## `front/src/features/prsm/SpectrumModal.tsx` 逐行解释

> 来源文件：`front/src/features/prsm/SpectrumModal.tsx`

> 目标：提供一个轻量的全屏 overlay 容器，用于在 PrSM 详情页里“放大查看谱图”。它只负责 UI 框架（遮罩、标题栏、关闭行为、禁用 body 滚动），不负责谱图状态（zoom 等由父组件持有）。

---

### L1-L2：依赖

- **L1**：`useEffect` 用于挂载/卸载全局键盘监听与 body 滚动锁；`ReactNode` 用于标题/子标题类型。
- **L2**：关闭按钮图标。

---

### L4-L11：Props 定义

- **L5**：`title`：标题允许传任意 ReactNode（可以是包含高亮/徽章的复杂标题）。
- **L6**：`subtitle`：可选副标题（通常显示 scan/run 等信息）。
- **L7**：`onClose`：关闭回调（父组件决定如何切换 modal open 状态）。
- **L8**：`children`：主体内容（一般是 `SpectrumChart` + 其它信息）。
- **L9-L10**：`actions`：右侧可插入额外按钮（例如“reset zoom”之类），避免把控制逻辑写死在 modal 组件里。

---

### L13-L17：组件职责说明（docstring）

- **L14-L16**：强调“modal 不保存状态”。这与 `SpectrumChart` 的受控 zoom 机制配套：父组件在 modal 打开/关闭时仍能保留 zoom。

---

### L18-L30：`useEffect` —— ESC 关闭 + body 滚动锁

- **L19-L23**：注册 `keydown` 监听，按 `Escape` 调用 `onClose()`。
- **L24-L25**：记录原本 `document.body.style.overflow`，然后设置为 `"hidden"`，防止背景页面滚动（全屏 overlay 的标准 UX）。
- **L26-L29**：cleanup：
  - 移除 `keydown` 监听。
  - 恢复 body overflow 到进入 modal 前的值（避免影响其它页面/模态框）。
- **L30**：effect 依赖 `onClose`，确保回调更新时监听逻辑与之同步。

---

### L32-L65：JSX 结构（遮罩 → 内容卡片 → 标题栏 → 主体）

- **L33-L38**：最外层遮罩：
  - `fixed inset-0 z-50`：覆盖全屏并置顶。
  - `bg-black/55 backdrop-blur-sm`：半透明黑色背景 + 背景模糊。
  - `onClick={onClose}`：点击遮罩（非内容区域）关闭。
  - `role="dialog" aria-modal="true"`：可访问性语义。
- **L39-L42**：内容卡片容器：
  - 固定高度 `h-[88vh]` 与宽度 `w-[94vw]`，最大宽度限制，适配大屏。
  - `onClick={(e) => e.stopPropagation()}`：阻止点击内容区域冒泡到遮罩层，避免误触关闭。
- **L43-L61**：标题栏：
  - 左侧：标题（可截断）+ 可选副标题。
  - 右侧：先渲染 `actions`（可选），再渲染关闭按钮。
- **L52-L59**：关闭按钮：图标按钮，hover 态更明显。
- **L62**：主体区域：`flex-1 overflow-hidden p-4`，让内部（如谱图）自己决定滚动/缩放方式，外层不产生额外滚动条。

---

### 与其它模块的关系

- **与 `PrsmDetailPage.tsx`**：`PrsmDetailPage` 负责：
  - 决定何时打开/关闭 modal；
  - 决定 modal 标题/副标题；
  - 传入 `actions`（例如复位按钮）；
  - 持有并传入受控 zoom（保证打开/关闭不会丢）。
- **与 `SpectrumChart.tsx`**：modal 只是容器；谱图交互完全由 `SpectrumChart` 实现。

