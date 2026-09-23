# 三维 LC-MS

## 1. 当前组件

```text
PrsmDetailPage
└─ Lcms3DPanel
   └─ ThreeLcmsScene
      ├─ THREE.Scene / PerspectiveCamera
      ├─ WebGLRenderer
      ├─ OrbitControls
      ├─ axes
      └─ stick plot
```

外层组件：[`Lcms3DPanel.tsx`](../src/features/lcms3d/Lcms3DPanel.tsx)。底层场景：[`ThreeLcmsScene.tsx`](../src/features/lcms3d/ThreeLcmsScene.tsx)。输入类型：[`types.ts`](../src/features/lcms3d/types.ts)。

## 2. 输入和语义

`Peak` 只有 `mz` 和 `intensity`。`Lcms3DPanel` 会过滤非有限值和非正强度，并展示 scan、RT（秒转分钟）和有效峰数量。

当前名称虽然是 “LC-MS Single Scan 3D Spectrum”，实际是一张单扫描三维 stick spectrum：

- X：m/z。
- Y：归一化强度高度。
- Z：用于立体布局，不代表额外采集维度。
- 颜色：主题 heat/Viridis 色板。

Agent 不应把它误解为完整的 RT×m/z×intensity LC-MS surface。

## 3. Three.js 行为

[`ThreeLcmsScene`](../src/features/lcms3d/ThreeLcmsScene.tsx) 当前行为：

- `PerspectiveCamera(44)`，固定初始位置。
- `OrbitControls` 开启 damping、pan 和距离限制。
- `WebGLRenderer` 开启 antialias，并把 pixel ratio 限制在 2。
- `ResizeObserver` 同步容器尺寸。
- 每帧 `requestAnimationFrame` 更新 controls 并 render。
- 首次成功 render 调用 `onFirstRender`。
- renderer 创建或 render 失败调用 `onRenderError`。
- effect cleanup 释放 controls、geometry/material、renderer 和 canvas。
- 主题变化时重建场景并读取当前主题颜色。

## 4. 降级与测试

`Lcms3DPanel` 对三种情况分别处理：

- 无有效峰：显示空提示，不创建 WebGL。
- WebGL 创建/渲染失败：显示 `PlotStatus(kind="error")`。
- 成功：渲染 `ThreeLcmsScene`，并将首帧信号传给页面切换系统。

[`page-transition.spec.ts`](../tests/page-transition.spec.ts) 验证暗色模式直接访问/刷新时，遮罩持续到 Three.js 第一帧。

## 5. 依赖边界

- Three.js 版本见 [`package.json`](../package.json)。
- Three.js 只能存在于场景组件；API 请求和 PrSM 数据解析不应依赖 Three.js。
- 组件不读取后端接口，数据由 [`PrsmDetailPage.tsx`](../src/pages/PrsmDetailPage.tsx) 提供。
