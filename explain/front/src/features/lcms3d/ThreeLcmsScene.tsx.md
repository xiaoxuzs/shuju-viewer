# `front/src/features/lcms3d/ThreeLcmsScene.tsx` 逐行解释

> 来源文件：`front/src/features/lcms3d/ThreeLcmsScene.tsx`
> 模块职责：用 Three.js 绘制 LC-MS 单扫描三维棒状图（实际为 2.5D：X=m/z，Y=强度，Z 仅用于网格厚度）。

## L19-L84（React 生命周期）

- `useEffect` 依赖 `[peaks]`：容器 ref 挂载后创建 Scene/Camera/Renderer/OrbitControls。
- `makeStickPlot` + `makeAxes` 加入场景；ResizeObserver 自适应宽高；RAF 循环渲染。
- cleanup：cancelAnimationFrame、dispose controls/geometry/material、移除 canvas。

## L107-L159（棒状图）

- `computeMzRange` / `computeIntensityMax`：数据范围。
- `makeStickPlot`：每峰一条竖线（LineSegments），顶点色按 Viridis 映射强度。

## L161-L208（坐标轴）

- 地面网格（m/z 方向）；X/Y 轴；m/z 与强度 tick 文字 sprite；轴标签「m/z (Da)」「强度」。

## L247-L307（工具函数）

- `viridis`：5 停点线性插值近似 matplotlib Viridis。
- `scale` / `formatTick` / `disposeObject`：几何缩放、刻度格式、资源释放。

## 与相邻模块的耦合

- **Lcms3DPanel.tsx**：唯一父组件，传入已清洗的 `Peak[]`。
- 纯客户端渲染，不发起 HTTP 请求。
