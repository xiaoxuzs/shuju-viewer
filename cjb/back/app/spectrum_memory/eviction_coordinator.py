"""Global 6GiB (configurable) pool: whole-dataset mzML bundles + MRU/LRU eviction."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any

from app.spectrum_memory.config import max_capacity_bytes
from app.spectrum_memory.contracts import MzmlBundleSpec
from app.spectrum_memory.lru_mru_queue import DatasetMruQueue
from app.spectrum_memory.size_accounting import pre_load_reserve_bytes
from app.spectrum_memory.types import CapacityError, NotResidentError, Residency


@dataclass
class _LoadingRecord:
    event: threading.Event
    reserve_bytes: int
    error: BaseException | None = None


class EvictionCoordinator:
    """Single-process coordinator with dataset-level single-flight loading."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._bundles: dict[int, Any] = {}
        self._loading: dict[int, _LoadingRecord] = {}
        self._queue = DatasetMruQueue()
        self._current_total = 0
        self._reserved_total = 0
        self._max = max_capacity_bytes()

    def residency_of(self, dataset_id: int) -> Residency:
        with self._lock:
            if dataset_id in self._bundles:
                return Residency.READY
            if dataset_id in self._loading:
                return Residency.LOADING
            return Residency.ABSENT

    def _evict_until_fits(self, need_bytes: int, *, exclude_reserved: int = 0) -> None:
        reserved = max(0, self._reserved_total - exclude_reserved)
        while self._current_total + reserved + need_bytes > self._max:
            victim = self._queue.pop_lru()
            if victim is None:
                return
            b = self._bundles.pop(victim, None)
            if b is not None:
                self._current_total -= b.accounted_bytes

    def ensure_dataset_resident(self, spec: MzmlBundleSpec) -> None:
        if not spec.runs:
            return

        dataset_id = spec.dataset_id
        with self._lock:
            if dataset_id in self._bundles:
                self._queue.touch(dataset_id)
                return
            record = self._loading.get(dataset_id)

        reserve = 0
        if record is None:
            reserve = pre_load_reserve_bytes(spec)
            with self._lock:
                if dataset_id in self._bundles:
                    self._queue.touch(dataset_id)
                    return
                record = self._loading.get(dataset_id)
                if record is None:
                    self._evict_until_fits(reserve)
                    if self._current_total + self._reserved_total + reserve > self._max:
                        raise CapacityError(
                            f"cannot reserve ~{reserve} bytes for dataset {dataset_id} "
                            f"(current={self._current_total}, reserved={self._reserved_total}, max={self._max})"
                        )
                    record = _LoadingRecord(event=threading.Event(), reserve_bytes=reserve)
                    self._loading[dataset_id] = record
                    self._reserved_total += reserve
                    is_loader = True
                else:
                    is_loader = False
        else:
            is_loader = False

        if not is_loader:
            record.event.wait()
            if record.error is not None:
                raise record.error
            with self._lock:
                if dataset_id not in self._bundles:
                    raise NotResidentError(f"dataset {dataset_id} finished loading without a resident bundle")
                self._queue.touch(dataset_id)
            return

        try:
            from app.spectrum_memory.mzml_dataset_bundle import DatasetMzmlBundle

            bundle = DatasetMzmlBundle.load(spec)
            actual = bundle.accounted_bytes

            with self._lock:
                if actual > self._max:
                    raise CapacityError(
                        f"dataset {dataset_id} accounted size {actual} bytes exceeds global max {self._max}"
                    )

                self._evict_until_fits(actual, exclude_reserved=record.reserve_bytes)
                other_reserved = self._reserved_total - record.reserve_bytes
                if self._current_total + other_reserved + actual > self._max:
                    raise CapacityError(
                        f"cannot fit dataset {dataset_id} (~{actual} B) after eviction "
                        f"(current={self._current_total}, reserved={other_reserved}, max={self._max})"
                    )
                self._bundles[dataset_id] = bundle
                self._current_total += actual
                self._reserved_total -= record.reserve_bytes
                self._loading.pop(dataset_id, None)
                self._queue.touch(dataset_id)
                record.event.set()
        except BaseException as exc:
            with self._lock:
                if self._loading.get(dataset_id) is record:
                    self._reserved_total -= record.reserve_bytes
                    record.error = exc
                    self._loading.pop(dataset_id, None)
                    record.event.set()
            raise

    def get_mzml_spectrum(self, dataset_id: int, run_id: int, scan_number: int) -> dict[str, Any] | None:
        with self._lock:
            b = self._bundles.get(dataset_id)
            if b is None:
                raise NotResidentError(
                    f"dataset {dataset_id} is not resident; open the dataset first"
                )
            self._queue.touch(dataset_id)
            scans = b.run_to_spectra.get(run_id)
            if scans is None:
                return None
            return scans.get(scan_number)

    def get_mzml_run_spectra(self, dataset_id: int, run_id: int) -> dict[int, dict[str, Any]] | None:
        """Return the resident scan map for one run.

        The returned mapping is owned by the in-memory bundle and must be
        treated as read-only by callers. This intentionally exposes the
        smallest surface needed by LC-MS map builders without coupling them to
        the coordinator internals.
        """
        with self._lock:
            b = self._bundles.get(dataset_id)
            if b is None:
                raise NotResidentError(
                    f"dataset {dataset_id} is not resident; open the dataset first"
                )
            self._queue.touch(dataset_id)
            return b.run_to_spectra.get(run_id)

    def release_dataset(self, dataset_id: int) -> None:
        with self._lock:
            b = self._bundles.pop(dataset_id, None)
            self._queue.remove(dataset_id)
            if b is not None:
                self._current_total -= b.accounted_bytes


_singleton: EvictionCoordinator | None = None
_singleton_lock = threading.Lock()


def get_coordinator() -> EvictionCoordinator:
    global _singleton
    with _singleton_lock:
        if _singleton is None:
            _singleton = EvictionCoordinator()
        return _singleton
