"""Global 6GiB (configurable) pool: whole-dataset mzML bundles + MRU/LRU eviction."""

from __future__ import annotations

import threading
from typing import Any

from app.spectrum_memory.config import max_capacity_bytes
from app.spectrum_memory.contracts import MzmlBundleSpec
from app.spectrum_memory.lru_mru_queue import DatasetMruQueue
from app.spectrum_memory.size_accounting import pre_load_reserve_bytes
from app.spectrum_memory.types import CapacityError, NotResidentError, Residency


class EvictionCoordinator:
    """Single-process coordinator (one RLock for local deployment)."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._bundles: dict[int, Any] = {}
        self._queue = DatasetMruQueue()
        self._current_total = 0
        self._max = max_capacity_bytes()

    def residency_of(self, dataset_id: int) -> Residency:
        with self._lock:
            if dataset_id in self._bundles:
                return Residency.READY
            return Residency.ABSENT

    def _evict_until_fits(self, need_bytes: int) -> None:
        while self._current_total + need_bytes > self._max:
            victim = self._queue.pop_lru()
            if victim is None:
                return
            b = self._bundles.pop(victim, None)
            if b is not None:
                self._current_total -= b.accounted_bytes

    def ensure_dataset_resident(self, spec: MzmlBundleSpec) -> None:
        if not spec.runs:
            return
        with self._lock:
            if spec.dataset_id in self._bundles:
                self._queue.touch(spec.dataset_id)
                return

            reserve = pre_load_reserve_bytes(spec)
            self._evict_until_fits(reserve)
            if self._current_total + reserve > self._max:
                raise CapacityError(
                    f"cannot reserve ~{reserve} bytes for dataset {spec.dataset_id} "
                    f"(current={self._current_total}, max={self._max})"
                )

            from app.spectrum_memory.mzml_dataset_bundle import DatasetMzmlBundle

            bundle = DatasetMzmlBundle.load(spec)
            actual = bundle.accounted_bytes

            if actual > self._max:
                raise CapacityError(
                    f"dataset {spec.dataset_id} accounted size {actual} bytes exceeds global max {self._max}"
                )

            self._evict_until_fits(actual)
            if self._current_total + actual > self._max:
                raise CapacityError(
                    f"cannot fit dataset {spec.dataset_id} (~{actual} B) after eviction "
                    f"(current={self._current_total}, max={self._max})"
                )
            self._bundles[spec.dataset_id] = bundle
            self._current_total += actual
            self._queue.touch(spec.dataset_id)

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
