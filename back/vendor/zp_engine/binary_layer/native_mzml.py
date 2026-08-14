from __future__ import annotations

import json
import os
import re
import struct
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Iterator

import numpy as np

from .exceptions import MzmlParseError


NATIVE_RECORD_MAGIC = b"ZPNMZ2\r\n"
NATIVE_SPOOL_RECORD_MAGIC = b"ZPNMZ3\r\n"
_COUNT = struct.Struct("<Q")
_RECORD_HEADER = struct.Struct("<IQQ")
_SPOOL_RECORD_HEADER = struct.Struct("<IQQQQ")
_MAX_SPECTRA = 4_000_000
_MAX_RECORD_JSON = 16 * 1024 * 1024
_MAX_ARRAY_BYTES = 8 * 1024**3
_MAX_TOTAL_ARRAY_BYTES = 128 * 1024**3
_SHA256 = re.compile(r"[0-9a-f]{64}")


class NativeFloat64Array(np.ndarray):
    """Read-only native array carrying the C++-verified raw SHA-256."""

    native_sha256: str

    def __new__(
        cls,
        raw: bytes | np.ndarray,
        *,
        checksum: str,
    ) -> "NativeFloat64Array":
        if _SHA256.fullmatch(checksum) is None:
            raise MzmlParseError(
                "NATIVE_PROTOCOL_ERROR",
                "native array SHA-256 is invalid",
                "native_stream.array_checksum",
            )
        if isinstance(raw, bytes):
            result = np.frombuffer(raw, dtype="<f8").view(cls)
        else:
            values = np.asarray(raw)
            if (
                values.dtype != np.dtype("<f8")
                or values.ndim != 1
                or not values.flags.c_contiguous
            ):
                raise MzmlParseError(
                    "NATIVE_PROTOCOL_ERROR",
                    "native array storage must be one-dimensional contiguous float64",
                    "native_stream.array_storage",
                )
            result = values.view(cls)
            result._native_backing = raw
        result.native_sha256 = checksum
        result.flags.writeable = False
        return result

    def __array_finalize__(self, source: object) -> None:
        if source is not None:
            self.native_sha256 = getattr(source, "native_sha256", "")


@dataclass(frozen=True, slots=True)
class NativeMzmlSpectrumRecord:
    fields: dict[str, object]
    mz_values: np.ndarray
    intensity_values: np.ndarray


def fixed_native_mzml_executable() -> Path | None:
    name = "mzml_pipeline.exe" if _is_windows() else "mzml_pipeline"
    candidate = Path(__file__).resolve().parent.parent / "native" / "bin" / name
    return candidate if candidate.is_file() else None


def read_native_mzml_records(
    source: Path,
    *,
    worker_threads: int,
    executable: Path,
) -> tuple[NativeMzmlSpectrumRecord, ...]:
    return _read_native_mzml_pipe_records(
        source,
        worker_threads=worker_threads,
        executable=executable,
    )


def _read_native_mzml_pipe_records(
    source: Path,
    *,
    worker_threads: int,
    executable: Path,
) -> tuple[NativeMzmlSpectrumRecord, ...]:
    if type(worker_threads) is not int or not 1 <= worker_threads <= 32:
        raise ValueError("worker_threads must be an integer from 1 to 32")
    source = source.resolve(strict=True)
    executable = executable.resolve(strict=True)
    process = subprocess.Popen(
        [
            str(executable),
            "--records",
            str(source),
            str(worker_threads),
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=8 * 1024 * 1024,
    )
    assert process.stdout is not None
    assert process.stderr is not None
    records: list[NativeMzmlSpectrumRecord] = []
    total_array_bytes = 0
    try:
        magic = _read_exact(process.stdout, len(NATIVE_RECORD_MAGIC), "stream.magic")
        if magic != NATIVE_RECORD_MAGIC:
            raise MzmlParseError(
                "NATIVE_PROTOCOL_ERROR",
                "native mzML stream magic does not match",
                "native_stream.magic",
            )
        spectrum_count = _COUNT.unpack(
            _read_exact(process.stdout, _COUNT.size, "stream.spectrum_count")
        )[0]
        if spectrum_count == 0 or spectrum_count > _MAX_SPECTRA:
            raise MzmlParseError(
                "NATIVE_RESOURCE_LIMIT",
                "native mzML spectrum count exceeds the supported range",
                "native_stream.spectrum_count",
            )
        for position in range(spectrum_count):
            json_length, mz_length, intensity_length = _RECORD_HEADER.unpack(
                _read_exact(
                    process.stdout,
                    _RECORD_HEADER.size,
                    f"stream.records[{position}].header",
                )
            )
            _validate_record_lengths(
                json_length,
                mz_length,
                intensity_length,
                position=position,
            )
            total_array_bytes += mz_length + intensity_length
            if total_array_bytes > _MAX_TOTAL_ARRAY_BYTES:
                raise MzmlParseError(
                    "NATIVE_RESOURCE_LIMIT",
                    "native mzML array payload exceeds the supported limit",
                    "native_stream.array_bytes",
                )
            raw_json = _read_exact(
                process.stdout,
                json_length,
                f"stream.records[{position}].json",
            )
            try:
                fields = json.loads(raw_json)
            except (UnicodeError, ValueError) as exc:
                raise MzmlParseError(
                    "NATIVE_PROTOCOL_ERROR",
                    f"native mzML metadata JSON is invalid: {exc}",
                    f"native_stream.records[{position}].json",
                ) from exc
            if not isinstance(fields, dict) or not all(
                isinstance(key, str) for key in fields
            ):
                raise MzmlParseError(
                    "NATIVE_PROTOCOL_ERROR",
                    "native mzML metadata must be a JSON object",
                    f"native_stream.records[{position}].json",
                )
            mz_raw = _read_exact(
                process.stdout,
                mz_length,
                f"stream.records[{position}].mz",
            )
            intensity_raw = _read_exact(
                process.stdout,
                intensity_length,
                f"stream.records[{position}].intensity",
            )
            mz_checksum = fields.get("mz_sha256")
            intensity_checksum = fields.get("intensity_sha256")
            if not isinstance(mz_checksum, str) or not isinstance(
                intensity_checksum,
                str,
            ):
                raise MzmlParseError(
                    "NATIVE_PROTOCOL_ERROR",
                    "native array SHA-256 fields are missing",
                    f"native_stream.records[{position}].json",
                )
            records.append(
                NativeMzmlSpectrumRecord(
                    fields=fields,
                    mz_values=NativeFloat64Array(
                        mz_raw,
                        checksum=mz_checksum,
                    ),
                    intensity_values=NativeFloat64Array(
                        intensity_raw,
                        checksum=intensity_checksum,
                    ),
                )
            )
        trailing = process.stdout.read(1)
        return_code = process.wait()
        stderr = process.stderr.read(8192)
        if return_code != 0:
            raise MzmlParseError(
                "NATIVE_MZML_FAILED",
                _safe_native_error(stderr),
                "native_mzml",
            )
        if trailing:
            raise MzmlParseError(
                "NATIVE_PROTOCOL_ERROR",
                "native mzML stream contains trailing bytes",
                "native_stream",
            )
        return tuple(records)
    except Exception:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        raise
    finally:
        process.stdout.close()
        process.stderr.close()


def _read_native_mzml_spool_records(
    source: Path,
    *,
    worker_threads: int,
    executable: Path,
) -> tuple[NativeMzmlSpectrumRecord, ...]:
    if type(worker_threads) is not int or not 1 <= worker_threads <= 32:
        raise ValueError("worker_threads must be an integer from 1 to 32")
    source = source.resolve(strict=True)
    executable = executable.resolve(strict=True)
    descriptor, raw_spool_path = tempfile.mkstemp(
        prefix="zp-native-mzml-",
        suffix=".bin",
    )
    os.close(descriptor)
    spool_path = Path(raw_spool_path)
    try:
        records = _read_native_mzml_spool_stream(
            source,
            worker_threads=worker_threads,
            executable=executable,
            spool_path=spool_path,
        )
        try:
            spool_path.unlink()
        except OSError:
            pass
        return records
    except Exception:
        try:
            spool_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def _read_native_mzml_spool_stream(
    source: Path,
    *,
    worker_threads: int,
    executable: Path,
    spool_path: Path,
) -> tuple[NativeMzmlSpectrumRecord, ...]:
    process = subprocess.Popen(
        [
            str(executable),
            "--spool-records",
            str(source),
            str(worker_threads),
            str(spool_path),
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=8 * 1024 * 1024,
    )
    assert process.stdout is not None
    assert process.stderr is not None
    raw_records: list[tuple[dict[str, object], int, int, int, int]] = []
    total_array_bytes = 0
    try:
        magic = _read_exact(
            process.stdout,
            len(NATIVE_SPOOL_RECORD_MAGIC),
            "stream.magic",
        )
        if magic != NATIVE_SPOOL_RECORD_MAGIC:
            raise MzmlParseError(
                "NATIVE_PROTOCOL_ERROR",
                "native mzML spool stream magic does not match",
                "native_stream.magic",
            )
        spectrum_count = _COUNT.unpack(
            _read_exact(process.stdout, _COUNT.size, "stream.spectrum_count")
        )[0]
        if spectrum_count == 0 or spectrum_count > _MAX_SPECTRA:
            raise MzmlParseError(
                "NATIVE_RESOURCE_LIMIT",
                "native mzML spectrum count exceeds the supported range",
                "native_stream.spectrum_count",
            )
        for position in range(spectrum_count):
            (
                json_length,
                mz_offset,
                mz_length,
                intensity_offset,
                intensity_length,
            ) = _SPOOL_RECORD_HEADER.unpack(
                _read_exact(
                    process.stdout,
                    _SPOOL_RECORD_HEADER.size,
                    f"stream.records[{position}].header",
                )
            )
            _validate_record_lengths(
                json_length,
                mz_length,
                intensity_length,
                position=position,
            )
            if mz_offset % 8 or intensity_offset % 8:
                raise MzmlParseError(
                    "NATIVE_PROTOCOL_ERROR",
                    "native mzML spool offsets must be 8-byte aligned",
                    f"native_stream.records[{position}]",
                )
            total_array_bytes += mz_length + intensity_length
            if total_array_bytes > _MAX_TOTAL_ARRAY_BYTES:
                raise MzmlParseError(
                    "NATIVE_RESOURCE_LIMIT",
                    "native mzML array payload exceeds the supported limit",
                    "native_stream.array_bytes",
                )
            raw_json = _read_exact(
                process.stdout,
                json_length,
                f"stream.records[{position}].json",
            )
            try:
                fields = json.loads(raw_json)
            except (UnicodeError, ValueError) as exc:
                raise MzmlParseError(
                    "NATIVE_PROTOCOL_ERROR",
                    f"native mzML metadata JSON is invalid: {exc}",
                    f"native_stream.records[{position}].json",
                ) from exc
            if not isinstance(fields, dict) or not all(
                isinstance(key, str) for key in fields
            ):
                raise MzmlParseError(
                    "NATIVE_PROTOCOL_ERROR",
                    "native mzML metadata must be a JSON object",
                    f"native_stream.records[{position}].json",
                )
            raw_records.append(
                (
                    fields,
                    mz_offset,
                    mz_length,
                    intensity_offset,
                    intensity_length,
                )
            )
        trailing = process.stdout.read(1)
        return_code = process.wait()
        stderr = process.stderr.read(8192)
        if return_code != 0:
            raise MzmlParseError(
                "NATIVE_MZML_FAILED",
                _safe_native_error(stderr),
                "native_mzml",
            )
        if trailing:
            raise MzmlParseError(
                "NATIVE_PROTOCOL_ERROR",
                "native mzML stream contains trailing bytes",
                "native_stream",
            )
        spool_size = spool_path.stat().st_size
        if spool_size < total_array_bytes:
            raise MzmlParseError(
                "NATIVE_PROTOCOL_TRUNCATED",
                "native mzML spool is shorter than declared array payloads",
                "native_spool",
            )
        backing = np.memmap(spool_path, dtype="<f8", mode="r")
        records: list[NativeMzmlSpectrumRecord] = []
        for position, (
            fields,
            mz_offset,
            mz_length,
            intensity_offset,
            intensity_length,
        ) in enumerate(raw_records):
            _validate_spool_bounds(
                mz_offset,
                mz_length,
                spool_size,
                position=position,
                name="mz",
            )
            _validate_spool_bounds(
                intensity_offset,
                intensity_length,
                spool_size,
                position=position,
                name="intensity",
            )
            mz_checksum = fields.get("mz_sha256")
            intensity_checksum = fields.get("intensity_sha256")
            if not isinstance(mz_checksum, str) or not isinstance(
                intensity_checksum,
                str,
            ):
                raise MzmlParseError(
                    "NATIVE_PROTOCOL_ERROR",
                    "native array SHA-256 fields are missing",
                    f"native_stream.records[{position}].json",
                )
            records.append(
                NativeMzmlSpectrumRecord(
                    fields=fields,
                    mz_values=NativeFloat64Array(
                        backing[
                            mz_offset // 8 : (mz_offset + mz_length) // 8
                        ],
                        checksum=mz_checksum,
                    ),
                    intensity_values=NativeFloat64Array(
                        backing[
                            intensity_offset // 8 : (
                                intensity_offset + intensity_length
                            )
                            // 8
                        ],
                        checksum=intensity_checksum,
                    ),
                )
            )
        return tuple(records)
    except Exception:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        raise
    finally:
        process.stdout.close()
        process.stderr.close()


def _validate_spool_bounds(
    offset: int,
    length: int,
    spool_size: int,
    *,
    position: int,
    name: str,
) -> None:
    if offset < 0 or length <= 0 or offset + length > spool_size:
        raise MzmlParseError(
            "NATIVE_PROTOCOL_ERROR",
            "native mzML spool array range is outside the spool file",
            f"native_stream.records[{position}].{name}",
        )


def iter_native_mzml_records(
    source: Path,
    *,
    worker_threads: int,
    executable: Path,
) -> Iterator[NativeMzmlSpectrumRecord]:
    yield from read_native_mzml_records(
        source,
        worker_threads=worker_threads,
        executable=executable,
    )


def _validate_record_lengths(
    json_length: int,
    mz_length: int,
    intensity_length: int,
    *,
    position: int,
) -> None:
    if json_length == 0 or json_length > _MAX_RECORD_JSON:
        raise MzmlParseError(
            "NATIVE_RESOURCE_LIMIT",
            "native mzML metadata record exceeds the supported limit",
            f"native_stream.records[{position}].json_length",
        )
    for name, length in (("mz", mz_length), ("intensity", intensity_length)):
        if length == 0 or length > _MAX_ARRAY_BYTES or length % 8:
            raise MzmlParseError(
                "NATIVE_RESOURCE_LIMIT",
                "native mzML array length is invalid or exceeds the supported limit",
                f"native_stream.records[{position}].{name}_length",
            )
    if mz_length != intensity_length:
        raise MzmlParseError(
            "NATIVE_PROTOCOL_ERROR",
            "native mzML core arrays have different byte lengths",
            f"native_stream.records[{position}]",
        )


def _read_exact(stream: BinaryIO, length: int, location: str) -> bytes:
    chunks = bytearray(length)
    view = memoryview(chunks)
    offset = 0
    while offset < length:
        read = stream.readinto(view[offset:])
        if not read:
            raise MzmlParseError(
                "NATIVE_PROTOCOL_TRUNCATED",
                "native mzML stream ended before the declared record length",
                location,
            )
        offset += read
    return bytes(chunks)


def _safe_native_error(stderr: bytes) -> str:
    message = stderr.decode("utf-8", errors="replace").strip()
    if not message:
        return "native mzML process failed"
    return f"native mzML process failed: {message[:1000]}"


def _is_windows() -> bool:
    import os

    return os.name == "nt"
