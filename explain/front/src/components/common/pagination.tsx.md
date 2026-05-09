## `front/src/components/common/pagination.tsx` 逐行解释

> 一个轻量分页组件：显示当前页范围（from–to / total），并提供首页/上一页/下一页/末页按钮。

---

## L1-L6：依赖

- **L1-L3**：文件注释说明用途。
- **L4**：lucide 图标：单箭头/双箭头。
- **L5**：复用通用 `Button` 组件（统一样式与可访问性）。

---

## L7-L79：`Pagination` 组件

### Props（L7-L17）

- **page/pageSize/total**：分页三要素。
- **onPageChange**：外部回调；组件本身不持有状态。

### 计算（L18-L21）

- `totalPages = max(1, ceil(total/pageSize))`：保证至少显示 `1` 页，避免 UI 出现 `0/0`。
- `from/to`：用于 “Showing x–y of z” 的区间展示；当 `total==0` 时 from=0。

### UI（L22-L78）

- 左侧：当 `total==0` 显示 `No rows`；否则显示区间与总数（`toLocaleString()` 增加千分位）。
- 右侧：四个按钮：
  - 跳到第一页（禁用条件 `page<=1`）
  - 上一页（禁用条件 `page<=1`）
  - 下一页（禁用条件 `page>=totalPages`）
  - 跳到最后一页（禁用条件 `page>=totalPages`）
- 中间显示 `page / totalPages`。

