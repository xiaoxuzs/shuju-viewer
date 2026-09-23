# `front/src/features/lcms3d/types.ts` 逐行解释

> 来源文件：`front/src/features/lcms3d/types.ts`
> 模块职责：LC-MS 3D 可视化共用的峰数据结构。

## L1-L4

- `Peak`：`mz`（Da）与 `intensity`（任意正数强度单位，与后端 spectrum dict 一致）。

## 与相邻模块的耦合

- **Lcms3DPanel.tsx**：过滤无效/非正强度峰后传给 ThreeLcmsScene。
- **PrsmDetailPage.tsx**：从 MS1 spectrum 的 `mz[]`/`intensity[]` 组装 `Peak[]` 传入 Panel。
