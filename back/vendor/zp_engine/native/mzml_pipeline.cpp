#include <algorithm>
// Native mzML pipeline core. It never writes a final .zp file; ZpWriter owns
// final container assembly and atomic publication.
#include <array>
#include <atomic>
#include <bit>
#include <charconv>
#include <chrono>
#include <cctype>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <limits>
#include <mutex>
#include <optional>
#include <stdexcept>
#include <string>
#include <string_view>
#include <thread>
#include <vector>

#ifdef _WIN32
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <fcntl.h>
#include <io.h>
#include <windows.h>
#else
#include <dlfcn.h>
#include <fcntl.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>
#endif

namespace {

constexpr std::string_view kSpectrumOpen = "<spectrum ";
constexpr std::string_view kSpectrumClose = "</spectrum>";
constexpr std::string_view kBinaryArrayOpen = "<binaryDataArray";
constexpr std::string_view kBinaryArrayClose = "</binaryDataArray>";
constexpr std::string_view kBinaryOpen = "<binary>";
constexpr std::string_view kBinaryClose = "</binary>";
constexpr std::string_view kCvParamOpen = "<cvParam ";
constexpr std::string_view kStreamMagic = "ZPNMZ1\r\n";
constexpr std::string_view kRecordMagic = "ZPNMZ2\r\n";
constexpr std::string_view kSpoolRecordMagic = "ZPNMZ3\r\n";
constexpr std::size_t kStreamBatchSize = 2048;

class MappedFile {
public:
    explicit MappedFile(const std::filesystem::path& path) {
#ifdef _WIN32
        file_ = CreateFileW(
            path.c_str(),
            GENERIC_READ,
            FILE_SHARE_READ,
            nullptr,
            OPEN_EXISTING,
            FILE_ATTRIBUTE_NORMAL,
            nullptr
        );
        if (file_ == INVALID_HANDLE_VALUE) {
            throw std::runtime_error("cannot open input file");
        }
        LARGE_INTEGER size{};
        if (!GetFileSizeEx(file_, &size) || size.QuadPart <= 0) {
            throw std::runtime_error("cannot read input file size");
        }
        size_ = static_cast<std::size_t>(size.QuadPart);
        mapping_ = CreateFileMappingW(file_, nullptr, PAGE_READONLY, 0, 0, nullptr);
        if (mapping_ == nullptr) {
            throw std::runtime_error("cannot create input mapping");
        }
        data_ = static_cast<const char*>(
            MapViewOfFile(mapping_, FILE_MAP_READ, 0, 0, 0)
        );
        if (data_ == nullptr) {
            throw std::runtime_error("cannot map input file");
        }
#else
        file_ = open(path.c_str(), O_RDONLY);
        if (file_ < 0) {
            throw std::runtime_error("cannot open input file");
        }
        struct stat info {};
        if (fstat(file_, &info) != 0 || info.st_size <= 0) {
            throw std::runtime_error("cannot read input file size");
        }
        size_ = static_cast<std::size_t>(info.st_size);
        void* mapped = mmap(nullptr, size_, PROT_READ, MAP_PRIVATE, file_, 0);
        if (mapped == MAP_FAILED) {
            throw std::runtime_error("cannot map input file");
        }
        data_ = static_cast<const char*>(mapped);
#endif
    }

    MappedFile(const MappedFile&) = delete;
    MappedFile& operator=(const MappedFile&) = delete;

    ~MappedFile() {
#ifdef _WIN32
        if (data_ != nullptr) {
            UnmapViewOfFile(data_);
        }
        if (mapping_ != nullptr) {
            CloseHandle(mapping_);
        }
        if (file_ != INVALID_HANDLE_VALUE) {
            CloseHandle(file_);
        }
#else
        if (data_ != nullptr) {
            munmap(const_cast<char*>(data_), size_);
        }
        if (file_ >= 0) {
            close(file_);
        }
#endif
    }

    [[nodiscard]] std::string_view view() const {
        return {data_, size_};
    }

private:
    const char* data_ = nullptr;
    std::size_t size_ = 0;
#ifdef _WIN32
    HANDLE file_ = INVALID_HANDLE_VALUE;
    HANDLE mapping_ = nullptr;
#else
    int file_ = -1;
#endif
};

using UncompressFunction = int (*)(
    unsigned char*,
    unsigned long*,
    const unsigned char*,
    unsigned long
);

class ZlibRuntime {
public:
    ZlibRuntime() {
#ifdef _WIN32
        for (const char* name : {"zlib1.dll", "zlib.dll"}) {
            module_ = LoadLibraryA(name);
            if (module_ != nullptr) {
                break;
            }
        }
        if (module_ != nullptr) {
            uncompress_ = reinterpret_cast<UncompressFunction>(
                GetProcAddress(module_, "uncompress")
            );
        }
#else
        module_ = dlopen("libz.so.1", RTLD_NOW | RTLD_LOCAL);
        if (module_ != nullptr) {
            uncompress_ = reinterpret_cast<UncompressFunction>(
                dlsym(module_, "uncompress")
            );
        }
#endif
    }

    ZlibRuntime(const ZlibRuntime&) = delete;
    ZlibRuntime& operator=(const ZlibRuntime&) = delete;

    ~ZlibRuntime() {
#ifdef _WIN32
        if (module_ != nullptr) {
            FreeLibrary(module_);
        }
#else
        if (module_ != nullptr) {
            dlclose(module_);
        }
#endif
    }

    void decompress(
        const std::vector<std::uint8_t>& source,
        std::vector<std::uint8_t>& target
    ) const {
        if (uncompress_ == nullptr) {
            throw std::runtime_error(
                "zlib runtime with uncompress() is unavailable"
            );
        }
        unsigned long target_size = static_cast<unsigned long>(target.size());
        const int code = uncompress_(
            target.data(),
            &target_size,
            source.data(),
            static_cast<unsigned long>(source.size())
        );
        if (code != 0 || target_size != target.size()) {
            throw std::runtime_error("zlib decompression failed or length changed");
        }
    }

private:
#ifdef _WIN32
    HMODULE module_ = nullptr;
#else
    void* module_ = nullptr;
#endif
    UncompressFunction uncompress_ = nullptr;
};

struct SpectrumRange {
    std::size_t begin;
    std::size_t end;
};

struct WorkerStats {
    std::uint64_t spectra = 0;
    std::uint64_t arrays = 0;
    std::uint64_t decoded_bytes = 0;
    std::uint64_t normalized_float64_bytes = 0;
    std::uint64_t cv_params = 0;
    std::uint64_t checksum_xor = 0;
    std::uint64_t errors = 0;
};

struct NormalizedArray {
    std::vector<std::uint8_t> bytes;
    std::size_t decoded_bytes = 0;
    std::uint64_t checksum = 0;
    std::array<std::uint8_t, 32> sha256{};
};

struct DecodedSpectrum {
    std::string metadata_xml;
    std::string fields_json;
    NormalizedArray mz;
    NormalizedArray intensity;
    std::uint64_t cv_params = 0;
};

[[nodiscard]] std::optional<std::string_view> attribute(
    std::string_view tag,
    std::string_view name
);

struct CvParam {
    std::string_view accession;
    std::string_view name;
    std::string_view value;
    std::string_view unit_accession;
    std::string_view unit_name;
};

[[nodiscard]] std::string_view opening_tag(std::string_view block) {
    const std::size_t end = block.find('>');
    if (end == std::string_view::npos) {
        throw std::runtime_error("XML opening tag is incomplete");
    }
    return block.substr(0, end + 1);
}

[[nodiscard]] std::optional<std::string_view> child_block(
    std::string_view parent,
    std::string_view opening,
    std::string_view closing
) {
    const std::size_t begin = parent.find(opening);
    if (begin == std::string_view::npos) {
        return std::nullopt;
    }
    const std::size_t end = parent.find(closing, begin);
    if (end == std::string_view::npos) {
        throw std::runtime_error("XML child closing tag is missing");
    }
    return parent.substr(begin, end + closing.size() - begin);
}

[[nodiscard]] std::size_t find_element(
    std::string_view parent,
    std::string_view tag_name,
    std::size_t position
) {
    const std::string marker = "<" + std::string(tag_name);
    while (true) {
        const std::size_t found = parent.find(marker, position);
        if (found == std::string_view::npos) {
            return found;
        }
        const std::size_t after = found + marker.size();
        if (
            after < parent.size()
            && (parent[after] == '>' || std::isspace(
                static_cast<unsigned char>(parent[after])
            ))
        ) {
            return found;
        }
        position = after;
    }
}

[[nodiscard]] std::vector<std::string_view> element_blocks(
    std::string_view parent,
    std::string_view tag_name
) {
    std::vector<std::string_view> result;
    const std::string closing = "</" + std::string(tag_name) + ">";
    std::size_t position = 0;
    while (true) {
        const std::size_t begin = find_element(parent, tag_name, position);
        if (begin == std::string_view::npos) {
            break;
        }
        const std::size_t end = parent.find(closing, begin);
        if (end == std::string_view::npos) {
            throw std::runtime_error("XML element closing tag is missing");
        }
        result.push_back(parent.substr(begin, end + closing.size() - begin));
        position = end + closing.size();
    }
    return result;
}

[[nodiscard]] std::optional<std::string_view> element_block(
    std::string_view parent,
    std::string_view tag_name
) {
    const std::vector<std::string_view> values =
        element_blocks(parent, tag_name);
    if (values.empty()) {
        return std::nullopt;
    }
    return values.front();
}

[[nodiscard]] std::vector<std::string_view> child_blocks(
    std::string_view parent,
    std::string_view opening,
    std::string_view closing
) {
    std::vector<std::string_view> result;
    std::size_t position = 0;
    while (true) {
        const std::size_t begin = parent.find(opening, position);
        if (begin == std::string_view::npos) {
            break;
        }
        const std::size_t end = parent.find(closing, begin);
        if (end == std::string_view::npos) {
            throw std::runtime_error("XML repeated child closing tag is missing");
        }
        result.push_back(parent.substr(begin, end + closing.size() - begin));
        position = end + closing.size();
    }
    return result;
}

[[nodiscard]] std::vector<CvParam> cv_params(std::string_view block) {
    std::vector<CvParam> result;
    std::size_t position = 0;
    while (
        (position = block.find(kCvParamOpen, position))
        != std::string_view::npos
    ) {
        const std::size_t end = block.find('>', position);
        if (end == std::string_view::npos) {
            throw std::runtime_error("cvParam opening tag is incomplete");
        }
        const std::string_view tag = block.substr(position, end + 1 - position);
        result.push_back(
            CvParam{
                attribute(tag, "accession").value_or(std::string_view{}),
                attribute(tag, "name").value_or(std::string_view{}),
                attribute(tag, "value").value_or(std::string_view{}),
                attribute(tag, "unitAccession").value_or(std::string_view{}),
                attribute(tag, "unitName").value_or(std::string_view{}),
            }
        );
        position = end + 1;
    }
    return result;
}

[[nodiscard]] const CvParam* named_param(
    const std::vector<CvParam>& params,
    std::string_view name
) {
    const auto found = std::find_if(
        params.begin(),
        params.end(),
        [name](const CvParam& item) { return item.name == name; }
    );
    return found == params.end() ? nullptr : &*found;
}

void append_utf8(std::string& target, std::uint32_t codepoint) {
    if (codepoint > 0x10ffffU || (codepoint >= 0xd800U && codepoint <= 0xdfffU)) {
        throw std::runtime_error("invalid XML numeric character reference");
    }
    if (codepoint <= 0x7fU) {
        target.push_back(static_cast<char>(codepoint));
    } else if (codepoint <= 0x7ffU) {
        target.push_back(static_cast<char>(0xc0U | (codepoint >> 6U)));
        target.push_back(static_cast<char>(0x80U | (codepoint & 0x3fU)));
    } else if (codepoint <= 0xffffU) {
        target.push_back(static_cast<char>(0xe0U | (codepoint >> 12U)));
        target.push_back(static_cast<char>(0x80U | ((codepoint >> 6U) & 0x3fU)));
        target.push_back(static_cast<char>(0x80U | (codepoint & 0x3fU)));
    } else {
        target.push_back(static_cast<char>(0xf0U | (codepoint >> 18U)));
        target.push_back(static_cast<char>(0x80U | ((codepoint >> 12U) & 0x3fU)));
        target.push_back(static_cast<char>(0x80U | ((codepoint >> 6U) & 0x3fU)));
        target.push_back(static_cast<char>(0x80U | (codepoint & 0x3fU)));
    }
}

[[nodiscard]] std::string xml_unescape(std::string_view source) {
    std::string result;
    result.reserve(source.size());
    for (std::size_t position = 0; position < source.size();) {
        if (source[position] != '&') {
            result.push_back(source[position++]);
            continue;
        }
        const std::size_t end = source.find(';', position + 1);
        if (end == std::string_view::npos) {
            throw std::runtime_error("unterminated XML entity");
        }
        const std::string_view entity = source.substr(
            position + 1,
            end - position - 1
        );
        if (entity == "amp") {
            result.push_back('&');
        } else if (entity == "lt") {
            result.push_back('<');
        } else if (entity == "gt") {
            result.push_back('>');
        } else if (entity == "quot") {
            result.push_back('"');
        } else if (entity == "apos") {
            result.push_back('\'');
        } else if (!entity.empty() && entity.front() == '#') {
            const bool hexadecimal =
                entity.size() > 1 && (entity[1] == 'x' || entity[1] == 'X');
            const std::string_view digits = entity.substr(hexadecimal ? 2 : 1);
            std::uint32_t codepoint = 0;
            const auto parsed = std::from_chars(
                digits.data(),
                digits.data() + digits.size(),
                codepoint,
                hexadecimal ? 16 : 10
            );
            if (
                digits.empty()
                || parsed.ec != std::errc{}
                || parsed.ptr != digits.data() + digits.size()
            ) {
                throw std::runtime_error("invalid XML numeric character reference");
            }
            append_utf8(result, codepoint);
        } else {
            throw std::runtime_error("unsupported XML entity");
        }
        position = end + 1;
    }
    return result;
}

void append_json_string(std::string& target, std::string_view raw) {
    const std::string value = xml_unescape(raw);
    target.push_back('"');
    for (const unsigned char character : value) {
        switch (character) {
            case '"':
                target.append("\\\"");
                break;
            case '\\':
                target.append("\\\\");
                break;
            case '\b':
                target.append("\\b");
                break;
            case '\f':
                target.append("\\f");
                break;
            case '\n':
                target.append("\\n");
                break;
            case '\r':
                target.append("\\r");
                break;
            case '\t':
                target.append("\\t");
                break;
            default:
                if (character < 0x20U) {
                    constexpr char digits[] = "0123456789abcdef";
                    target.append("\\u00");
                    target.push_back(digits[character >> 4U]);
                    target.push_back(digits[character & 0x0fU]);
                } else {
                    target.push_back(static_cast<char>(character));
                }
        }
    }
    target.push_back('"');
}

void append_json_optional(
    std::string& target,
    std::optional<std::string_view> value
) {
    if (!value.has_value()) {
        target.append("null");
    } else {
        append_json_string(target, *value);
    }
}

void append_json_param_value(std::string& target, const CvParam* value) {
    if (value == nullptr || value->value.empty()) {
        target.append("null");
    } else {
        append_json_string(target, value->value);
    }
}

void append_json_field_prefix(
    std::string& target,
    std::string_view name,
    bool& first
) {
    if (!first) {
        target.push_back(',');
    }
    first = false;
    append_json_string(target, name);
    target.push_back(':');
}

[[nodiscard]] bool contains_ascii_case_insensitive(
    std::string_view source,
    std::string_view needle
) {
    if (needle.empty() || source.size() < needle.size()) {
        return false;
    }
    for (std::size_t offset = 0; offset + needle.size() <= source.size(); ++offset) {
        bool equal = true;
        for (std::size_t index = 0; index < needle.size(); ++index) {
            const unsigned char left =
                static_cast<unsigned char>(source[offset + index]);
            const unsigned char right =
                static_cast<unsigned char>(needle[index]);
            if (std::tolower(left) != std::tolower(right)) {
                equal = false;
                break;
            }
        }
        if (equal) {
            return true;
        }
    }
    return false;
}

[[nodiscard]] std::optional<std::string_view> attribute(
    std::string_view tag,
    std::string_view name
) {
    std::size_t position = 0;
    while ((position = tag.find(name, position)) != std::string_view::npos) {
        const bool left_ok = position == 0
            || tag[position - 1] == ' '
            || tag[position - 1] == '\t'
            || tag[position - 1] == '\n';
        std::size_t cursor = position + name.size();
        while (cursor < tag.size() && (tag[cursor] == ' ' || tag[cursor] == '\t')) {
            ++cursor;
        }
        if (!left_ok || cursor >= tag.size() || tag[cursor] != '=') {
            position += name.size();
            continue;
        }
        ++cursor;
        while (cursor < tag.size() && (tag[cursor] == ' ' || tag[cursor] == '\t')) {
            ++cursor;
        }
        if (cursor >= tag.size() || (tag[cursor] != '"' && tag[cursor] != '\'')) {
            return std::nullopt;
        }
        const char quote = tag[cursor++];
        const std::size_t end = tag.find(quote, cursor);
        if (end == std::string_view::npos) {
            return std::nullopt;
        }
        return tag.substr(cursor, end - cursor);
    }
    return std::nullopt;
}

[[nodiscard]] std::size_t parse_size(
    std::optional<std::string_view> text,
    std::string_view field
) {
    if (!text.has_value()) {
        throw std::runtime_error(std::string(field) + " is missing");
    }
    std::size_t value = 0;
    const char* begin = text->data();
    const char* end = begin + text->size();
    const auto result = std::from_chars(begin, end, value);
    if (result.ec != std::errc{} || result.ptr != end) {
        throw std::runtime_error(std::string(field) + " is invalid");
    }
    return value;
}

[[nodiscard]] std::vector<std::uint8_t> decode_base64(std::string_view encoded) {
    static const std::array<std::int16_t, 256> table = [] {
        std::array<std::int16_t, 256> values{};
        values.fill(-1);
        constexpr std::string_view alphabet =
            "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
        for (std::size_t index = 0; index < alphabet.size(); ++index) {
            values[static_cast<unsigned char>(alphabet[index])] =
                static_cast<std::int16_t>(index);
        }
        return values;
    }();

    std::vector<std::uint8_t> result;
    result.reserve(encoded.size() * 3 / 4);
    std::uint32_t buffer = 0;
    int bits = 0;
    for (const unsigned char character : encoded) {
        if (character == '=') {
            break;
        }
        const std::int16_t value = table[character];
        if (value < 0) {
            if (
                character == ' '
                || character == '\t'
                || character == '\r'
                || character == '\n'
            ) {
                continue;
            }
            throw std::runtime_error("invalid base64 character");
        }
        buffer = (buffer << 6U) | static_cast<std::uint32_t>(value);
        bits += 6;
        if (bits >= 8) {
            bits -= 8;
            result.push_back(
                static_cast<std::uint8_t>((buffer >> bits) & 0xffU)
            );
        }
    }
    return result;
}

[[nodiscard]] std::uint64_t fnv1a(
    const std::uint8_t* data,
    std::size_t size
) {
    std::uint64_t hash = 1469598103934665603ULL;
    for (std::size_t index = 0; index < size; ++index) {
        hash ^= data[index];
        hash *= 1099511628211ULL;
    }
    return hash;
}

class Sha256 {
public:
    Sha256() = default;

    void update(const std::uint8_t* data, std::size_t size) {
        total_bytes_ += size;
        while (size) {
            const std::size_t take = std::min(size, block_.size() - buffered_);
            std::memcpy(block_.data() + buffered_, data, take);
            buffered_ += take;
            data += take;
            size -= take;
            if (buffered_ == block_.size()) {
                transform(block_.data());
                buffered_ = 0;
            }
        }
    }

    [[nodiscard]] std::array<std::uint8_t, 32> finish() {
        const std::uint64_t bit_length =
            static_cast<std::uint64_t>(total_bytes_) * 8U;
        block_[buffered_++] = 0x80U;
        if (buffered_ > 56) {
            std::fill(block_.begin() + buffered_, block_.end(), 0);
            transform(block_.data());
            buffered_ = 0;
        }
        std::fill(block_.begin() + buffered_, block_.begin() + 56, 0);
        for (std::size_t index = 0; index < 8; ++index) {
            block_[63 - index] = static_cast<std::uint8_t>(
                bit_length >> (index * 8U)
            );
        }
        transform(block_.data());
        std::array<std::uint8_t, 32> result{};
        for (std::size_t index = 0; index < state_.size(); ++index) {
            for (std::size_t byte = 0; byte < 4; ++byte) {
                result[index * 4 + byte] = static_cast<std::uint8_t>(
                    state_[index] >> ((3 - byte) * 8U)
                );
            }
        }
        return result;
    }

private:
    [[nodiscard]] static std::uint32_t rotate_right(
        std::uint32_t value,
        unsigned int shift
    ) {
        return (value >> shift) | (value << (32U - shift));
    }

    void transform(const std::uint8_t* block) {
        static constexpr std::array<std::uint32_t, 64> constants = {
            0x428a2f98U, 0x71374491U, 0xb5c0fbcfU, 0xe9b5dba5U,
            0x3956c25bU, 0x59f111f1U, 0x923f82a4U, 0xab1c5ed5U,
            0xd807aa98U, 0x12835b01U, 0x243185beU, 0x550c7dc3U,
            0x72be5d74U, 0x80deb1feU, 0x9bdc06a7U, 0xc19bf174U,
            0xe49b69c1U, 0xefbe4786U, 0x0fc19dc6U, 0x240ca1ccU,
            0x2de92c6fU, 0x4a7484aaU, 0x5cb0a9dcU, 0x76f988daU,
            0x983e5152U, 0xa831c66dU, 0xb00327c8U, 0xbf597fc7U,
            0xc6e00bf3U, 0xd5a79147U, 0x06ca6351U, 0x14292967U,
            0x27b70a85U, 0x2e1b2138U, 0x4d2c6dfcU, 0x53380d13U,
            0x650a7354U, 0x766a0abbU, 0x81c2c92eU, 0x92722c85U,
            0xa2bfe8a1U, 0xa81a664bU, 0xc24b8b70U, 0xc76c51a3U,
            0xd192e819U, 0xd6990624U, 0xf40e3585U, 0x106aa070U,
            0x19a4c116U, 0x1e376c08U, 0x2748774cU, 0x34b0bcb5U,
            0x391c0cb3U, 0x4ed8aa4aU, 0x5b9cca4fU, 0x682e6ff3U,
            0x748f82eeU, 0x78a5636fU, 0x84c87814U, 0x8cc70208U,
            0x90befffaU, 0xa4506cebU, 0xbef9a3f7U, 0xc67178f2U,
        };
        std::array<std::uint32_t, 64> words{};
        for (std::size_t index = 0; index < 16; ++index) {
            words[index] =
                (static_cast<std::uint32_t>(block[index * 4]) << 24U)
                | (static_cast<std::uint32_t>(block[index * 4 + 1]) << 16U)
                | (static_cast<std::uint32_t>(block[index * 4 + 2]) << 8U)
                | static_cast<std::uint32_t>(block[index * 4 + 3]);
        }
        for (std::size_t index = 16; index < words.size(); ++index) {
            const std::uint32_t left =
                rotate_right(words[index - 15], 7)
                ^ rotate_right(words[index - 15], 18)
                ^ (words[index - 15] >> 3U);
            const std::uint32_t right =
                rotate_right(words[index - 2], 17)
                ^ rotate_right(words[index - 2], 19)
                ^ (words[index - 2] >> 10U);
            words[index] = words[index - 16] + left
                + words[index - 7] + right;
        }
        std::uint32_t a = state_[0];
        std::uint32_t b = state_[1];
        std::uint32_t c = state_[2];
        std::uint32_t d = state_[3];
        std::uint32_t e = state_[4];
        std::uint32_t f = state_[5];
        std::uint32_t g = state_[6];
        std::uint32_t h = state_[7];
        for (std::size_t index = 0; index < words.size(); ++index) {
            const std::uint32_t upper =
                rotate_right(e, 6) ^ rotate_right(e, 11)
                ^ rotate_right(e, 25);
            const std::uint32_t choice = (e & f) ^ (~e & g);
            const std::uint32_t first =
                h + upper + choice + constants[index] + words[index];
            const std::uint32_t lower =
                rotate_right(a, 2) ^ rotate_right(a, 13)
                ^ rotate_right(a, 22);
            const std::uint32_t majority =
                (a & b) ^ (a & c) ^ (b & c);
            const std::uint32_t second = lower + majority;
            h = g;
            g = f;
            f = e;
            e = d + first;
            d = c;
            c = b;
            b = a;
            a = first + second;
        }
        state_[0] += a;
        state_[1] += b;
        state_[2] += c;
        state_[3] += d;
        state_[4] += e;
        state_[5] += f;
        state_[6] += g;
        state_[7] += h;
    }

    std::array<std::uint32_t, 8> state_ = {
        0x6a09e667U,
        0xbb67ae85U,
        0x3c6ef372U,
        0xa54ff53aU,
        0x510e527fU,
        0x9b05688cU,
        0x1f83d9abU,
        0x5be0cd19U,
    };
    std::array<std::uint8_t, 64> block_{};
    std::size_t total_bytes_ = 0;
    std::size_t buffered_ = 0;
};

[[nodiscard]] std::array<std::uint8_t, 32> sha256(
    const std::vector<std::uint8_t>& bytes
) {
    Sha256 digest;
    digest.update(bytes.data(), bytes.size());
    return digest.finish();
}

[[nodiscard]] std::string hex_digest(
    const std::array<std::uint8_t, 32>& digest
) {
    constexpr char alphabet[] = "0123456789abcdef";
    std::string result(64, '0');
    for (std::size_t index = 0; index < digest.size(); ++index) {
        result[index * 2] = alphabet[digest[index] >> 4U];
        result[index * 2 + 1] = alphabet[digest[index] & 0x0fU];
    }
    return result;
}

[[nodiscard]] NormalizedArray normalize_array(
    const std::vector<std::uint8_t>& bytes,
    bool float32,
    std::size_t value_count
) {
    NormalizedArray result;
    result.decoded_bytes = bytes.size();
    if (!float32) {
        if (bytes.size() != value_count * sizeof(double)) {
            throw std::runtime_error("float64 array length mismatch");
        }
        result.bytes = bytes;
        result.checksum = fnv1a(result.bytes.data(), result.bytes.size());
        result.sha256 = sha256(result.bytes);
        return result;
    }
    if (bytes.size() != value_count * sizeof(float)) {
        throw std::runtime_error("float32 array length mismatch");
    }
    result.bytes.resize(value_count * sizeof(double));
    for (std::size_t index = 0; index < value_count; ++index) {
        float source = 0.0F;
        std::memcpy(
            &source,
            bytes.data() + index * sizeof(float),
            sizeof(float)
        );
        const double normalized = static_cast<double>(source);
        std::memcpy(
            result.bytes.data() + index * sizeof(double),
            &normalized,
            sizeof(double)
        );
    }
    result.checksum = fnv1a(result.bytes.data(), result.bytes.size());
    result.sha256 = sha256(result.bytes);
    return result;
}

void validate_normalized_array(
    const NormalizedArray& array,
    bool require_nonnegative
) {
    if (array.bytes.size() % sizeof(double)) {
        throw std::runtime_error("normalized float64 array is misaligned");
    }
    for (
        std::size_t offset = 0;
        offset < array.bytes.size();
        offset += sizeof(double)
    ) {
        double value = 0;
        std::memcpy(&value, array.bytes.data() + offset, sizeof(value));
        if (!std::isfinite(value) || (require_nonnegative && value < 0)) {
            throw std::runtime_error(
                "normalized array contains an invalid numeric value"
            );
        }
    }
}

[[nodiscard]] std::uint64_t mix_checksum(
    std::uint64_t hash,
    std::uint64_t ordinal
) {
    std::uint64_t value = hash ^ (ordinal + 0x9e3779b97f4a7c15ULL);
    value = (value ^ (value >> 30U)) * 0xbf58476d1ce4e5b9ULL;
    value = (value ^ (value >> 27U)) * 0x94d049bb133111ebULL;
    return value ^ (value >> 31U);
}

[[nodiscard]] std::string strip_binary_payloads(std::string_view spectrum) {
    std::string stripped;
    stripped.reserve(spectrum.size() / 3);
    std::size_t position = 0;
    while (true) {
        const std::size_t binary_start = spectrum.find(kBinaryOpen, position);
        if (binary_start == std::string_view::npos) {
            stripped.append(spectrum.substr(position));
            break;
        }
        const std::size_t binary_end = spectrum.find(kBinaryClose, binary_start);
        if (binary_end == std::string_view::npos) {
            throw std::runtime_error("binary closing tag is missing");
        }
        const std::size_t payload_start = binary_start + kBinaryOpen.size();
        stripped.append(spectrum.substr(position, payload_start - position));
        stripped.append(kBinaryClose);
        position = binary_end + kBinaryClose.size();
    }
    return stripped;
}

[[nodiscard]] std::string build_fields_json(std::string_view spectrum) {
    const std::string_view spectrum_tag = opening_tag(spectrum);
    const std::size_t content_start = spectrum_tag.size();
    std::size_t top_end = spectrum.find("<scanList", content_start);
    for (const std::string_view marker : {
        std::string_view{"<precursorList"},
        std::string_view{"<productList"},
        std::string_view{"<binaryDataArrayList"},
        std::string_view{"</spectrum>"},
    }) {
        const std::size_t found = spectrum.find(marker, content_start);
        if (found != std::string_view::npos) {
            top_end = top_end == std::string_view::npos
                ? found
                : std::min(top_end, found);
        }
    }
    if (top_end == std::string_view::npos) {
        throw std::runtime_error("spectrum metadata boundary is missing");
    }
    const std::vector<CvParam> top = cv_params(
        spectrum.substr(content_start, top_end - content_start)
    );

    const std::optional<std::string_view> scan =
        element_block(spectrum, "scan");
    std::vector<CvParam> scan_params;
    std::vector<CvParam> window_params;
    std::optional<std::string_view> scan_tag;
    if (scan.has_value()) {
        scan_tag = opening_tag(*scan);
        std::size_t scan_param_end = scan->find("<scanWindowList");
        if (scan_param_end == std::string_view::npos) {
            scan_param_end = scan->find("</scan>");
        }
        scan_params = cv_params(
            scan->substr(scan_tag->size(), scan_param_end - scan_tag->size())
        );
        const std::optional<std::string_view> window =
            element_block(*scan, "scanWindow");
        if (window.has_value()) {
            window_params = cv_params(*window);
        }
    }

    const CvParam* ms_level = named_param(top, "ms level");
    const CvParam* rt = named_param(scan_params, "scan start time");
    const CvParam* filter = named_param(scan_params, "filter string");
    const CvParam* total_ion_current = named_param(top, "total ion current");
    const CvParam* base_peak_mz = named_param(top, "base peak m/z");
    const CvParam* base_peak_intensity =
        named_param(top, "base peak intensity");
    const CvParam* lowest_observed_mz =
        named_param(top, "lowest observed m/z");
    const CvParam* highest_observed_mz =
        named_param(top, "highest observed m/z");
    const CvParam* scan_window_lower =
        named_param(window_params, "scan window lower limit");
    const CvParam* scan_window_upper =
        named_param(window_params, "scan window upper limit");

    std::optional<std::string_view> mz_dtype;
    std::optional<std::string_view> intensity_dtype;
    std::optional<std::string_view> mz_compression;
    std::optional<std::string_view> intensity_compression;
    std::vector<std::string> auxiliary_json;
    for (const std::string_view block : child_blocks(
        spectrum,
        kBinaryArrayOpen,
        kBinaryArrayClose
    )) {
        const std::vector<CvParam> params = cv_params(block);
        const bool is_mz =
            block.find("MS:1000514") != std::string_view::npos;
        const bool is_intensity =
            block.find("MS:1000515") != std::string_view::npos;
        const std::optional<std::string_view> dtype =
            block.find("MS:1000521") != std::string_view::npos
            ? std::optional<std::string_view>{"float32"}
            : block.find("MS:1000523") != std::string_view::npos
            ? std::optional<std::string_view>{"float64"}
            : block.find("MS:1000519") != std::string_view::npos
            ? std::optional<std::string_view>{"int32"}
            : block.find("MS:1000522") != std::string_view::npos
            ? std::optional<std::string_view>{"int64"}
            : std::nullopt;
        const std::optional<std::string_view> compression =
            block.find("MS:1000574") != std::string_view::npos
            ? std::optional<std::string_view>{"zlib"}
            : block.find("MS:1000576") != std::string_view::npos
            ? std::optional<std::string_view>{"none"}
            : std::nullopt;
        if (is_mz) {
            mz_dtype = dtype;
            mz_compression = compression;
            continue;
        }
        if (is_intensity) {
            intensity_dtype = dtype;
            intensity_compression = compression;
            continue;
        }
        const auto semantic = std::find_if(
            params.begin(),
            params.end(),
            [](const CvParam& item) {
                return item.accession == "MS:1000786"
                    || item.accession == "MS:1000595";
            }
        );
        std::string item;
        item.push_back('{');
        bool first = true;
        auto add_optional = [&](std::string_view name, auto value) {
            append_json_field_prefix(item, name, first);
            append_json_optional(item, value);
        };
        add_optional(
            "accession",
            semantic == params.end()
                ? std::optional<std::string_view>{}
                : std::optional<std::string_view>{semantic->accession}
        );
        add_optional(
            "name",
            semantic == params.end()
                ? std::optional<std::string_view>{}
                : std::optional<std::string_view>{
                    semantic->value.empty() ? semantic->name : semantic->value
                }
        );
        add_optional("dtype", dtype);
        add_optional("compression", compression);
        add_optional(
            "unit_accession",
            semantic == params.end() || semantic->unit_accession.empty()
                ? std::optional<std::string_view>{}
                : std::optional<std::string_view>{semantic->unit_accession}
        );
        add_optional(
            "unit_name",
            semantic == params.end() || semantic->unit_name.empty()
                ? std::optional<std::string_view>{}
                : std::optional<std::string_view>{semantic->unit_name}
        );
        item.push_back('}');
        auxiliary_json.push_back(std::move(item));
    }

    std::string result;
    result.reserve(2048);
    result.push_back('{');
    bool first = true;
    auto add_optional = [&](std::string_view name, auto value) {
        append_json_field_prefix(result, name, first);
        append_json_optional(result, value);
    };
    auto add_param = [&](std::string_view name, const CvParam* value) {
        append_json_field_prefix(result, name, first);
        append_json_param_value(result, value);
    };
    auto add_bool = [&](std::string_view name, bool value) {
        append_json_field_prefix(result, name, first);
        result.append(value ? "true" : "false");
    };
    add_optional("source_index", attribute(spectrum_tag, "index"));
    add_optional("native_id", attribute(spectrum_tag, "id"));
    add_optional(
        "default_array_length",
        attribute(spectrum_tag, "defaultArrayLength")
    );
    add_optional("data_processing_ref", attribute(spectrum_tag, "dataProcessingRef"));
    add_param("ms_level", ms_level);
    add_param("source_rt_value", rt);
    add_optional(
        "source_rt_unit_accession",
        rt == nullptr || rt->unit_accession.empty()
            ? std::optional<std::string_view>{}
            : std::optional<std::string_view>{rt->unit_accession}
    );
    add_optional(
        "source_rt_unit_name",
        rt == nullptr || rt->unit_name.empty()
            ? std::optional<std::string_view>{}
            : std::optional<std::string_view>{rt->unit_name}
    );
    add_optional("source_mz_dtype", mz_dtype);
    add_optional("source_intensity_dtype", intensity_dtype);
    add_optional("source_mz_compression", mz_compression);
    add_optional("source_intensity_compression", intensity_compression);
    add_optional(
        "representation",
        named_param(top, "centroid spectrum") != nullptr
            ? std::optional<std::string_view>{"centroid"}
            : named_param(top, "profile spectrum") != nullptr
            ? std::optional<std::string_view>{"profile"}
            : std::optional<std::string_view>{"unknown"}
    );
    add_optional(
        "polarity",
        named_param(top, "positive scan") != nullptr
            ? std::optional<std::string_view>{"positive"}
            : named_param(top, "negative scan") != nullptr
            ? std::optional<std::string_view>{"negative"}
            : std::optional<std::string_view>{}
    );
    add_bool(
        "has_dia_semantics",
        contains_ascii_case_insensitive(
            spectrum,
            "data independent acquisition"
        )
    );
    add_bool(
        "has_ion_mobility",
        contains_ascii_case_insensitive(spectrum, "ion mobility")
            || contains_ascii_case_insensitive(spectrum, "drift time")
    );
    add_param("total_ion_current", total_ion_current);
    add_param("base_peak_mz", base_peak_mz);
    add_param("base_peak_intensity", base_peak_intensity);
    add_param("lowest_observed_mz", lowest_observed_mz);
    add_param("highest_observed_mz", highest_observed_mz);
    add_param("scan_window_lower", scan_window_lower);
    add_param("scan_window_upper", scan_window_upper);
    add_param("filter_string", filter);
    add_optional(
        "instrument_configuration_ref",
        scan_tag.has_value()
            ? attribute(*scan_tag, "instrumentConfigurationRef")
            : std::optional<std::string_view>{}
    );

    append_json_field_prefix(result, "auxiliary_arrays", first);
    result.push_back('[');
    for (std::size_t index = 0; index < auxiliary_json.size(); ++index) {
        if (index) {
            result.push_back(',');
        }
        result.append(auxiliary_json[index]);
    }
    result.push_back(']');

    append_json_field_prefix(result, "precursors", first);
    result.push_back('[');
    const std::vector<std::string_view> precursors =
        element_blocks(spectrum, "precursor");
    for (std::size_t precursor_index = 0;
         precursor_index < precursors.size();
         ++precursor_index) {
        if (precursor_index) {
            result.push_back(',');
        }
        const std::string_view precursor = precursors[precursor_index];
        const std::string_view precursor_tag = opening_tag(precursor);
        const std::vector<std::string_view> selected_ions =
            element_blocks(precursor, "selectedIon");
        std::vector<CvParam> ion_params;
        if (selected_ions.size() == 1) {
            ion_params = cv_params(selected_ions.front());
        }
        const CvParam* selected_mz =
            named_param(ion_params, "selected ion m/z");
        const CvParam* charge = named_param(ion_params, "charge state");
        const CvParam* intensity =
            named_param(ion_params, "peak intensity");
        const std::optional<std::string_view> isolation =
            element_block(precursor, "isolationWindow");
        const std::vector<CvParam> isolation_params =
            isolation.has_value()
            ? cv_params(*isolation)
            : std::vector<CvParam>{};
        const std::optional<std::string_view> activation =
            element_block(precursor, "activation");
        const std::vector<CvParam> activation_params =
            activation.has_value()
            ? cv_params(*activation)
            : std::vector<CvParam>{};
        const CvParam* collision =
            named_param(activation_params, "collision energy");

        std::string precursor_json;
        precursor_json.push_back('{');
        bool precursor_first = true;
        auto precursor_optional = [&](std::string_view name, auto value) {
            append_json_field_prefix(precursor_json, name, precursor_first);
            append_json_optional(precursor_json, value);
        };
        auto precursor_param = [&](std::string_view name, const CvParam* value) {
            append_json_field_prefix(precursor_json, name, precursor_first);
            append_json_param_value(precursor_json, value);
        };
        append_json_field_prefix(
            precursor_json,
            "selected_ion_count",
            precursor_first
        );
        precursor_json.append(std::to_string(selected_ions.size()));
        precursor_optional(
            "source_spectrum_ref",
            attribute(precursor_tag, "spectrumRef")
        );
        precursor_param("selected_ion_mz", selected_mz);
        precursor_param("charge", charge);
        append_json_field_prefix(
            precursor_json,
            "charge_present",
            precursor_first
        );
        precursor_json.append(charge == nullptr ? "false" : "true");
        precursor_param("intensity", intensity);
        precursor_param(
            "isolation_target_mz",
            named_param(isolation_params, "isolation window target m/z")
        );
        precursor_param(
            "isolation_lower_offset",
            named_param(isolation_params, "isolation window lower offset")
        );
        precursor_param(
            "isolation_upper_offset",
            named_param(isolation_params, "isolation window upper offset")
        );
        precursor_param("collision_energy", collision);
        precursor_optional(
            "collision_energy_unit_accession",
            collision == nullptr || collision->unit_accession.empty()
                ? std::optional<std::string_view>{}
                : std::optional<std::string_view>{collision->unit_accession}
        );
        precursor_optional(
            "collision_energy_unit_name",
            collision == nullptr || collision->unit_name.empty()
                ? std::optional<std::string_view>{}
                : std::optional<std::string_view>{collision->unit_name}
        );
        append_json_field_prefix(
            precursor_json,
            "activation_methods",
            precursor_first
        );
        precursor_json.push_back('[');
        bool first_method = true;
        for (const CvParam& method : activation_params) {
            if (
                method.accession == "MS:1000045"
                || method.name == "collision energy"
            ) {
                continue;
            }
            if (!first_method) {
                precursor_json.push_back(',');
            }
            first_method = false;
            precursor_json.push_back('{');
            bool method_first = true;
            auto method_value = [&](std::string_view name, auto value) {
                append_json_field_prefix(
                    precursor_json,
                    name,
                    method_first
                );
                append_json_optional(precursor_json, value);
            };
            method_value(
                "accession",
                std::optional<std::string_view>{method.accession}
            );
            method_value(
                "name",
                std::optional<std::string_view>{method.name}
            );
            method_value(
                "value",
                method.value.empty()
                    ? std::optional<std::string_view>{}
                    : std::optional<std::string_view>{method.value}
            );
            method_value(
                "unit_accession",
                method.unit_accession.empty()
                    ? std::optional<std::string_view>{}
                    : std::optional<std::string_view>{method.unit_accession}
            );
            method_value(
                "unit_name",
                method.unit_name.empty()
                    ? std::optional<std::string_view>{}
                    : std::optional<std::string_view>{method.unit_name}
            );
            precursor_json.push_back('}');
        }
        precursor_json.push_back(']');
        precursor_json.push_back('}');
        result.append(precursor_json);
    }
    result.push_back(']');
    result.push_back('}');
    return result;
}

[[nodiscard]] DecodedSpectrum decode_spectrum(
    std::string_view spectrum,
    const ZlibRuntime& zlib,
    bool include_metadata_xml = false,
    bool include_fields_json = false
) {
    const std::size_t opening_end = spectrum.find('>');
    if (opening_end == std::string_view::npos) {
        throw std::runtime_error("spectrum opening tag is incomplete");
    }
    const std::size_t value_count = parse_size(
        attribute(spectrum.substr(0, opening_end + 1), "defaultArrayLength"),
        "defaultArrayLength"
    );

    DecodedSpectrum result;
    if (include_metadata_xml) {
        result.metadata_xml = strip_binary_payloads(spectrum);
    }
    if (include_fields_json) {
        result.fields_json = build_fields_json(spectrum);
    }
    std::size_t cv_position = 0;
    while (
        (cv_position = spectrum.find(kCvParamOpen, cv_position))
        != std::string_view::npos
    ) {
        ++result.cv_params;
        cv_position += kCvParamOpen.size();
    }

    std::size_t position = opening_end + 1;
    bool has_mz = false;
    bool has_intensity = false;
    while (
        (position = spectrum.find(kBinaryArrayOpen, position))
        != std::string_view::npos
    ) {
        const std::size_t block_end = spectrum.find(kBinaryArrayClose, position);
        if (block_end == std::string_view::npos) {
            throw std::runtime_error("binaryDataArray closing tag is missing");
        }
        const std::string_view block = spectrum.substr(
            position,
            block_end + kBinaryArrayClose.size() - position
        );
        const bool is_mz =
            block.find("MS:1000514") != std::string_view::npos;
        const bool is_intensity =
            block.find("MS:1000515") != std::string_view::npos;
        const bool core_array = is_mz || is_intensity;
        if (core_array) {
            if ((is_mz && has_mz) || (is_intensity && has_intensity)) {
                throw std::runtime_error("duplicate core array semantic");
            }
            const bool float32 =
                block.find("MS:1000521") != std::string_view::npos;
            const bool float64 =
                block.find("MS:1000523") != std::string_view::npos;
            const bool compressed =
                block.find("MS:1000574") != std::string_view::npos;
            const bool uncompressed =
                block.find("MS:1000576") != std::string_view::npos;
            if ((!float32 && !float64) || (!compressed && !uncompressed)) {
                throw std::runtime_error("unsupported core array encoding");
            }
            const std::size_t binary_start = block.find(kBinaryOpen);
            const std::size_t binary_end = block.find(
                kBinaryClose,
                binary_start
            );
            if (
                binary_start == std::string_view::npos
                || binary_end == std::string_view::npos
            ) {
                throw std::runtime_error("binary payload is missing");
            }
            const std::string_view encoded = block.substr(
                binary_start + kBinaryOpen.size(),
                binary_end - binary_start - kBinaryOpen.size()
            );
            const std::vector<std::uint8_t> decoded = decode_base64(encoded);
            const std::size_t source_width = float32
                ? sizeof(float)
                : sizeof(double);
            std::vector<std::uint8_t> raw(value_count * source_width);
            if (compressed) {
                zlib.decompress(decoded, raw);
            } else {
                if (decoded.size() != raw.size()) {
                    throw std::runtime_error("uncompressed array length mismatch");
                }
                raw = decoded;
            }
            NormalizedArray normalized = normalize_array(
                raw,
                float32,
                value_count
            );
            if (is_mz) {
                result.mz = std::move(normalized);
                has_mz = true;
            } else {
                result.intensity = std::move(normalized);
                has_intensity = true;
            }
        }
        position = block_end + kBinaryArrayClose.size();
    }
    if (!has_mz || !has_intensity) {
        throw std::runtime_error("spectrum does not contain two core arrays");
    }
    validate_normalized_array(result.mz, true);
    validate_normalized_array(result.intensity, false);
    if (include_fields_json) {
        if (result.fields_json.empty() || result.fields_json.back() != '}') {
            throw std::runtime_error("native metadata JSON is incomplete");
        }
        result.fields_json.pop_back();
        result.fields_json.append(",\"mz_sha256\":\"");
        result.fields_json.append(hex_digest(result.mz.sha256));
        result.fields_json.append("\",\"intensity_sha256\":\"");
        result.fields_json.append(hex_digest(result.intensity.sha256));
        result.fields_json.append("\"}");
    }
    return result;
}

void process_spectrum(
    std::string_view spectrum,
    std::uint64_t spectrum_ordinal,
    const ZlibRuntime& zlib,
    WorkerStats& stats
) {
    const DecodedSpectrum decoded = decode_spectrum(spectrum, zlib);
    stats.cv_params += decoded.cv_params;
    stats.arrays += 2;
    stats.decoded_bytes += (
        decoded.mz.decoded_bytes + decoded.intensity.decoded_bytes
    );
    stats.normalized_float64_bytes += (
        decoded.mz.bytes.size() + decoded.intensity.bytes.size()
    );
    stats.checksum_xor ^= mix_checksum(
        decoded.mz.checksum,
        spectrum_ordinal * 2
    );
    stats.checksum_xor ^= mix_checksum(
        decoded.intensity.checksum,
        spectrum_ordinal * 2 + 1
    );
    ++stats.spectra;
}

[[nodiscard]] std::vector<SpectrumRange> find_spectra(std::string_view source) {
    std::vector<SpectrumRange> ranges;
    std::size_t position = 0;
    while (true) {
        const std::size_t begin = source.find(kSpectrumOpen, position);
        if (begin == std::string_view::npos) {
            break;
        }
        const std::size_t closing = source.find(kSpectrumClose, begin);
        if (closing == std::string_view::npos) {
            throw std::runtime_error("spectrum closing tag is missing");
        }
        const std::size_t end = closing + kSpectrumClose.size();
        ranges.push_back({begin, end});
        position = end;
    }
    return ranges;
}

[[nodiscard]] unsigned int parse_thread_count(std::string_view text) {
    unsigned int thread_count = 0;
    const auto result = std::from_chars(
        text.data(),
        text.data() + text.size(),
        thread_count
    );
    if (
        result.ec != std::errc{}
        || result.ptr != text.data() + text.size()
        || thread_count == 0
        || thread_count > 64
    ) {
        throw std::runtime_error("threads must be an integer from 1 to 64");
    }
    return thread_count;
}

void write_bytes(const void* data, std::size_t size) {
    if (size > static_cast<std::size_t>(std::numeric_limits<std::streamsize>::max())) {
        throw std::runtime_error("stream record exceeds platform write limit");
    }
    std::cout.write(
        static_cast<const char*>(data),
        static_cast<std::streamsize>(size)
    );
    if (!std::cout) {
        throw std::runtime_error("cannot write native stream");
    }
}

void write_u32(std::uint32_t value) {
    write_bytes(&value, sizeof(value));
}

void write_u64(std::uint64_t value) {
    write_bytes(&value, sizeof(value));
}

void write_spool(std::ofstream& spool, const void* data, std::size_t size) {
    if (size > static_cast<std::size_t>(std::numeric_limits<std::streamsize>::max())) {
        throw std::runtime_error("spool record exceeds platform write limit");
    }
    spool.write(
        static_cast<const char*>(data),
        static_cast<std::streamsize>(size)
    );
    if (!spool) {
        throw std::runtime_error("cannot write native spool");
    }
}

[[nodiscard]] std::uint64_t spool_offset(std::ofstream& spool) {
    const std::streampos position = spool.tellp();
    if (position < std::streampos{0}) {
        throw std::runtime_error("cannot read native spool position");
    }
    return static_cast<std::uint64_t>(position);
}

void run_stream(
    std::string_view source,
    const std::vector<SpectrumRange>& spectra,
    unsigned int thread_count,
    bool fields_mode
) {
#ifdef _WIN32
    if (_setmode(_fileno(stdout), _O_BINARY) == -1) {
        throw std::runtime_error("cannot set stdout to binary mode");
    }
#endif
    const std::string_view magic = fields_mode ? kRecordMagic : kStreamMagic;
    write_bytes(magic.data(), magic.size());
    write_u64(static_cast<std::uint64_t>(spectra.size()));
    const ZlibRuntime zlib;

    for (std::size_t batch_begin = 0; batch_begin < spectra.size();) {
        const std::size_t batch_size = std::min(
            kStreamBatchSize,
            spectra.size() - batch_begin
        );
        std::vector<std::optional<DecodedSpectrum>> decoded(batch_size);
        std::atomic<std::size_t> next{0};
        std::vector<std::thread> workers;
        workers.reserve(thread_count);
        std::mutex error_mutex;
        std::string first_error;
        for (unsigned int worker = 0; worker < thread_count; ++worker) {
            workers.emplace_back([&] {
                while (true) {
                    const std::size_t offset = next.fetch_add(
                        1,
                        std::memory_order_relaxed
                    );
                    if (offset >= batch_size) {
                        break;
                    }
                    const std::size_t index = batch_begin + offset;
                    const SpectrumRange range = spectra[index];
                    try {
                        decoded[offset] = decode_spectrum(
                            source.substr(range.begin, range.end - range.begin),
                            zlib,
                            !fields_mode,
                            fields_mode
                        );
                    } catch (const std::exception& error) {
                        std::lock_guard<std::mutex> guard(error_mutex);
                        if (first_error.empty()) {
                            first_error = "spectrum[" + std::to_string(index)
                                + "]: " + error.what();
                        }
                    }
                }
            });
        }
        for (std::thread& worker : workers) {
            worker.join();
        }
        if (!first_error.empty()) {
            throw std::runtime_error(first_error);
        }
        for (const std::optional<DecodedSpectrum>& item : decoded) {
            if (!item.has_value()) {
                throw std::runtime_error("native stream batch is incomplete");
            }
            const DecodedSpectrum& spectrum = item.value();
            const std::string& metadata = fields_mode
                ? spectrum.fields_json
                : spectrum.metadata_xml;
            if (
                metadata.size()
                > static_cast<std::size_t>(std::numeric_limits<std::uint32_t>::max())
            ) {
                throw std::runtime_error("spectrum metadata exceeds uint32 limit");
            }
            write_u32(static_cast<std::uint32_t>(metadata.size()));
            write_u64(static_cast<std::uint64_t>(spectrum.mz.bytes.size()));
            write_u64(static_cast<std::uint64_t>(spectrum.intensity.bytes.size()));
            write_bytes(metadata.data(), metadata.size());
            write_bytes(spectrum.mz.bytes.data(), spectrum.mz.bytes.size());
            write_bytes(
                spectrum.intensity.bytes.data(),
                spectrum.intensity.bytes.size()
            );
        }
        std::cout.flush();
        batch_begin += batch_size;
    }
}

void run_spool_records(
    std::string_view source,
    const std::vector<SpectrumRange>& spectra,
    unsigned int thread_count,
    const std::filesystem::path& spool_path
) {
#ifdef _WIN32
    if (_setmode(_fileno(stdout), _O_BINARY) == -1) {
        throw std::runtime_error("cannot set stdout to binary mode");
    }
#endif
    std::ofstream spool(
        spool_path,
        std::ios::binary | std::ios::trunc
    );
    if (!spool) {
        throw std::runtime_error("cannot open native spool");
    }
    write_bytes(kSpoolRecordMagic.data(), kSpoolRecordMagic.size());
    write_u64(static_cast<std::uint64_t>(spectra.size()));
    const ZlibRuntime zlib;

    for (std::size_t batch_begin = 0; batch_begin < spectra.size();) {
        const std::size_t batch_size = std::min(
            kStreamBatchSize,
            spectra.size() - batch_begin
        );
        std::vector<std::optional<DecodedSpectrum>> decoded(batch_size);
        std::atomic<std::size_t> next{0};
        std::vector<std::thread> workers;
        workers.reserve(thread_count);
        std::mutex error_mutex;
        std::string first_error;
        for (unsigned int worker = 0; worker < thread_count; ++worker) {
            workers.emplace_back([&] {
                while (true) {
                    const std::size_t offset = next.fetch_add(
                        1,
                        std::memory_order_relaxed
                    );
                    if (offset >= batch_size) {
                        break;
                    }
                    const std::size_t index = batch_begin + offset;
                    const SpectrumRange range = spectra[index];
                    try {
                        decoded[offset] = decode_spectrum(
                            source.substr(range.begin, range.end - range.begin),
                            zlib,
                            false,
                            true
                        );
                    } catch (const std::exception& error) {
                        std::lock_guard<std::mutex> guard(error_mutex);
                        if (first_error.empty()) {
                            first_error = "spectrum[" + std::to_string(index)
                                + "]: " + error.what();
                        }
                    }
                }
            });
        }
        for (std::thread& worker : workers) {
            worker.join();
        }
        if (!first_error.empty()) {
            throw std::runtime_error(first_error);
        }
        for (const std::optional<DecodedSpectrum>& item : decoded) {
            if (!item.has_value()) {
                throw std::runtime_error("native spool batch is incomplete");
            }
            const DecodedSpectrum& spectrum = item.value();
            const std::string& metadata = spectrum.fields_json;
            if (
                metadata.size()
                > static_cast<std::size_t>(std::numeric_limits<std::uint32_t>::max())
            ) {
                throw std::runtime_error("spectrum metadata exceeds uint32 limit");
            }
            const std::uint64_t mz_offset = spool_offset(spool);
            write_spool(
                spool,
                spectrum.mz.bytes.data(),
                spectrum.mz.bytes.size()
            );
            const std::uint64_t intensity_offset = spool_offset(spool);
            write_spool(
                spool,
                spectrum.intensity.bytes.data(),
                spectrum.intensity.bytes.size()
            );
            write_u32(static_cast<std::uint32_t>(metadata.size()));
            write_u64(mz_offset);
            write_u64(static_cast<std::uint64_t>(spectrum.mz.bytes.size()));
            write_u64(intensity_offset);
            write_u64(static_cast<std::uint64_t>(spectrum.intensity.bytes.size()));
            write_bytes(metadata.data(), metadata.size());
        }
        spool.flush();
        if (!spool) {
            throw std::runtime_error("cannot flush native spool");
        }
        std::cout.flush();
        batch_begin += batch_size;
    }
}

int run_benchmark(
    std::string_view source,
    const std::vector<SpectrumRange>& spectra,
    unsigned int thread_count,
    std::chrono::steady_clock::time_point total_started,
    std::chrono::steady_clock::time_point scan_started,
    std::chrono::steady_clock::time_point scan_finished
) {
    const ZlibRuntime zlib;
    std::atomic<std::size_t> next{0};
    std::vector<WorkerStats> worker_stats(thread_count);
    std::vector<std::thread> workers;
    workers.reserve(thread_count);
    std::mutex error_mutex;
    std::string first_error;
    for (unsigned int worker = 0; worker < thread_count; ++worker) {
        workers.emplace_back([&, worker] {
            WorkerStats& stats = worker_stats[worker];
            while (true) {
                const std::size_t index = next.fetch_add(
                    1,
                    std::memory_order_relaxed
                );
                if (index >= spectra.size()) {
                    break;
                }
                const SpectrumRange range = spectra[index];
                try {
                    process_spectrum(
                        source.substr(range.begin, range.end - range.begin),
                        index,
                        zlib,
                        stats
                    );
                } catch (const std::exception& error) {
                    ++stats.errors;
                    std::lock_guard<std::mutex> guard(error_mutex);
                    if (first_error.empty()) {
                        first_error = "spectrum[" + std::to_string(index)
                            + "]: " + error.what();
                    }
                }
            }
        });
    }
    for (std::thread& worker : workers) {
        worker.join();
    }
    const auto total_finished = std::chrono::steady_clock::now();

    WorkerStats total{};
    for (const WorkerStats& stats : worker_stats) {
        total.spectra += stats.spectra;
        total.arrays += stats.arrays;
        total.decoded_bytes += stats.decoded_bytes;
        total.normalized_float64_bytes += stats.normalized_float64_bytes;
        total.cv_params += stats.cv_params;
        total.checksum_xor ^= stats.checksum_xor;
        total.errors += stats.errors;
    }
    const double scan_seconds =
        std::chrono::duration<double>(scan_finished - scan_started).count();
    const double total_seconds =
        std::chrono::duration<double>(total_finished - total_started).count();
    const double mib_per_second =
        static_cast<double>(source.size()) / 1048576.0 / total_seconds;
    std::cout
        << "{\n"
        << "  \"input_bytes\": " << source.size() << ",\n"
        << "  \"threads\": " << thread_count << ",\n"
        << "  \"spectrum_ranges\": " << spectra.size() << ",\n"
        << "  \"spectra_processed\": " << total.spectra << ",\n"
        << "  \"arrays_processed\": " << total.arrays << ",\n"
        << "  \"cv_params_seen\": " << total.cv_params << ",\n"
        << "  \"decoded_bytes\": " << total.decoded_bytes << ",\n"
        << "  \"normalized_float64_bytes\": "
        << total.normalized_float64_bytes << ",\n"
        << "  \"checksum_xor\": " << total.checksum_xor << ",\n"
        << "  \"errors\": " << total.errors << ",\n"
        << "  \"scan_seconds\": " << scan_seconds << ",\n"
        << "  \"total_seconds\": " << total_seconds << ",\n"
        << "  \"input_mib_per_second\": " << mib_per_second << ",\n"
        << "  \"first_error\": \"";
    for (const char character : first_error) {
        if (character == '"' || character == '\\') {
            std::cout << '\\';
        }
        std::cout << character;
    }
    std::cout << "\"\n}\n";
    return total.errors == 0 ? 0 : 1;
}

}  // namespace

int main(int argc, char** argv) {
    try {
        const bool stream_mode = argc == 4 && std::string_view(argv[1]) == "--stream";
        const bool record_mode = argc == 4 && std::string_view(argv[1]) == "--records";
        const bool spool_record_mode =
            argc == 5 && std::string_view(argv[1]) == "--spool-records";
        const bool pipe_mode = stream_mode || record_mode || spool_record_mode;
        if ((!pipe_mode && argc != 3) || (!spool_record_mode && pipe_mode && argc != 4)) {
            std::cerr
                << "usage: mzml_native [--stream|--records] "
                << "<file.mzML> <threads>\n"
                << "       mzml_native --spool-records "
                << "<file.mzML> <threads> <arrays.spool>\n";
            return 2;
        }
        if constexpr (std::endian::native != std::endian::little) {
            throw std::runtime_error("only little-endian hosts are supported");
        }
        const char* path = pipe_mode ? argv[2] : argv[1];
        const unsigned int thread_count = parse_thread_count(
            pipe_mode ? std::string_view(argv[3]) : std::string_view(argv[2])
        );
        const auto total_started = std::chrono::steady_clock::now();
        const MappedFile mapped{std::filesystem::path(path)};
        const std::string_view source = mapped.view();
        const auto scan_started = std::chrono::steady_clock::now();
        const std::vector<SpectrumRange> spectra = find_spectra(source);
        const auto scan_finished = std::chrono::steady_clock::now();
        if (spectra.empty()) {
            throw std::runtime_error("no spectra found");
        }
        if (pipe_mode) {
            if (spool_record_mode) {
                run_spool_records(
                    source,
                    spectra,
                    thread_count,
                    std::filesystem::path(argv[4])
                );
            } else {
                run_stream(source, spectra, thread_count, record_mode);
            }
            return 0;
        }
        return run_benchmark(
            source,
            spectra,
            thread_count,
            total_started,
            scan_started,
            scan_finished
        );
    } catch (const std::exception& error) {
        std::cerr << "native mzML failed: " << error.what() << '\n';
        return 1;
    }
}
