# Proteo-Viewer 架构索引

> 本仓的"读模型 / 写模型 / 任务流 / 命名规则"地图。修改任何跨层逻辑前先读这里。
> 当物理表布局或 ZIP 流程变化时，请同步更新本文档与 `docs/universal_schema.sql`。

---

## 1. 总览：单一 universal schema，无 ORM 路径

```
┌──────────────────────────────────────────────────────────────────────────┐
│                          PostgreSQL (universal)                          │
│  datasets  runs  proteins  peptides  proteoforms                         │
│  identification_matches  protein_relation_mapping  import_jobs           │
└──────────────────────────────────────────────────────────────────────────┘
        ▲                       ▲                          ▲
        │ raw SQL (text)        │ raw SQL (text)           │ raw SQL (text)
        │                       │                          │
┌──────────────┐       ┌────────────────────────┐    ┌──────────────────┐
│ FastAPI 读模型 │       │ ZIP 后台任务（写）      │    │ Universal CLI（写）│
│ app/api/v1/* │       │ app/services/import_   │    │ python -m app... │
│              │       │  jobs.py + ingest/...  │    │                  │
└──────────────┘       └────────────────────────┘    └──────────────────┘
       ▲
       │ axios + react-query
       │
┌──────────────┐
│ React 前端    │
│ front/src/*  │
└──────────────┘
```

* 库结构唯一真值：[`docs/universal_schema.sql`](./universal_schema.sql)。所有读、写、CLI 都按这套 7+1 张表。
* 历史 ORM/Alembic 路径已删除（`back/app/models/`、`back/alembic/`、`back/app/ingest/importer.py`、`back/app/ingest/cli.py` 均已不在仓库内）。
* `import_jobs` 表是新增的：保存 ZIP 后台任务的状态/阶段/进度，启动时 `ensure_jobs_table()` 自动 `CREATE TABLE IF NOT EXISTS`。

---

## 2. 读模型：浏览器看到的所有数据

| 用途 | 文件 |
| --- | --- |
| 路由聚合 | `back/app/api/v1/__init__.py` |
| 数据集列表 / 详情 / 删除 | `back/app/api/v1/datasets.py` |
| 蛋白 / 形态 / PrSM | `back/app/api/v1/proteins.py`, `proteoforms.py`, `prsms.py` |
| MS1/MS2 谱 | `back/app/api/v1/spectra.py` |
| 旧形状 ↔ universal 兼容 | `back/app/api/v1/universal_compat.py` |
| Pydantic 响应 | `back/app/schemas/` |
| DB 会话 / 配置 | `back/app/core/db.py`, `back/app/api/deps.py`, `back/app/core/config.py` |

读路径都用 `Session + sqlalchemy.text` 直接查 universal schema，不再走 ORM。

### 2.1 cutoff 是「虚拟的」

universal 库**没有** `cutoffs` 表。前端期望两张 cutoff 卡（`prsm` / `proteoform`），靠：

* `identification_matches.extra_metadata->>'source_cutoff'` 字符串归类；
* `app/api/v1/universal_compat.py` 里集中定义的常量：
  - `cutoff_kinds()` — 顺序元组（`("prsm", "proteoform")`），驱动 UI 顺序。
  - `cutoff_id(kind)` — 合成稳定整数 ID（1=prsm, 2=proteoform，前端 React key / URL 用，**勿改**）。
  - `cutoff_label(kind)` — 中英展示文案。
* `datasets.py::_cutoffs_payload` 用 `GROUP BY source_cutoff` 配合 `protein_relation_mapping` 算每个 cutoff 的真实 protein/proteoform/PrSM 计数。
* `proteins.py / proteoforms.py` 在列表/详情上用 `EXISTS` 子查询按 cutoff 过滤，确保 cutoff 切换会真的换数据。

---

## 3. 写模型：导入与删除

### 3.1 通过 HTTP（前端"Import from ZIP"按钮）

```
POST /api/v1/imports                       (back/app/api/v1/imports.py)
   ⇣ multipart: file/slug/name/description, 流式落盘到 tempfile
   ⇣ create_job() → INSERT INTO import_jobs (status='queued')
   ⇣ start_zip_import_background()         (back/app/services/import_jobs.py)
        │
        ├─ phase=extract:
        │     mkdir <DATA_ROOT>/<slug>.incoming
        │     unzip → 校验 zip-slip → 报告每文件进度
        │
        ├─ phase=init:
        │     ingest_universal_toppic(...) (back/app/ingest/universal_toppic_adapter.py)
        │       INSERT datasets ; lazy _RunRegistry
        │
        ├─ phase=proteins, matches:
        │     循环 cutoff_kinds()，每 cutoff 走 _import_proteins_and_forms +
        │     _import_prsm_matches；progress_callback 把 ProgressEvent 投到
        │     _PHASE_RANGES → import_jobs 行。
        │
        ├─ phase=finalize:
        │     UPDATE datasets/runs SET status='READY'
        │     UPDATE datasets SET description=:desc        (HTTP 入口附带的)
        │
        └─ atomic swap:
              rmtree DATA_ROOT/<slug>  (旧版本)
              rename .incoming → DATA_ROOT/<slug>
              失败：保留 .incoming，标记 job failed
GET /api/v1/imports/{job_id}              ← 前端轮询
   ⇢ 顺便 GC 7 天前的 success/failed 行（JOB_TTL_DAYS）
```

进度阶段映射全部在 `app/services/import_jobs.py::_PHASE_RANGES` / `_PHASE_LABELS`：

| phase | 全局百分比 | 中文标签 |
| --- | --- | --- |
| `queued` | 0 – 1 | 排队中… |
| `extract` | 1 – 18 | 正在解压压缩包，耗时较长… |
| `init` | 18 – 22 | 正在创建数据集记录… |
| `proteins` | 22 – 30 | 正在导入蛋白与形态… |
| `matches` | 30 – 95 | 正在导入鉴定结果（PrSM 详情）… |
| `finalize` | 95 – 99.5 | 正在收尾索引… |
| `success` | 100 | 导入完成 |

### 3.2 通过命令行（远程 / 大数据集时绕过 HTTP 上传）

```
cd back
uv run python -m app.ingest.universal_toppic_adapter ingest \
    --root  ../shuju/<unzipped-folder> \
    --slug  <unique_slug>  --name "<display name>" \
    --mode  full  --replace
```

CLI 与 HTTP 后台任务调用**同一个** `ingest_universal_toppic`，所以行为完全一致。`--database-url` 默认 `settings.database_url`。

### 3.3 多 run（按 spectrum_file_name 自动分桶）

* `_RunRegistry`（`universal_toppic_adapter.py`）懒加载：
  - `mode=fast` 没有逐 PrSM 的 `spectrum_file_name`，只创建一条默认 run，保持原有行为；
  - `mode=full` 每读一个 `prsm*.js`，从 `prsm.ms.ms_header.spectrum_file_name` 取文件名，缺则用默认 run；首次出现则插入新的 `runs` 行；之后命中缓存。
* `identification_matches.run_id` 据此精确指向各自的 mzML/raw。
* `UniversalImportStats.run_id` 仍指默认 run（`stats.run_id` 用于日志摘要）。

### 3.4 删除数据集

```
DELETE /api/v1/datasets/{slug}            (back/app/api/v1/datasets.py)
   ⇣ has_active_job_for_slug(slug)?   有 → 409 拒绝
   ⇣ DELETE FROM datasets WHERE slug = :slug
        cascade → runs / proteins / proteoforms / identification_matches /
                  protein_relation_mapping
   ⇣ 解析磁盘目录：
        优先 datasets.source_root；要求落在 DATA_ROOT 子树
        缺则 fallback DATA_ROOT/_slug_dir_name(slug)
   ⇣ rmtree(folder)（不在 DATA_ROOT 下时拒绝、返回 400）
   ⇢ DatasetDeletedOut { deleted_db, deleted_disk, folder, folder_existed }
```

前端在 `DatasetsPage.tsx` 卡片右上角加了垃圾桶按钮，点开 destructive 风格确认对话框，Confirm 后调用 `deleteDataset(slug)` 并 `invalidateQueries(['datasets'])`。`onClick` 里 `preventDefault + stopPropagation`，避免点按钮误触发外层 `<Link>` 跳转。

---

## 4. 命名规则速查

| 对象 | 规则 | 代码位置 |
| --- | --- | --- |
| 解压子目录名 | slug 经 `_slug_dir_name`：保留 `[A-Za-z0-9._-]`，其余替换为 `_`，去首尾 `._-`，空则 `dataset` | `back/app/services/import_jobs.py::_slug_dir_name`、`back/app/services/spectrum_cache.py` |
| `.incoming` 临时目录 | `<slug_dir>.incoming` 紧邻最终目录，仅在 DB 写完才 rename 替换 | `back/app/services/import_jobs.py::run_zip_import_job` |
| 上传临时 zip | `viewer-import-*<原后缀>` | `back/app/api/v1/imports.py` |
| 数据集主键 | `datasets.dataset_id` 自增；`datasets.slug` 唯一 | `docs/universal_schema.sql` |
| job 主键 | UUID v4 | `back/app/services/import_jobs.py::create_job` |
| run 主键 | `runs.run_id` 自增；同一 dataset 下多条 run 用 `file_name` 区分 | adapter 里的 `_RunRegistry._insert_run` |
| 谱图查找 | 先 `datasets.source_root` 绝对路径；缺则 `DATA_ROOT/_slug_dir_name(slug)` | `back/app/services/spectrum_cache.py` |
| cutoff ID | 1=prsm，2=proteoform（前端常量） | `back/app/api/v1/universal_compat.py` |

---

## 5. 任务/运维要点

### 5.1 启动与日志

`start-back.bat` / `start-front.bat` 都把 stdout+stderr `Tee-Object` 写到 `<repo>/logs/<role>-YYYYMMDD-HHMMSS.log`，控制台仍能实时查看。日志目录已加进 `.gitignore`。

### 5.2 进程重启

* `import_jobs` 持久化在表里，`uvicorn --reload` 触发的重启不会丢任务记录；前端轮询 ID 仍能拿到最新行（即使后台线程因 reload 中断，job 会停留在 `running` 状态，DB 里能看到，下一次手动重导即可）。
* 7 天内的成功/失败任务会被惰性 GC（`get_job` 时执行）。

### 5.3 删除时的安全护栏

* `delete_dataset` 仅在 `DATA_ROOT` 子树内 `rmtree`；其它路径会抛 `ValueError` → 400。
* 任意 `queued/running` 的 import job 指向同一 slug 时拒绝删除（409）。

### 5.4 可移植性

* 谱图路径 fallback 让"把 `shuju/` 拷到另一台机器、改 `.env` 里的 `DATA_ROOT`"成为可行；不需要重写 `datasets.source_root`。
* 如果硬要批量改，可以直接 `UPDATE datasets SET source_root = REPLACE(source_root, '<old>', '<new>')`。

### 5.5 备份

最小化备份：`docs/universal_schema.sql` + `pg_dump <db>` + `shuju/` 目录。`import_jobs` 历史可省略备份（重启即重建表结构，旧任务 7 天内自然 GC）。

---

## 6. 已知未做的二期项

* 多 run 的前端展示：`identification_matches.run_id` 已能区分多文件，但前端目前不暴露 run 选择器；如果后续要做多 mzML 数据集，就需要在 dataset 详情页加上 "run filter" 控件。
* 进度条目前按"文件个数"线性估计，对极端不均匀的数据集（少量超大 prsm.js）误差会累加；如有需要，可把权重改成按字节数。
