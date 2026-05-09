# `back/app/services/import_jobs.py` 逐行解释（导入任务主流程）

> 来源文件：`back/app/services/import_jobs.py`  
> 说明：该文件是后端“上传 ZIP → 解压 → 识别数据形态 → 写 universal schema → 原子替换目录 → 写 capability/mzML 映射 → 任务进度轮询”的核心实现。

---

## L1-L20（模块定位）

- 解释该模块为何存在：导入任务必须可被前端轮询、跨 `uvicorn --reload` 保持状态，因此把任务状态持久化到 DB 的 `import_jobs` 表。
- 说明写入路径走 `ingest_universal_toppic`（universal schema 的写模型）。
- 说明进度拆分为多阶段：extract/proteins/matches/finalize 等，并映射到 0..100。

## L22-L55（导入与依赖）

- 标准库：`re/json/shutil/threading/uuid/zipfile` 等，用于路径、并发、解压、文件操作。
- SQLAlchemy：`text` + `IntegrityError`（处理 unique 冲突回滚）。
- 项目内依赖：
  - `cutoff_kinds`：决定 per-cutoff 进度条切片顺序
  - `settings`：拿 `resolved_data_root`、`database_url`
  - `_db_engine`：直接用 engine.begin() 执行 SQL（导入/任务更新都不通过 ORM）
  - `ingest_universal_toppic` / `ingest_universal_prsm_js`：两条导入 adapter
  - `mzml_mapping`：导入期 strict 校验（只做文件映射，不读 mzML）
  - `prsm_files.has_prsm_files`：用于判断 `ingest_root/data/` 下是否存在可识别的 `prsm*` 明细文件（目前支持 `.js/.json/.txt`），从而识别“prsm bundle”导入形态

## L57-L143（启动时补 schema）

### L61：`JOB_TTL_DAYS = 7`

- 导入任务表的 GC TTL：成功/失败任务超过 7 天会被删除（在读取 job 时惰性 GC）。

### L63-L87：`_BOOTSTRAP_SQL`

- `CREATE TABLE IF NOT EXISTS import_jobs (...)`：任务表结构
- 建索引：
  - `(status, updated_at DESC)`：方便按状态/时间查
  - `(dataset_slug)`：方便按 slug 查是否有活动任务

### L90-L97：`_DATASET_ZIP_FINGERPRINT_SQL`

- 为 `datasets` 补 `source_zip_sha256` 列 + 部分唯一索引：
  - 使“同 ZIP 内容”的导入具备全局唯一性（避免重复导入/并发冲突）

### L99-L104：`_RUNS_METADATA_SQL`

- 为 `runs` 补 `run_metadata JSONB` 列：
  - mzML memory 模式需要把 `mzml_file_path` 写到该 JSONB

### L107-L143：`ensure_*` 三个函数

- `ensure_jobs_table()`：执行 `_BOOTSTRAP_SQL`
- `ensure_dataset_zip_fingerprint_schema()`：执行 `_DATASET_ZIP_FINGERPRINT_SQL`
- `ensure_runs_metadata_schema()`：执行 `_RUNS_METADATA_SQL`
- 都是 best-effort：失败只记录日志，不阻塞启动（避免 DB 暂时不可用导致进程直接起不来）

## L145-L175：重复 ZIP 检测

- `ExistingDatasetFingerprintMatch`：返回 slug + dataset_name
- `find_dataset_with_zip_sha256(...)`：
  - 查 `datasets.source_zip_sha256` 是否已存在
  - 异常 best-effort：失败返回 None（意味着不会阻止导入，但可能在后面 unique index 冲突时回滚）

## L178-L191：`_gc_old_jobs`

- 在读取 job 时做惰性 GC：删除 `status in ('success','failed')` 且超过 TTL 的记录。

## L194-L225：进度条映射常量

- `_CUTOFF_ORDER`：由 `cutoff_kinds()` 决定（prsm 在前，proteoform 在后）
- `_PHASE_RANGES`：各阶段占全局进度条的百分比窗口（matches 占最大窗口）
- `_PHASE_LABELS`：阶段码 → 中文标签（前端直接显示）

## L233-L259：解压后识别 ingest 根目录

- `_slug_dir_name(slug)`：slug → 安全目录名（与 `spectrum_cache` 一致）
- `_has_dataset_layout(path)`：判断目录是否像一个数据集根（包含 topfd/toppic*/data 任一）
- `_find_ingest_root(extract_dir)`：
  - 如果 extract_dir 本身就是数据集根 → 直接返回
  - 否则如果只有一个子目录是数据集根 → unwrap
  - 多个候选 → 失败（ZIP 只能包含一个数据集）

## L261-L297：zip-slip 防护与条目收集

- `_validate_zip_paths(zf, dest)`：
  - 拒绝绝对路径与 `..`
  - 并确保 resolve 后路径仍在 `dest` 子树内（防 zip slip）
- `_collect_zip_entries`：
  - 在安全校验后，返回：
    - all infos（包含 dir entries）
    - 需要预建的目录列表
    - 需要抽取的 file infos 列表

## L299-L449：并行解压（带进度回调）

- `ZIP_EXTRACT_WORKERS = 12`：线程池大小（固定上限）
- `_get_thread_zip_handle`：每线程维护一个 ZipFile 句柄，避开 zipfile 的锁/共享状态
- `_extract_chunk`：单线程批量 read→write（不 mkdir，提升吞吐）
- `_maybe_unwrap_single_root_folder`：如果 zip 解压出来只有一个 wrapper 目录，就把内容上提一层（兼容常见“打包外层目录”）
- `_extract_zip_with_progress`：
  - 先建目录树（把目录条目算作 done）
  - 再把 file_infos 按 chunk_size=500 分块，提交线程池并行 extract
  - 每完成一个 chunk，用 on_progress(current,total) 回报进度

## L457-L638：任务行的创建/读取/更新 + 进度换算

- `ImportJob` dataclass：DB 行的内存镜像
- `_row_to_job`：把 DB mappings 转成 ImportJob
- `create_job(...)`：
  - 插入 import_jobs，status=queued，并返回 snapshot
- `get_job(job_id)`：
  - 校验 UUID 合法性，不合法直接 None
  - begin() 中执行 `_gc_old_jobs`
  - 查询并返回 snapshot
- `has_active_job_for_slug(slug)`：
  - 检查某 slug 是否存在 queued/running 任务（用于删除护栏）
- `_update_job`：
  - 只允许更新白名单列（避免意外写错）
  - best-effort：更新失败不阻塞导入主流程
- `_phase_percent`：
  - 把某阶段（phase, cutoff, current, total）映射到全局百分比
  - 如果带 cutoff：按 cutoff 顺序在该阶段窗口里切片（prsm 占前半，proteoform 占后半）
- `_make_adapter_progress_handler(job_id)`：
  - 适配 `ingest_universal_toppic` 的 `ProgressEvent`
  - 把 adapter 内部进度持续写入 import_jobs（并 clamp 到 99.5，100 留给 success）

## L645-L954：`run_zip_import_job`（后台导入主函数）

> 这是整套导入流程的核心：解压→识别→决定谱图来源→写库→原子替换目录→写 capability 与 mzML 映射→写 job success/fail。

### L654-L658（目标目录约定）

- `final_dir = DATA_ROOT/<slug_dir>`
- `incoming_dir = DATA_ROOT/<slug_dir>.incoming`
- `keep_incoming_on_error`：
  - 当出现“DB 已成功但 rename 失败”等情形，保留 incoming 供排查

### L661-L693（Phase: extract）

- 更新 job：running/extract
- 清理旧 incoming 并创建新 incoming
- 定义 `_extract_cb`：把解压进度映射到全局 percent 并写回 import_jobs
- `_extract_zip_with_progress(...)`：并行安全解压
- `_maybe_unwrap_single_root_folder(...)`：必要时 unwrap
- `_find_ingest_root(...)`：定位真正 ingest 根目录

### L694-L699（识别输入形态）

- `is_toppic_html_tree`：
  - 以 `toppic_prsm_cutoff/data_js/proteins.js` 是否存在作为判据
- `is_prsm_js_bundle`：
  - 用 `has_prsm_files(ingest_root / "data")` 判定：只要存在支持的 `prsm*` 明细文件即可（目前后缀支持 `.js/.json/.txt`），不再只认 `prsm*.js`

### L698-L719（识别谱图来源：TopFD JS vs mzML memory）

- 默认 `spectra_source = "topfd_js"`
- 若缺少 TopFD `ms1_json` 或 `ms2_json`：
  - 切换为 `mzml_memory`
  - **只做** `build_mapping_from_extracted_dataset` 校验与 mapping 构建（不读 mzML 内容）

### L720-L756（Phase: init / ingest）

- 更新 job：init
- 若是 TopPIC HTML 树：
  - `ingest_mode = "fast"`（TopFD JS）或 `"full"`（mzML memory）
  - 调用 `ingest_universal_toppic(...)` 并传入 progress_callback
- 若是 prsm bundle：
  - 强制 mzML memory，否则失败
  - 调用 `ingest_universal_prsm_js(...)`
- 否则：ZIP 结构不支持 → fail

### L757-L766（补 description）

- 如果用户上传时传了 description：
  - 单独 `UPDATE datasets SET description=...`
  - 因为当前 adapter 的 INSERT 模板不一定包含 description

### L767-L781（原子目录替换）

- 如果 final_dir 已存在：先 rmtree（删除旧版本）
- 把 incoming rename 成 final_dir：
  - Windows 上 rename 可能因句柄占用失败
  - 若失败：标记 keep_incoming_on_error=True，并抛错（DB 已写入，磁盘未替换）

### L782-L907（回写 datasets/source_root + zip hash + capability + run↔mzML 映射）

- 计算 `new_source_root`：
  - 把 ingest_root 相对 incoming_dir 的相对路径，拼到 final_dir 上
  - 解决“导入时 source_root 指向 .incoming”导致后续读谱/删除追错路径的问题
- 写 `datasets.source_root` 与 `datasets.source_zip_sha256`
- 写 `datasets.capabilities.spectra_source`：
  - `topfd_js` 或 `mzml_memory`（前端据此决定调用哪套谱图 API）
- 若是 `mzml_memory`：
  - 必须有 `mzml_mapping`
  - 删除 adapter 创建但没有 match 的默认 run（full 模式下可能产生）
  - 遍历 `runs`：
    - 用 `run.file_name` 规范化 key
    - 在 mzml_mapping 中找到唯一 mzML path
    - 写入 `runs.run_metadata = run_metadata || {"mzml_file_path": "..."}`
  - 若有 run 无法映射：导入失败（strict）

### L886-L907（并发重复 ZIP 的回滚）

- `IntegrityError`（zip sha256 唯一索引冲突）：
  - 说明并发导入撞车
  - 调用 `delete_dataset(slug, bypass_active_job_guard=True)` 回滚 DB+磁盘
  - 抛出 RuntimeError 给 job error

### L909-L931（写 success）

- 记录日志摘要（dataset_id/run_id/proteins/proteoforms/matches）
- `_update_job(... status="success", progress=100, stage="success")`

### L932-L953（写 failed + 清理）

- 捕获任何异常：
  - 写 job failed（error=异常字符串）
  - 若不需要保留 incoming：尽力 rmtree incoming_dir
  - finally：删除临时 zip 文件

## L956-L979：`start_zip_import_background`

- 创建 daemon thread 执行 `run_zip_import_job(...)`：
  - daemon=True：进程退出时不阻塞
  - name 里带 job_id，便于调试线程

## L981-L1102：`delete_dataset`（DB + disk 删除）

### L994-L1025（DB 侧删除）

- 若不是 bypass 且 slug 有 active job → 409 语义（这里抛 RuntimeError 给 API 层处理）
- 查 `datasets`：
  - 不存在 → `LookupError`
- `DELETE FROM datasets WHERE dataset_id=...`：
  - 依赖 FK 的 `ON DELETE CASCADE` 清理 runs/proteins/proteoforms/identification_matches/protein_relation_mapping

### L1026-L1069（磁盘侧候选目录推导与安全护栏）

- 只允许删除 `DATA_ROOT` 子树下的目录：
  - `_top_under_data_root(p)`：
    - 如果 p 不在 data_root 下 → 返回 None（拒绝）
    - 如果在 data_root 下，但 p 是子目录：向上爬到“data_root 直接子目录”，删除时删整个数据集目录
- 构造候选目录：
  - 优先从 `datasets.source_root` 推导（如果有）
  - fallback 到 `DATA_ROOT/<slug_dir>`
  - 额外加入 `<slug_dir>.incoming`（清理崩溃残留）
- 若一个候选都推不出来：抛 ValueError（拒绝删除未知路径）

### L1071-L1101（执行删除并返回结果）

- 依次尝试删除 candidates（存在才删）
- 返回：
  - `deleted_db=True`
  - `deleted_disk`：至少删掉一个候选目录则为 True
  - `folder`：primary（第一个候选）用于前端展示
  - `folder_existed`：是否至少存在一个候选目录

---

## 补充：关键实现细节（与源码行号一一对应）

以下段落把上文“分段摘要”里最容易被略过的实现细节，按源码行号钉死，便于对照阅读 `import_jobs.py`。

### `L388-L451`：`_extract_zip_with_progress` 解压与进度语义

- **L401-L402**：`dest.resolve()` 并 `mkdir(parents=True)`，保证目标目录是绝对路径且已存在。
- **L404-L405**：打开 `ZipFile` 后调用 `_collect_zip_entries`：此时已完成 zip-slip 校验，并得到 `(infos, dir_paths, file_infos)`。
- **L407-L411**：`n_total = max(len(infos), 1)`：进度总数与旧实现一致——**目录条目 + 文件条目**都算在 `infolist()` 里；至少为 1 避免除零。
- **L413-L423**：若提供 `on_progress`，先报 `0/n_total`；再一次性创建所有 `dir_paths`（减少每个文件 `mkdir` 的开销）。
- **L421-L423**：把“目录已建好”视为已完成 `n_dirs` 份进度，并 `on_progress(min(done, n_total), n_total)`。
- **L425-L429**：若无文件条目，直接报到 `n_total` 并返回（只有目录的 zip）。
- **L431-L447**：`ZIP_EXTRACT_WORKERS=12`，`chunk_size=500`：把 `file_infos` 切成多块提交 `ThreadPoolExecutor`；每块在单线程里调用 `_extract_chunk`（read→write，不在块内 mkdir）。
- **L440-L447**：`as_completed` 聚合 future：累加 `extracted_files`，`done = n_dirs + extracted_files`，持续回调进度直到全部文件写完。
- **L449-L450**：最后再回调一次 `n_total/n_total`，保证 UI 收到 100% 的 extract 子进度（在 `_phase_percent("extract", ...)` 映射下落在 extract 窗口内）。

### `L605-L638`：`_phase_percent` 与 `_make_adapter_progress_handler`

- **L607-L612**：取 `_PHASE_RANGES[phase]` 的 `(start, end)`，`span = end - start`；`local = current/total` 并 clamp 到 `[0,1]`。
- **L614-L615**：若 `cutoff` 为空或不在 `_CUTOFF_ORDER`：全局进度 = `start + span * local`（该阶段内线性）。
- **L617-L620**：若带 `cutoff`：把 `span` 均分给每个 cutoff kind（顺序来自 `cutoff_kinds()`）；当前 cutoff 的切片起点为 `cutoff_offset = order * per_cutoff`，进度为 `start + cutoff_offset + per_cutoff * local`。这样同一 phase 内 prsm 事件占前半窗口、proteoform 占后半窗口（与 architecture.md 描述一致）。
- **L624-L636**：`handle(ProgressEvent)`：用 `_phase_percent` 算 `pct`，再 **clamp 到 `[0, 99.5]`**——避免内部阶段把进度顶到 100%（100 仅保留给 job 成功落库后的最终状态）。
- **L629-L636**：`_update_job` 写入 `progress/stage/stage_label/stage_detail/message`：`stage_detail` 与 `message` 都使用 adapter 传来的 `event.message`（例如 “1234/5678 PrSM details”）。

### `L768-L797`：原子替换目录与 Windows rename 重试

- **L773-L774**：DB ingest 已成功后再 `rmtree(final_dir)`（删除旧版本数据集目录）。
- **L776-L785**：最多 8 次尝试 `incoming_dir.rename(final_dir)`：每次失败后 `sleep(0.35 * attempt)`，缓解杀毒/资源管理器短暂占锁。
- **L786-L796**：若仍失败：不抛异常终止 success 路径的“业务结果”，而是 **降级**——`keep_incoming_on_error=True`，`final_dir_used = incoming_dir`，并打 warning 日志；这样 `source_root` 后续会指向仍位于 `.incoming` 下的路径（见下一段修正逻辑），避免“DB 有数据但磁盘目录丢失”。

### `L798-L807`：`source_root` 从 `.incoming` 平移到 `final_dir`

- **L798-L806**：`ingest_root.relative_to(incoming_dir.resolve())` 得到 ingest 根相对 incoming 的相对路径；若 ingest_root 不在 incoming 下（`ValueError`），用空相对路径。
- **L807**：`new_source_root = (final_dir_used / rel_to_incoming).resolve()`：无论 rename 是否成功，都把 DB 里的 `datasets.source_root` 更新为“最终实际目录 + 相对 ingest 子路径”，保证 spectrum 读取与删除逻辑追的是真实磁盘位置。

### `L898-L915`：`IntegrityError`（并发重复 ZIP）回滚

- **L902-L915**：在 `UPDATE datasets SET source_root, source_zip_sha256` 等 finalize 写入时，若触发 `source_zip_sha256` 唯一索引冲突：说明并发两次导入同一 ZIP 内容；记录 warning 后调用 **`delete_dataset(slug, bypass_active_job_guard=True)`** 回滚刚写入的 DB 行与磁盘目录，再抛出带用户提示的 `RuntimeError`，避免留下半套数据集。

### `L948-L969`：失败路径与 `finally`

- **L948-L958**：任意异常：job 标记 `failed`，`error=str(exc)`，`stage_detail` 同步错误文本。
- **L959-L964**：若 **未** 处于 `keep_incoming_on_error`：尽力删除 `incoming_dir`（部分解压残留）。
- **L965-L969**：`finally`：无论成功失败，尝试 `zip_path.unlink(missing_ok=True)` 删除上传临时 zip，避免磁盘堆积。

