## `docs/architecture.md` 逐行解释

> 这是一份“架构索引/地图”，用于告诉维护者：系统分哪几层、读写路径分别在哪里、cutoff 如何在 universal schema 中表达、ZIP 导入任务如何流转、以及一些关键命名规则与运维要点。它不是源码，但它直接决定你在改动导入/表结构/API 时应该同步更新哪里。

---

### L1-L5：标题与阅读前提

- **L1**：文档标题：Proteo-Viewer 架构索引。
- **L3-L4**：这是“读模型/写模型/任务流/命名规则”的地图；提示修改跨层逻辑前先读这里。
- **L4**：强调当物理表布局或 ZIP 流程变化时，要同步更新本文档与 `docs/universal_schema.sql`（数据库 schema 是最终真值）。

---

### L8-L36：总览：单一 universal schema，无 ORM 路径

#### L10-L31：架构图（ASCII）

- **L11-L15**：PostgreSQL universal schema 的表集合：
  - datasets / runs / proteins / peptides / proteoforms / identification_matches / protein_relation_mapping / import_jobs
- **L16-L18**：三条“raw SQL (text)”的箭头说明：
  - FastAPI 读模型（API）用 raw SQL
  - ZIP 后台任务（导入写模型）用 raw SQL
  - Universal CLI（写模型）也用 raw SQL
- **L24-L30**：React 前端通过 axios + react-query 调用 FastAPI。

#### L33-L36：关键结论

- **L33**：库结构唯一真值是 `docs/universal_schema.sql`，所有读写都按这套表。
- **L34**：历史 ORM/Alembic 路径已删除（列出曾经存在的目录/文件，作为“不要再找 ORM”提示）。
- **L35**：`import_jobs` 是新增表：用于 ZIP 后台任务状态持久化；后端启动时会 `ensure_jobs_table()` 做 `CREATE TABLE IF NOT EXISTS`。

---

## 2. 读模型（L39-L64）

### L41-L50：读模型文件索引表

- 列出各用途对应的后端文件：
  - 路由聚合：`api/v1/__init__.py`
  - datasets：`api/v1/datasets.py`
  - proteins/proteoforms/prsms：对应各 API 文件
  - spectra：`api/v1/spectra.py`
  - universal 兼容：`api/v1/universal_compat.py`
  - Pydantic schemas：`schemas/`
  - DB 会话/配置：`core/db.py` 等

### L51：读路径的技术选型

- 明确：读路径用 `Session + sqlalchemy.text` 直接查 universal schema，不走 ORM。

### L53-L64：cutoff 是“虚拟的”

- **L55-L63**：解释 cutoff 的实现方式：
  - universal schema 没有 `cutoffs` 表；
  - cutoff 字符串来自 `identification_matches.extra_metadata->>'source_cutoff'`；
  - 前端需要 id/label/顺序，因此在 `universal_compat.py` 里定义：
    - kinds 顺序元组
    - 稳定 synthetic id（1/2，不能改）
    - label 文案
  - datasets API 通过 GROUP BY + relation mapping 计算每个 cutoff 的 protein/proteoform/prsm 计数；
  - proteins/proteoforms API 用 EXISTS 子查询按 cutoff 过滤，保证切换 cutoff 会“真的换数据”。

---

## 3. 写模型：导入与删除（L67-L147）

### 3.1 HTTP 导入（ZIP 后台任务）流程图（L69-L113）

这段是“Import from ZIP”按钮背后真实执行顺序：

- **L72**：`POST /api/v1/imports`：上传 zip（`api/v1/imports.py`）。
- **L73-L76**：文件流式落盘到临时文件，写入 `import_jobs` 记录，然后启动后台任务（`services/import_jobs.py`）。
- **L77-L97**：后台任务 phases：
  - extract：解压到 `<DATA_ROOT>/<slug>.incoming`，做 zip-slip 校验并报告进度
  - init/proteins/matches：调用 `ingest_universal_toppic`（adapter），并把 adapter progress 映射到 `import_jobs` 的 progress/stage 字段
  - finalize：设置 datasets/runs 为 READY，并写入 description
  - atomic swap：用 rename 实现 `.incoming` → 正式目录替换；失败时保留 `.incoming` 并标记 job failed
- **L98-L100**：前端轮询 `GET /imports/{job_id}`，同时后端会顺便 GC 老任务（7 天 TTL）。
- **L102-L113**：列出 phase → 百分比区间 → 中文标签（来自 `import_jobs.py` 的 `_PHASE_RANGES/_PHASE_LABELS`）。

### 3.2 CLI 导入（L114-L125）

- 展示命令行方式调用 adapter ingest；
- 强调 CLI 与 HTTP 后台任务调用同一个 `ingest_universal_toppic`，因此行为一致。

### 3.3 多 run（L126-L133）

- 解释 `_RunRegistry`（adapter 内部）如何在 full 模式下按 `spectrum_file_name` 自动分桶创建多个 runs；
- fast 模式因为没有逐 PrSM 细节（缺 spectrum_file_name），只创建一个默认 run；
- `identification_matches.run_id` 因此可以精确指向不同 mzML/raw。

### 3.4 删除数据集（L134-L147）

- `DELETE /datasets/{slug}`：
  - 若 slug 有 active import job → 409 拒绝（避免竞争）
  - 删除 datasets 行（cascade 删除其它表）
  - 解析磁盘目录并限制必须在 DATA_ROOT 子树内，才允许 rmtree
  - 返回 `DatasetDeletedOut`

同时解释前端 `DatasetsPage.tsx` 的 delete 按钮如何实现（preventDefault/stopPropagation + invalidate datasets query）。

---

## 4. 命名规则速查（L153-L165）

- 列表形式总结了几个关键命名与约束：
  - slug_dir_name 的规则与位置（import_jobs.py / spectrum_cache.py）
  - `.incoming` 临时目录命名与替换策略
  - 临时 zip 文件命名
  - datasets/job/run 的主键语义
  - 谱图查找路径 fallback
  - cutoff ID 的稳定常量来源

---

## 5. 任务/运维要点（L168-L192）

- **启动与日志**：start 脚本把日志写到 `logs/` 并 gitignore。
- **进程重启**：import_jobs 持久化；reload 可能中断后台线程但任务记录仍在。
- **删除安全护栏**：只能删除 DATA_ROOT 内目录；有 active job 时拒绝删除。
- **可移植性**：谱图路径 fallback 使得迁移 DATA_ROOT 更容易；也可通过 UPDATE 批量改 source_root。
- **备份**：最小备份集合（schema + pg_dump + shuju）。

---

## 6. 已知未做的二期项（L195-L199）

- 多 run 前端选择器尚未做；
- 进度条当前按“文件个数”估计，对极端不均匀数据会有误差，可改按字节权重。

---

## 7. 补充：双谱图源（TopFD JS / mzML memory）

> 本节对应 `docs/architecture.md` 未单独成节的实现细节；完整流程图见 `explain/docs/mzml-spectra-import-flow.md.md`。

- **capabilities.spectra_source**：`topfd_js` 与 `mzml_memory` 二选一（导入时写入或合并；`TopPIC_prsm_js` 旧行可由 `datasets` API 推断为 `mzml_memory` 供前端路由）。
- **mzML 路径**：导入时在 `mzml_mapping` 中做 **strict 1:1**（`spectrum_file_name` ↔ 磁盘文件），结果写入 **`runs.run_metadata.mzml_file_path`**；`main.py` 启动时 `ensure_runs_metadata_schema()` 保证列存在。
- **懒加载**：不在导入时读 mzML；首次 `GET .../runs/{run_id}/spectra/{scan}` 时 `MzmlStore.load_run` 全量读入并建 scan 索引。
- **动态 API**：`mzml_spectra.py`；若 `run_metadata` 缺路径，会按 **`datasets.source_root`** 重算映射、`UPDATE` 后 **`session.commit()`**（`get_db` 不自动提交）。
- **前端**：`PrsmDetailPage` 按 `spectra_source` 选择 TopFD 静态谱图 API 或 mzML 动态 API；`parseRawSpectrum` 同时支持 TopFD `peaks[]` 与 mzML **平行 `mz`/`intensity` 数组**。

