from __future__ import annotations

import hashlib
import io
import math
import struct
from array import array
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from typing import BinaryIO, Iterator, Mapping

import numpy as np
import pyarrow as pa

from .blocks import ArrayBlock
from .exceptions import ZpV2ArrayReadError, ZpV2ArrayWriteError
from .native_mzml import NativeFloat64Array
from .v2_arrays_reader import (
    V2ArrayDirectoryEntry,
    ZpV2ArrayReadLimits,
    ZpV2ArraysReader,
)
from .v2_arrays_writer import (
    V2ArraysLayout,
    ZpV2ArrayWriteLimits,
    _ARRAYS_HEADER as _V2_ARRAYS_HEADER,
    _encoded_chunks,
)


V3_ARRAYS_ENCODING = "zp-arrays-v3"
V3_ARRAYS_MAGIC = b"ZPARRV3\0"
V3_ARRAYS_SCHEMA_VERSION = 3
V3_ARRAYS_CHUNK_SIZE = 4 * 1024 * 1024
V3_ARRAY_COMPRESSION_ZSTD = "zstd"
V3_ARRAY_COMPRESSION_RAW = "raw"
V3_ARRAY_COMPRESSION_STRATEGIES = frozenset(
    {V3_ARRAY_COMPRESSION_ZSTD, V3_ARRAY_COMPRESSION_RAW}
)

_HEADER = struct.Struct("<8sHBBIIQQQ20s")
_CHUNK_HEADER = struct.Struct("<BBHII32s")
_CODEC_RAW = 0
_CODEC_ZSTD = 1


@dataclass(frozen=True, slots=True)
class V3ChunkEntry:
    index: int
    frame_offset: int
    stored_offset: int
    stored_length: int
    raw_offset: int
    raw_length: int
    codec: int
    checksum: bytes


@dataclass(frozen=True, slots=True)
class V3ArraysDirectory:
    entries: tuple[V2ArrayDirectoryEntry, ...]
    entries_by_id: Mapping[str, V2ArrayDirectoryEntry]
    directory_length: int
    payload_offset: int
    payload_length: int
    chunk_size: int
    chunks: tuple[V3ChunkEntry, ...]


@dataclass(frozen=True, slots=True)
class V3ArraysWriteMetrics:
    raw_payload_bytes: int
    stored_payload_bytes: int
    chunk_count: int
    compressed_chunk_count: int


@dataclass(frozen=True, slots=True)
class V3ArrayReadLimits:
    max_arrays_block_length: int
    max_directory_length: int
    max_entry_count: int
    max_array_value_count: int
    max_array_id_utf8_length: int
    max_payload_length: int
    max_decoded_memory: int


def _fail_read(
    code: str,
    message: str,
    location: str,
    *,
    actual: object | None = None,
    limit: int | None = None,
    array_id: str | None = None,
) -> None:
    raise ZpV2ArrayReadError(
        code,
        message,
        location,
        actual=actual,
        limit=limit,
        array_id=array_id,
    )


def _read_exact(stream: BinaryIO, length: int, code: str, location: str) -> bytes:
    payload = stream.read(length)
    if len(payload) != length:
        _fail_read(code, "data is truncated", location, actual=len(payload), limit=length)
    return payload


def _align8(value: int) -> int:
    return (value + 7) & ~7


def _synthetic_v2_directory(
    raw_directory: bytes,
    padding: bytes,
    *,
    entry_count: int,
    payload_length: int,
    limits: ZpV2ArrayReadLimits | V3ArrayReadLimits,
    require_canonical: bool,
):
    payload_offset = _V2_ARRAYS_HEADER.size + len(raw_directory) + len(padding)
    header = _V2_ARRAYS_HEADER.pack(
        b"ZPARRV2\0",
        2,
        1,
        0,
        entry_count,
        _V2_ARRAYS_HEADER.size,
        len(raw_directory),
        payload_offset,
        payload_length,
        b"\0" * 16,
    )
    synthetic = io.BytesIO(header + raw_directory + padding)
    compatible_limits = (
        limits
        if isinstance(limits, ZpV2ArrayReadLimits)
        else ZpV2ArrayReadLimits(
            max_arrays_block_length=limits.max_arrays_block_length,
            max_directory_length=limits.max_directory_length,
            max_entry_count=limits.max_entry_count,
            max_array_value_count=limits.max_array_value_count,
            max_array_id_utf8_length=limits.max_array_id_utf8_length,
            max_payload_length=limits.max_payload_length,
            max_decoded_memory=limits.max_decoded_memory,
        )
    )
    return ZpV2ArraysReader(compatible_limits).read_directory(
        synthetic,
        block_offset=0,
        block_length=payload_offset + payload_length,
        require_canonical=require_canonical,
    )


class ZpV3ArraysReader:
    def __init__(
        self,
        limits: ZpV2ArrayReadLimits | V3ArrayReadLimits,
    ) -> None:
        if not isinstance(limits, (ZpV2ArrayReadLimits, V3ArrayReadLimits)):
            raise TypeError("limits must be a supported array read limits instance")
        self.limits = limits
        self._cached_chunk_key: tuple[int, int] | None = None
        self._cached_chunk: bytes | None = None

    def read_directory(
        self,
        stream: BinaryIO,
        *,
        block_offset: int,
        block_length: int,
        require_canonical: bool = True,
    ) -> V3ArraysDirectory:
        limits = self.limits
        if block_length > limits.max_arrays_block_length:
            _fail_read(
                "ARRAYS_RESOURCE_LIMIT_EXCEEDED",
                "resource limit exceeded",
                "arrays.block_length",
                actual=block_length,
                limit=limits.max_arrays_block_length,
            )
        if block_length < _HEADER.size:
            _fail_read(
                "INVALID_ARRAY_DIRECTORY_LENGTH",
                "arrays block is shorter than its fixed header",
                "arrays.block_length",
                actual=block_length,
                limit=_HEADER.size,
            )
        stream.seek(block_offset)
        raw_header = _read_exact(
            stream,
            _HEADER.size,
            "INVALID_ARRAY_DIRECTORY_LENGTH",
            "arrays.header",
        )
        (
            magic,
            schema_version,
            endianness,
            flags,
            entry_count,
            chunk_size,
            directory_offset,
            directory_length,
            payload_length,
            reserved,
        ) = _HEADER.unpack(raw_header)
        if magic != V3_ARRAYS_MAGIC:
            _fail_read("INVALID_ARRAYS_MAGIC", "invalid arrays magic", "arrays.header.magic")
        if schema_version != V3_ARRAYS_SCHEMA_VERSION:
            _fail_read(
                "UNSUPPORTED_ARRAYS_VERSION",
                "unsupported arrays schema version",
                "arrays.header.schema_version",
                actual=schema_version,
            )
        if endianness != 1:
            _fail_read(
                "UNSUPPORTED_ARRAYS_ENDIANNESS",
                "unsupported arrays endianness",
                "arrays.header.endianness",
                actual=endianness,
            )
        if flags != 0 or reserved != b"\0" * 20:
            _fail_read(
                "UNSUPPORTED_ARRAYS_FLAGS",
                "arrays flags and reserved bytes must be zero",
                "arrays.header",
            )
        if directory_offset != _HEADER.size:
            _fail_read(
                "INVALID_ARRAY_DIRECTORY_OFFSET",
                "internal directory must follow the fixed header",
                "arrays.header.directory_offset",
                actual=directory_offset,
                limit=_HEADER.size,
            )
        if entry_count > limits.max_entry_count:
            _fail_read(
                "ARRAY_COUNT_TOO_LARGE",
                "resource limit exceeded",
                "arrays.entry_count",
                actual=entry_count,
                limit=limits.max_entry_count,
            )
        if directory_length > limits.max_directory_length:
            _fail_read(
                "ARRAY_DIRECTORY_TOO_LARGE",
                "resource limit exceeded",
                "arrays.directory_length",
                actual=directory_length,
                limit=limits.max_directory_length,
            )
        if payload_length > limits.max_payload_length:
            _fail_read(
                "ARRAY_PAYLOAD_TOO_LARGE",
                "resource limit exceeded",
                "arrays.payload_length",
                actual=payload_length,
                limit=limits.max_payload_length,
            )
        if (
            chunk_size < 8
            or chunk_size % 8
            or chunk_size > limits.max_decoded_memory
        ):
            _fail_read(
                "INVALID_ARRAY_CHUNK_SIZE",
                "chunk size must be aligned and fit the decode budget",
                "arrays.header.chunk_size",
                actual=chunk_size,
                limit=limits.max_decoded_memory,
            )
        directory_end = directory_offset + directory_length
        payload_offset = _align8(directory_end)
        if payload_offset > block_length:
            _fail_read(
                "INVALID_ARRAY_DIRECTORY_LENGTH",
                "internal directory is outside the arrays block",
                "arrays.directory",
            )
        stream.seek(block_offset + directory_offset)
        raw_directory = _read_exact(
            stream,
            directory_length,
            "INVALID_ARRAY_DIRECTORY_LENGTH",
            "arrays.directory",
        )
        padding = _read_exact(
            stream,
            payload_offset - directory_end,
            "INVALID_ARRAY_PAYLOAD_OFFSET",
            "arrays.padding",
        )
        if any(padding):
            _fail_read("NONZERO_ARRAY_PADDING", "arrays padding must be zero", "arrays.padding")
        parsed = _synthetic_v2_directory(
            raw_directory,
            padding,
            entry_count=entry_count,
            payload_length=payload_length,
            limits=limits,
            require_canonical=require_canonical,
        )

        chunk_count = math.ceil(payload_length / chunk_size) if payload_length else 0
        chunks: list[V3ChunkEntry] = []
        cursor = payload_offset
        raw_offset = 0
        for index in range(chunk_count):
            if cursor + _CHUNK_HEADER.size > block_length:
                _fail_read(
                    "INVALID_ARRAY_CHUNK_HEADER",
                    "chunk header is outside the arrays block",
                    f"arrays.chunks[{index}]",
                )
            stream.seek(block_offset + cursor)
            raw_chunk_header = _read_exact(
                stream,
                _CHUNK_HEADER.size,
                "INVALID_ARRAY_CHUNK_HEADER",
                f"arrays.chunks[{index}]",
            )
            codec, chunk_flags, chunk_reserved, raw_length, stored_length, checksum = (
                _CHUNK_HEADER.unpack(raw_chunk_header)
            )
            expected_raw_length = min(chunk_size, payload_length - raw_offset)
            if codec not in {_CODEC_RAW, _CODEC_ZSTD}:
                _fail_read(
                    "UNSUPPORTED_ARRAY_CHUNK_CODEC",
                    "unsupported array chunk codec",
                    f"arrays.chunks[{index}].codec",
                    actual=codec,
                )
            if chunk_flags != 0 or chunk_reserved != 0:
                _fail_read(
                    "UNSUPPORTED_ARRAY_CHUNK_FLAGS",
                    "chunk flags and reserved bytes must be zero",
                    f"arrays.chunks[{index}]",
                )
            if raw_length != expected_raw_length or stored_length <= 0:
                _fail_read(
                    "INVALID_ARRAY_CHUNK_LENGTH",
                    "chunk length is inconsistent with the logical payload",
                    f"arrays.chunks[{index}]",
                    actual=(raw_length, stored_length),
                    limit=expected_raw_length,
                )
            if codec == _CODEC_RAW and stored_length != raw_length:
                _fail_read(
                    "INVALID_ARRAY_CHUNK_LENGTH",
                    "raw chunk length must equal its logical length",
                    f"arrays.chunks[{index}]",
                )
            stored_offset = cursor + _CHUNK_HEADER.size
            cursor = stored_offset + stored_length
            if cursor > block_length:
                _fail_read(
                    "INVALID_ARRAY_CHUNK_LENGTH",
                    "chunk payload is outside the arrays block",
                    f"arrays.chunks[{index}]",
                    actual=cursor,
                    limit=block_length,
                )
            chunks.append(
                V3ChunkEntry(
                    index=index,
                    frame_offset=stored_offset - _CHUNK_HEADER.size,
                    stored_offset=stored_offset,
                    stored_length=stored_length,
                    raw_offset=raw_offset,
                    raw_length=raw_length,
                    codec=codec,
                    checksum=checksum,
                )
            )
            raw_offset += raw_length
        if cursor != block_length:
            _fail_read(
                "ARRAYS_TRAILING_DATA",
                "arrays block contains trailing data",
                "arrays.block_length",
                actual=block_length,
                limit=cursor,
            )
        return V3ArraysDirectory(
            entries=parsed.entries,
            entries_by_id=parsed.entries_by_id,
            directory_length=directory_length,
            payload_offset=payload_offset,
            payload_length=payload_length,
            chunk_size=chunk_size,
            chunks=tuple(chunks),
        )

    def read_chunk(
        self,
        stream: BinaryIO,
        *,
        block_offset: int,
        directory: V3ArraysDirectory,
        chunk_index: int,
    ) -> bytes:
        key = (id(directory), chunk_index)
        if key == self._cached_chunk_key and self._cached_chunk is not None:
            return self._cached_chunk
        chunk = directory.chunks[chunk_index]
        stream.seek(block_offset + chunk.stored_offset)
        stored = _read_exact(
            stream,
            chunk.stored_length,
            "ARRAY_PAYLOAD_OUT_OF_BOUNDS",
            f"arrays.chunks[{chunk_index}]",
        )
        try:
            if chunk.codec == _CODEC_RAW:
                raw = stored
            else:
                raw = pa.Codec("zstd").decompress(
                    stored,
                    decompressed_size=chunk.raw_length,
                ).to_pybytes()
        except (pa.ArrowException, ValueError) as exc:
            _fail_read(
                "INVALID_ARRAY_CHUNK_PAYLOAD",
                "array chunk cannot be decompressed",
                f"arrays.chunks[{chunk_index}]",
                actual=str(exc),
            )
        if len(raw) != chunk.raw_length:
            _fail_read(
                "INVALID_ARRAY_CHUNK_LENGTH",
                "decoded chunk length is invalid",
                f"arrays.chunks[{chunk_index}]",
                actual=len(raw),
                limit=chunk.raw_length,
            )
        actual = hashlib.sha256(raw).digest()
        if actual != chunk.checksum:
            _fail_read(
                "ARRAY_CHUNK_CHECKSUM_MISMATCH",
                "decoded chunk checksum does not match its frame",
                f"arrays.chunks[{chunk_index}]",
                actual=actual.hex(),
            )
        self._cached_chunk_key = key
        self._cached_chunk = raw
        return raw

    def read_array(
        self,
        stream: BinaryIO,
        *,
        block_offset: int,
        directory: V3ArraysDirectory,
        array_id: str,
    ) -> ArrayBlock:
        entry = directory.entries_by_id.get(array_id)
        if entry is None:
            _fail_read(
                "ARRAY_NOT_FOUND",
                "array_id is not present in the arrays directory",
                "arrays.directory",
                array_id=array_id,
            )
        if entry.byte_length == 0:
            raw = b""
        else:
            first = entry.data_offset // directory.chunk_size
            last = (entry.data_offset + entry.byte_length - 1) // directory.chunk_size
            pieces: list[bytes] = []
            end = entry.data_offset + entry.byte_length
            for chunk_index in range(first, last + 1):
                chunk = directory.chunks[chunk_index]
                decoded = self.read_chunk(
                    stream,
                    block_offset=block_offset,
                    directory=directory,
                    chunk_index=chunk_index,
                )
                begin_in_chunk = max(entry.data_offset, chunk.raw_offset) - chunk.raw_offset
                end_in_chunk = min(end, chunk.raw_offset + chunk.raw_length) - chunk.raw_offset
                pieces.append(decoded[begin_in_chunk:end_in_chunk])
            raw = b"".join(pieces)
        actual = hashlib.sha256(raw).hexdigest()
        if actual != entry.checksum:
            _fail_read(
                "ARRAY_CHECKSUM_MISMATCH",
                "array payload checksum does not match its entry",
                f"arrays[{array_id!r}].checksum",
                actual=actual,
                array_id=array_id,
            )
        values = array("d")
        values.frombytes(raw)
        if struct.pack("=H", 1) != struct.pack("<H", 1):
            values.byteswap()
        return ArrayBlock(
            array_id=entry.array_id,
            array_type=entry.array_type,
            dtype=entry.dtype,
            values=values.tolist(),
        )


def _iter_raw_chunks(layout: V2ArraysLayout, chunk_size: int) -> Iterator[bytes]:
    pending = bytearray()
    for array_block, entry in zip(layout.arrays, layout.entries):
        digest = (
            None
            if isinstance(array_block.values, NativeFloat64Array)
            else hashlib.sha256()
        )
        written = 0
        for view in _encoded_chunks(array_block, validate_types=False):
            if digest is not None:
                digest.update(view)
            written += len(view)
            cursor = 0
            while cursor < len(view):
                take = min(chunk_size - len(pending), len(view) - cursor)
                pending.extend(view[cursor : cursor + take])
                cursor += take
                if len(pending) == chunk_size:
                    yield bytes(pending)
                    pending.clear()
        checksum_changed = (
            digest is not None and digest.hexdigest() != entry.checksum
        )
        if written != entry.byte_length or checksum_changed:
            raise ZpV2ArrayWriteError(
                "ARRAY_VALUES_CHANGED_DURING_WRITE",
                "array values changed after layout preparation",
                f"arrays[{array_block.array_id!r}].values",
                actual=written,
            )
    if pending:
        yield bytes(pending)


def _raw_chunk(raw: bytes) -> tuple[int, bytes, bytes]:
    return _CODEC_RAW, raw, hashlib.sha256(raw).digest()


def _compress_chunk(raw: bytes) -> tuple[int, bytes, bytes]:
    compressed = pa.Codec("zstd", compression_level=1).compress(raw).to_pybytes()
    if len(compressed) >= len(raw):
        return _raw_chunk(raw)
    return _CODEC_ZSTD, compressed, hashlib.sha256(raw).digest()


def _write_exact(stream: BinaryIO, payload: bytes, digest: object) -> None:
    written = stream.write(payload)
    if written != len(payload):
        raise OSError(f"short write: expected {len(payload)} bytes, wrote {written}")
    digest.update(payload)


def write_v3_arrays_block(
    stream: BinaryIO,
    layout: V2ArraysLayout,
    *,
    worker_threads: int,
    chunk_size: int = V3_ARRAYS_CHUNK_SIZE,
    compression_strategy: str = V3_ARRAY_COMPRESSION_ZSTD,
) -> tuple[int, str, V3ArraysWriteMetrics]:
    if type(worker_threads) is not int or not 1 <= worker_threads <= 32:
        raise ZpV2ArrayWriteError(
            "INVALID_ARRAY_WORKER_THREADS",
            "worker_threads must be an integer from 1 to 32",
            "arrays.worker_threads",
            actual=worker_threads,
        )
    if chunk_size < 8 or chunk_size % 8:
        raise ZpV2ArrayWriteError(
            "INVALID_ARRAY_CHUNK_SIZE",
            "chunk_size must be a positive 8-byte multiple",
            "arrays.chunk_size",
            actual=chunk_size,
        )
    if compression_strategy not in V3_ARRAY_COMPRESSION_STRATEGIES:
        raise ZpV2ArrayWriteError(
            "INVALID_ARRAY_COMPRESSION_STRATEGY",
            "compression_strategy must be 'zstd' or 'raw'",
            "arrays.compression_strategy",
            actual=compression_strategy,
        )
    directory_end = _HEADER.size + len(layout.directory_bytes)
    payload_offset = _align8(directory_end)
    header = _HEADER.pack(
        V3_ARRAYS_MAGIC,
        V3_ARRAYS_SCHEMA_VERSION,
        1,
        0,
        len(layout.entries),
        chunk_size,
        _HEADER.size,
        len(layout.directory_bytes),
        layout.payload_length,
        b"\0" * 20,
    )
    digest = hashlib.sha256()
    _write_exact(stream, header, digest)
    _write_exact(stream, layout.directory_bytes, digest)
    padding = b"\0" * (payload_offset - directory_end)
    _write_exact(stream, padding, digest)

    queue: deque[Future[tuple[int, bytes, bytes]]] = deque()
    stored_payload_bytes = 0
    chunk_count = 0
    compressed_chunk_count = 0

    def write_chunk_payload(
        result: tuple[int, bytes, bytes],
        raw_length: int,
    ) -> None:
        nonlocal stored_payload_bytes, chunk_count, compressed_chunk_count
        codec, stored, checksum = result
        frame = _CHUNK_HEADER.pack(
            codec,
            0,
            0,
            raw_length,
            len(stored),
            checksum,
        )
        _write_exact(stream, frame, digest)
        _write_exact(stream, stored, digest)
        stored_payload_bytes += len(stored)
        chunk_count += 1
        compressed_chunk_count += int(codec == _CODEC_ZSTD)

    raw_lengths: deque[int] = deque()
    if compression_strategy == V3_ARRAY_COMPRESSION_RAW:
        for raw in _iter_raw_chunks(layout, chunk_size):
            write_chunk_payload(_raw_chunk(raw), len(raw))
    else:
        with ThreadPoolExecutor(max_workers=worker_threads) as executor:
            for raw in _iter_raw_chunks(layout, chunk_size):
                queue.append(executor.submit(_compress_chunk, raw))
                raw_lengths.append(len(raw))
                if len(queue) >= worker_threads * 2:
                    write_chunk_payload(
                        queue.popleft().result(),
                        raw_lengths.popleft(),
                    )
            while queue:
                write_chunk_payload(queue.popleft().result(), raw_lengths.popleft())

    block_length = (
        payload_offset
        + chunk_count * _CHUNK_HEADER.size
        + stored_payload_bytes
    )
    return (
        block_length,
        digest.hexdigest(),
        V3ArraysWriteMetrics(
            raw_payload_bytes=layout.payload_length,
            stored_payload_bytes=stored_payload_bytes,
            chunk_count=chunk_count,
            compressed_chunk_count=compressed_chunk_count,
        ),
    )
