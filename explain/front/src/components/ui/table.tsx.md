## `front/src/components/ui/table.tsx` 逐行解释

> 一组 Table 组件封装：`Table/Header/Body/Row/Head/Cell`，统一样式并提升可复用性（尤其是 sticky header、hover 行高亮）。

---

## L1-L2：依赖

- `React`：forwardRef 与表格相关 props 类型。
- `cn`：合并 className。

---

## L4-L11：`Table`

- 外层包一层 `div`（`overflow-auto`），解决宽表格横向滚动问题。
- 内部渲染 `<table>`，默认 `w-full caption-bottom text-sm`。

---

## L13-L25：`TableHeader`

- 渲染 `<thead>`，并提供：
  - `sticky top-0`：表头在滚动容器内固定
  - 半透明背景 + blur：避免遮挡内容时难看
  - `[_tr]:border-b`：对表头行加下边框

---

## L27-L33：`TableBody`

- 渲染 `<tbody>`，并让最后一行去掉边框（更干净）。

---

## L34-L47：`TableRow`

- 默认每行有下边框、hover 高亮，并支持 `data-[state=selected]` 的选中态背景。

---

## L48-L61：`TableHead`

- 渲染 `<th>`：
  - 默认高度 `h-10`、左右 padding、文本弱化颜色
  - `whitespace-nowrap` 防止表头折行
  - 对包含 checkbox 的列做 padding 特殊处理（`[:has([role=checkbox])]`）

---

## L62-L72：`TableCell`

- 渲染 `<td>`，默认 `p-3` + `whitespace-nowrap`，并同样对 checkbox 列做 padding 调整。

