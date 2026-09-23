# `back/tests/test_spectrum_memory.py` 逐行解释

> 来源文件：`back/tests/test_spectrum_memory.py`
> 模块职责：单元测试 MRU 队列、预留字节、EvictionCoordinator 加载/驱逐/查询/释放。

## MRU 队列（L15-L30）

- LRU 在 OrderedDict 左端；touch 后移到 MRU（右端）。

## 预留字节（L33-L48）

- 更大 mzML 文件 → `pre_load_reserve_bytes` 更大；下限 ≥1 MiB。

## EvictionCoordinator（L51-L231）

- 使用 `_FakeBundle` + patch `DatasetMzmlBundle.load` 避免真实解析 mzML。
- `test_eviction_coordinator_evicts_lru_when_over_budget`：预算 500B，两 dataset 各 300B → 先加载的 101 被驱逐。
- `test_eviction_coordinator_hit_is_idempotent_and_keeps_resident`：重复 ensure 不 double accounting。
- `test_eviction_coordinator_get_spectrum_raises_when_absent`：`NotResidentError`。
- hit 测试：单 scan 与整 run scan map 返回正确 payload。
- `release_dataset` 清零 accounting。
- 单 dataset 超过 `_max` 抛 `CapacityError`。

## 与相邻模块的耦合

- 依赖 `lxml`（pyteomics）时在 integration 路径 `importorskip`；Coordinator 测试用 mock 绕过。
