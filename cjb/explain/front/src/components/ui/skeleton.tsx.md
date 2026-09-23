## `front/src/components/ui/skeleton.tsx` 逐行解释

> 来源文件：`front/src/components/ui/skeleton.tsx`

> `Skeleton` 是加载占位组件：用灰色块 + pulse 动画模拟内容正在加载。

---

## L1-L2：依赖

- `cn`：合并 className。

---

## L3-L13：`Skeleton` 组件

- 透传 `React.HTMLAttributes<HTMLDivElement>`，外部可以控制宽高（例如 `w-40 h-4`）。
- 默认类名 `animate-pulse rounded-md bg-muted/60`，并与外部 className 合并。

