## `front/src/main.tsx` 逐行解释

> 来源文件：`front/src/main.tsx`

> 目标：前端入口文件。负责创建 React 根节点，挂载 Router（`BrowserRouter`）与数据获取层（TanStack Query 的 `QueryClientProvider`），并加载全局样式。

---

### L1-L4：文件级注释（入口职责 + Query 默认策略）

- **L1-L2**：说明这是应用入口，挂载 React、React Router、TanStack Query。
- **L3-L4**：概述 Query 默认策略：
  - 关闭窗口聚焦自动刷新（避免频繁请求）
  - 30s staleTime（30 秒内视为“新鲜数据”）
  - 失败重试 1 次（避免无限重试）

这些配置会影响所有页面的请求行为（除非单个 query 覆盖）。

---

### L5-L12：依赖

- **L5-L6**：React 与 ReactDOM root API（React 18 的 `createRoot`）。
- **L7**：`BrowserRouter`：基于 HTML5 history 的路由容器。
- **L8**：TanStack Query：`QueryClient`（配置）与 `QueryClientProvider`（上下文注入）。
- **L10**：导入根组件 `App`（内部定义所有 routes）。
- **L11**：加载全局样式（Tailwind/主题变量等通常在这里汇总）。

---

### L13-L21：创建全局 `queryClient`

- **L13**：实例化一个 `QueryClient`。
- **L14-L20**：设置默认 options：
  - `refetchOnWindowFocus:false`：用户切回标签页不会自动刷新
  - `staleTime:30_000`：30s 内不认为数据过期
  - `retry:1`：失败后最多重试一次

这几项对“列表页/详情页体验”很关键：既减少抖动与请求量，又保留一定的自动恢复能力。

---

### L23-L31：挂载 React 树

- **L23**：找到 DOM 中的 `#root` 并创建 root。`!` 表示开发者确信该元素存在（否则会在运行期报错）。
- **L24**：`React.StrictMode`：开发模式下额外执行一些检查/双调用以帮助发现副作用问题。
- **L25**：`QueryClientProvider`：把 query client 注入全局上下文，后续页面可以使用 `useQuery` 等 hooks。
- **L26-L28**：`BrowserRouter`：注入路由上下文，`App` 里的 `Routes` 才能生效。

---

### 与其它模块的耦合点

- **与 `front/src/App.tsx`**：`main.tsx` 只负责挂载；真实路由表在 `App.tsx`。
- **与 `front/src/api/client.ts`**：Query 的请求函数通常调用 `client.ts` 导出的 `fetchXxx`。
- **与页面组件**：所有页面 `useQuery` 默认遵循这里的 staleTime/retry/refetch 策略。

