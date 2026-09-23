# `front/src/features/lcms3d/Lcms3DPanel.tsx` 逐行解释

> 来源文件：`front/src/features/lcms3d/Lcms3DPanel.tsx`
> 模块职责：PrSM 详情页 MS1 单扫描的三维棒状谱图卡片容器。

## L8-L12（Props）

- `peaks`：当前 MS1 scan 的峰列表（可 null/undefined）。
- `scan`、`retentionTimeSeconds`：副标题展示用。

## L14-L32

- `cleanPeaks`：过滤非有限 m/z/强度或 intensity≤0 的峰。
- `rtMin`：秒转分钟；`subtitle` 拼接 Scan、RT、峰数量。

## L34-L53（渲染）

- 无峰时提示「该扫描暂无可显示的峰」。
- 有峰时渲染 `ThreeLcmsScene`（高度 480px）。
- Card 标题说明坐标轴：X m/z，Y 强度，Viridis 着色。

## 与相邻模块的耦合

- **PrsmDetailPage.tsx**：在 MS1 谱加载成功后传入 peaks/scan/RT。
- **ThreeLcmsScene.tsx**：Three.js 实际绘制。
- 无独立 API 模块（原 `api.ts` 已删除；数据来自 PrSM 页已有 spectrum 查询）。
