# `back/app/services/mzml_store.py` 逐行解释

> 来源文件：`back/app/services/mzml_store.py`

## L1-L9（模块定位与约束）

- 这是 mzML 的**进程内存缓存（legacy 单 run LRU）**：
  - 新 mzML-memory 数据集优先走 **`app.spectrum_memory`** 整包驻留；本模块仍可能被旧代码路径引用。
  - 按 `run_id` 做 key（`runs.run_metadata.mzml_file_path`）
  - 第一次谱图请求时才加载整个 mzML 并建立 scan 索引

## L13-L20（导入）

- `re`：解析 native id 里的 `scan=123`
- `threading`：并发加载控制（避免同一 run_id 被多线程重复加载）
- `gzip`：支持直接读取 `.mzML.gz`（mzML 压缩包），避免导入时解压到磁盘再读
- `dataclass`：存放缓存结构
- `pyteomics.mzml`：mzML 读取器

## L22-L28：scan 解析

- `_SCAN_RE = re.compile(r"scan=(\d+)")`
- `_parse_scan(native_id)`：
  - 从 spectrum 的 native id（例如 `controllerType=0 controllerNumber=1 scan=161`）提取 scan number
  - 无法解析返回 None（此 spectrum 不进入索引）

## L30-L38：RT 单位统一为秒

- `_rt_seconds(spec)`：
  - 从 mzML 的 `scanList.scan[].scan start time` 取 RT
  - 若 unit 是 minute 则乘以 60
  - 取不到则返回 0.0

## L41-L72：提取 precursor 信息（MS2）

- `_extract_precursor(spec)`：
  - 从 `precursorList.precursor[0]` 里抽取：
    - isolation window：target/lower/upper offset
    - selected ion：mz、charge
    - parent scan（从 spectrumRef 解析）
  - 内部 `_f/_i` 用于把字段安全转成 float/int（异常返回 None）

## L75-L86：抽取 spectrum（统一结构）

- `_extract_spectrum(spec, scan)` 返回 dict：
  - `scan/native_id/ms_level/rt_seconds`
  - `mz[]/intensity[]`：把 numpy array 转 list（可 JSON 序列化）
  - `precursor`：MS2 才可能有

## L89-L93：`_RunCache`

- 缓存条目结构：
  - `path`：mzML 文件路径（resolve 后）
  - `spectra`：`scan_number -> spectrum_dict` 的索引

## L95-L184：`MzmlStore`（核心缓存类）

### L98-L104（初始化）

- `max_runs`：最多缓存多少个 run 的 mzML（默认 4）
- `_lock`：全局互斥（保护 cache、lru、loading）
- `_loading`：`run_id -> Event`，用于“正在加载”的并发等待
- `_cache`：`run_id -> _RunCache`
- `_lru`：维护访问顺序，超限时驱逐

### L105-L114（LRU 维护）

- `_touch(run_id)`：把 run_id 移到 lru 末尾（最近使用）
- `_evict_if_needed()`：当超过 max_runs，弹出最久未使用的 run 并从 `_cache` 移除

### L115-L118：`is_loaded`

- 判断某 run_id 是否已经在内存中

### L119-L131：`status`

- 返回该 run 的缓存状态摘要（loaded/path/scan 数量、ms1/ms2 数量）
- 主要用于调试或未来的监控 API

### L133-L186：`load_run(run_id, mzml_path)`

- 目标：**只允许一个线程真正加载**；其它线程等待 Event 完成
- 逻辑：
  - 若该 run 已加载且路径一致：只 touch 并返回
  - 若发现 `_loading[run_id]` 已存在：说明别的线程在加载 → wait() 后返回
  - 否则当前线程成为 loader：
    - 根据扩展名选择读取方式：
      - `.mzML.gz` / `.mzML.gzip`：用 `gzip.open(..., "rb")` 再交给 `mzml.read(fh)`
      - 其他：`mzml.read(str(path))`
    - 迭代所有 spectrum
    - 从 native id 解析 scan，建立 `spectra[scan] = _extract_spectrum(...)`
  - finally：无论成功失败，都 set Event，保证等待者不死锁
  - 成功后写入 `_cache` 并触发 LRU 驱逐

### L175-L181：`get_spectrum(run_id, scan_number)`

- 返回 scan 对应的 spectrum dict（不存在返回 None）
- 同时 touch LRU（访问即刷新）

## L184

- `STORE = MzmlStore()`：进程全局单例，API 层直接复用

