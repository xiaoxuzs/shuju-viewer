# LC-MS 三维图验收说明

## 目标

在 PrSM 详情页的 `Fragmentation annotation` 下方展示真 3D LC-MS 图，坐标为：

- X：RT seconds
- Y：m/z
- Z：intensity

图形使用 Three.js WebGL 点云渲染，支持旋转、缩放和平移。前端只消费统一的 LC-MS DTO，不直接理解 TopFD JS 或 mzML 的原始结构。

## 当前兼容路径

- `topfd_js`：面向当前 `MZ20160222DS_histone49_html` 数据集。后端按当前 PrSM 的 MS1 spectrum id 读取附近谱图文件，并在服务端做 RT/mz 分箱。
- `mzml_memory`：面向后续 mzML 进内存缓存路径。后端从 `app.spectrum_memory` 读取当前 run 的驻留 scan map，并复用同一套分箱逻辑。

## 手工验收

1. 启动后端和前端。
2. 打开 49 数据集中的任意 PrSM 详情页。
3. 确认页面顺序为：
   - MS1 / MS2 谱图
   - Fragmentation annotation
   - LC-MS 3D map
   - Matched fragment peaks
4. 确认 LC-MS 3D map 不为空，右上角显示 source、frames、points。
5. 用鼠标拖拽、滚轮缩放、右键/触控板平移，确认 3D 场景可交互且坐标网格稳定。

## 性能验收

运行：

```powershell
$env:VIEWER_LCMS_DATASET_ID="你的 dataset_id"
$env:VIEWER_LCMS_RUN_ID="你的 run_id"
$env:VIEWER_LCMS_CENTER_SPEC_ID="当前 PrSM 的 ms1_id"
$env:VIEWER_LCMS_CENTER_SCAN="当前 PrSM 的 ms1_scan"
$env:VIEWER_LCMS_PRECURSOR_MZ="当前 PrSM 的 precursor_mz"
python cs/LCMS三维性能测验.py
```

可选参数：

- `VIEWER_API_BASE`：默认 `http://127.0.0.1:8000/api/v1`
- `VIEWER_LCMS_MAX_SECONDS`：默认 `0.5`
- `VIEWER_LCMS_FRAME_RADIUS`：默认 `18`（中心帧前后各 18 帧，共 37 帧叠加）

验收重点不是读取全量原始文件，而是确认服务端返回的是已经分箱和限点后的用户可交互数据。
