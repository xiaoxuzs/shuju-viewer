from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from app.services import mzml_scan_reader


class _FakeReader:
    def __init__(self, native_ids: list[str], spectra: dict[str, dict[str, Any]]) -> None:
        self.default_index = {native_id: offset for offset, native_id in enumerate(native_ids)}
        self._spectra = spectra
        self.get_calls: list[tuple[str, str | None]] = []
        self.close_calls = 0

    def __enter__(self) -> "_FakeReader":
        return self

    def __exit__(self, *_args: Any) -> None:
        return None

    def __iter__(self):
        raise AssertionError("indexed reader must not iterate spectra")

    def get_by_id(self, native_id: str, element_type: str | None = None) -> dict[str, Any]:
        self.get_calls.append((native_id, element_type))
        return self._spectra[native_id]

    def close(self) -> None:
        self.close_calls += 1


def _spectrum(native_id: str, *, ms_level: int = 2) -> dict[str, Any]:
    return {
        "id": native_id,
        "ms level": ms_level,
        "m/z array": np.array([100.0, 200.0]),
        "intensity array": np.array([10.0, 20.0]),
        "scanList": {"scan": [{"scan start time": 12.5}]},
    }


def _write_indexed_stub(path: Path, suffix: bytes = b"") -> None:
    path.write_bytes(b"<indexListOffset>1024</indexListOffset>" + suffix)


@pytest.fixture(autouse=True)
def clear_index_cache() -> None:
    mzml_scan_reader._INDEX_CACHE.clear()


def test_reader_uses_get_by_id_without_iterating(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    path = tmp_path / "run.mzML"
    _write_indexed_stub(path)
    native_id = "controllerType=0 controllerNumber=1 scan=123"
    reader = _FakeReader([native_id], {native_id: _spectrum(native_id)})
    monkeypatch.setattr(mzml_scan_reader, "_StrictPreIndexedMzML", lambda _path: reader)

    result = mzml_scan_reader.read_indexed_spectrum(path, 123)

    assert reader.get_calls == [(native_id, "spectrum")]
    assert result["scan"] == 123
    assert result["ms_level"] == 2
    assert result["mz"] == [100.0, 200.0]
    assert result["intensity"] == [10.0, 20.0]


def test_reader_supports_simple_index_native_id(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    path = tmp_path / "run.mzML"
    _write_indexed_stub(path)
    native_id = "index=100"
    reader = _FakeReader([native_id], {native_id: _spectrum(native_id, ms_level=1)})
    monkeypatch.setattr(mzml_scan_reader, "_StrictPreIndexedMzML", lambda _path: reader)

    result = mzml_scan_reader.read_indexed_spectrum(path, 100)

    assert result["native_id"] == native_id
    assert result["ms_level"] == 1


def test_reader_returns_not_found_without_get_by_id(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    path = tmp_path / "run.mzML"
    _write_indexed_stub(path)
    native_id = "scan=123"
    reader = _FakeReader([native_id], {native_id: _spectrum(native_id)})
    monkeypatch.setattr(mzml_scan_reader, "_StrictPreIndexedMzML", lambda _path: reader)

    with pytest.raises(mzml_scan_reader.SpectrumNotFoundError):
        mzml_scan_reader.read_indexed_spectrum(path, 999)

    assert reader.get_calls == []


def test_reader_rejects_unparseable_native_ids(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    path = tmp_path / "run.mzML"
    _write_indexed_stub(path)
    native_id = "sample=alpha spectrum=123"
    reader = _FakeReader([native_id], {native_id: _spectrum(native_id)})
    monkeypatch.setattr(mzml_scan_reader, "_StrictPreIndexedMzML", lambda _path: reader)

    with pytest.raises(mzml_scan_reader.UnsupportedNativeIdError, match="no parseable"):
        mzml_scan_reader.read_indexed_spectrum(path, 123)

    assert reader.get_calls == []


def test_reader_rejects_unindexed_mzml_without_fallback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    path = tmp_path / "run.mzML"
    path.write_bytes(b"unindexed")
    monkeypatch.setattr(
        mzml_scan_reader,
        "_StrictPreIndexedMzML",
        lambda _path: pytest.fail("unindexed mzML must be rejected before opening a reader"),
    )

    with pytest.raises(mzml_scan_reader.UnsupportedMzmlError, match="indexListOffset"):
        mzml_scan_reader.read_indexed_spectrum(path, 1)


def test_reader_rejects_gzip_without_opening_reader(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    path = tmp_path / "run.mzML.gz"
    path.write_bytes(b"gzip")
    monkeypatch.setattr(
        mzml_scan_reader,
        "_StrictPreIndexedMzML",
        lambda _path: pytest.fail("gzip must be rejected before opening a reader"),
    )

    with pytest.raises(mzml_scan_reader.UnsupportedMzmlError, match="gzip-compressed"):
        mzml_scan_reader.read_indexed_spectrum(path, 1)


def test_index_cache_invalidates_when_file_changes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    path = tmp_path / "run.mzML"
    _write_indexed_stub(path, b"first")
    first_id = "scan=1"
    second_id = "scan=2"
    readers = [
        _FakeReader([first_id], {first_id: _spectrum(first_id)}),
        _FakeReader([second_id], {second_id: _spectrum(second_id)}),
    ]
    opened = 0

    def open_reader(_path: str) -> _FakeReader:
        nonlocal opened
        reader = readers[opened]
        opened += 1
        return reader

    monkeypatch.setattr(mzml_scan_reader, "_StrictPreIndexedMzML", open_reader)

    assert mzml_scan_reader.read_indexed_spectrum(path, 1)["scan"] == 1
    _write_indexed_stub(path, b"second-version")
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
    assert mzml_scan_reader.read_indexed_spectrum(path, 2)["scan"] == 2

    assert opened == 2
    assert len(mzml_scan_reader._INDEX_CACHE) == 1


def test_reader_handle_is_reused_for_same_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    path = tmp_path / "run.mzML"
    _write_indexed_stub(path)
    first_id = "scan=1"
    second_id = "scan=2"
    reader = _FakeReader(
        [first_id, second_id],
        {
            first_id: _spectrum(first_id),
            second_id: _spectrum(second_id),
        },
    )
    opened = 0

    def open_reader(_path: str) -> _FakeReader:
        nonlocal opened
        opened += 1
        return reader

    monkeypatch.setattr(mzml_scan_reader, "_StrictPreIndexedMzML", open_reader)

    with mzml_scan_reader.indexed_reader_scope():
        assert mzml_scan_reader.read_indexed_spectrum(path, 1)["scan"] == 1
        assert mzml_scan_reader.read_indexed_spectrum(path, 2)["scan"] == 2

    assert opened == 1
    assert reader.get_calls == [
        (first_id, "spectrum"),
        (second_id, "spectrum"),
    ]
    assert reader.close_calls == 1


class _NoRowResult:
    def mappings(self) -> "_NoRowResult":
        return self

    def one_or_none(self) -> None:
        return None


class _NoRowSession:
    def execute(self, *_args: Any, **_kwargs: Any) -> _NoRowResult:
        return _NoRowResult()


def test_get_spectrum_by_scan_rejects_run_outside_dataset() -> None:
    with pytest.raises(mzml_scan_reader.RunNotFoundError, match="run not found"):
        mzml_scan_reader.get_spectrum_by_scan(
            _NoRowSession(),  # type: ignore[arg-type]
            dataset_id=39,
            run_id=999,
            scan_number=1,
        )
