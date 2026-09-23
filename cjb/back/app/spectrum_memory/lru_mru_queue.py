"""MRU/LRU ordering for whole-dataset bundles (OrderedDict: LRU at left, MRU at right)."""

from __future__ import annotations

from collections import OrderedDict


class DatasetMruQueue:
    """Tracks touch order; ``pop_lru`` removes the least-recently-used dataset_id."""

    def __init__(self) -> None:
        self._order: OrderedDict[int, None] = OrderedDict()

    def touch(self, dataset_id: int) -> None:
        if dataset_id in self._order:
            self._order.move_to_end(dataset_id)
        else:
            self._order[dataset_id] = None

    def remove(self, dataset_id: int) -> None:
        self._order.pop(dataset_id, None)

    def pop_lru(self) -> int | None:
        if not self._order:
            return None
        dataset_id, _ = self._order.popitem(last=False)
        return dataset_id

    def __contains__(self, dataset_id: int) -> bool:
        return dataset_id in self._order
