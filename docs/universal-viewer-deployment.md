# Universal Viewer 部署说明

本文说明如何把 Universal Viewer 的数据库结构和导入流程交给其他人部署。

---

## 1. Git 中应该提交什么

应该提交：

- `docs/universal_schema.sql`：Universal Viewer 新数据库的建表脚本。
- `docs/universal-viewer-deployment.md`：部署说明。
- `docs/universal-viewer-summary.md`：本次改造总结。
- `添加数据说明.md`：数据导入说明。
- `back/app/ingest/universal_toppic_adapter.py`：TopPIC / TopFD 导入适配器。
- `back/.env.example`：环境变量模板。

不应该提交：

- `back/.env`：包含本机密码，不要提交。
- `shuju/`：真实质谱数据体积大，不应进入 Git。
- `topfd/ms1_json/spectrum*.js`
- `topfd/ms2_json/spectrum*.js`
- `toppic_*_cutoff/data_js/prsms/prsm*.js`
- PostgreSQL 本地数据目录或二进制数据库文件。

---

## 2. 初始化数据库

### 2.1 创建数据库

在 PostgreSQL 可视化工具或 `psql` 中创建数据库：

```sql
CREATE DATABASE "Universal_Viewer";
```

如果数据库已经存在，可以跳过这一步。

### 2.2 导入表结构

在仓库根目录执行：

```powershell
psql -h localhost -U postgres -d "Universal_Viewer" -f "docs/universal_schema.sql"
```

如果 `psql` 不在 PATH 中，可以在 PostgreSQL 可视化界面中打开 `docs/universal_schema.sql`，然后在 `Universal_Viewer` 数据库的 Query Tool 中执行全文。

导入完成后，应看到 7 张表：

```text
datasets
runs
proteins
peptides
proteoforms
identification_matches
protein_relation_mapping
```

---

## 3. 配置后端环境变量

复制模板：

```powershell
cd back
Copy-Item .env.example .env
```

修改 `back/.env`：

```text
DATABASE_URL=postgresql+psycopg://postgres:<your_password>@localhost:5432/Universal_Viewer
DATA_ROOT=../shuju
API_CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
LOG_LEVEL=INFO
SPECTRUM_CACHE_SIZE=256
```

注意：

- 不要把真实 `.env` 提交到 Git。
- 如果修改了 `.env`，必须重启后端服务。

---

## 4. 安装后端依赖

在 `back/` 目录执行：

```powershell
uv sync
```

---

## 5. 放置数据文件

把 TopPIC / TopFD HTML 输出目录放到本机可访问的位置。

推荐目录：

```text
viewer/shuju/
```

数据目录结构应类似：

```text
MZ20160222DS_histone48_html/
  topfd/
    ms1_json/spectrum*.js
    ms2_json/spectrum*.js
  toppic_prsm_cutoff/data_js/
    proteins.js
    prsms/prsm*.js
  toppic_proteoform_cutoff/data_js/
    proteins.js
    prsms/prsm*.js
```

真实数据目录不要提交 Git。

---

## 6. 导入数据

在 `back/` 目录执行：

```powershell
uv run python -m app.ingest.universal_toppic_adapter `
  --root "E:/viewer/shuju/MZ20160222DS_histone48_html" `
  --database-url "postgresql+psycopg://postgres:<your_password>@localhost:5432/Universal_Viewer" `
  --slug mz20160222ds_histone48 `
  --name MZ20160222DS_histone48_html `
  --mode fast `
  --replace
```

参数说明：

- `--root`：TopPIC / TopFD HTML 输出目录。
- `--database-url`：目标数据库连接串。
- `--slug`：数据集唯一标识。
- `--name`：数据集展示名称。
- `--mode fast`：快速导入，只读 `proteins.js` 并登记详情路径。
- `--mode full`：完整摘要导入，会逐个解析 `prsm*.js`，更慢。
- `--replace`：删除同 slug 旧数据后重新导入。

推荐部署时使用：

```text
--mode fast
```

---

## 7. fast 模式导入内容

fast 模式会写入：

- `datasets`：1 条数据集记录。
- `runs`：1 条运行记录。
- `proteins`：从 `proteins.js` 解析 protein。
- `proteoforms`：从 `compatible_proteoform` 解析 proteoform。
- `protein_relation_mapping`：写入 protein -> proteoform 归属关系。
- `identification_matches`：从 `proteins.js` 中的 PrSM 摘要写入 match 记录。

fast 模式不会写入：

- 谱图峰列表。
- 完整 `ms_header`。
- 完整 `ms_peaks`。
- 完整 `annotated_protein`。

这些详情会在前端打开 PrSM 详情时，通过 `identification_matches.detail_path` 按需读取。

---

## 8. 验证数据库内容

导入后可以执行：

```sql
SELECT count(*) FROM datasets;
SELECT count(*) FROM runs;
SELECT count(*) FROM proteins;
SELECT count(*) FROM peptides;
SELECT count(*) FROM proteoforms;
SELECT count(*) FROM identification_matches;
SELECT count(*) FROM protein_relation_mapping;
```

查看来源 cutoff：

```sql
SELECT
  jsonb_extract_path_text(extra_metadata, 'source_cutoff') AS source_cutoff,
  count(*)
FROM identification_matches
GROUP BY source_cutoff
ORDER BY source_cutoff;
```

查看导入模式：

```sql
SELECT
  jsonb_extract_path_text(extra_metadata, 'import_mode') AS import_mode,
  count(*)
FROM identification_matches
GROUP BY import_mode;
```

当前示例数据集的 fast 导入结果应类似：

```text
datasets                         1
runs                             1
proteins                         32
peptides                         0
proteoforms                      1236
identification_matches           14169
protein_relation_mapping         1236
```

---

## 9. 启动服务

启动后端：

```powershell
cd back
uv run uvicorn app.main:app --reload --port 8000
```

启动前端：

```powershell
cd front
pnpm install
pnpm dev
```

浏览器打开前端页面后，应能看到导入的数据集。

---

## 10. 常见问题

### 后端还是读旧数据库

检查 `back/.env`：

```text
DATABASE_URL=postgresql+psycopg://postgres:<your_password>@localhost:5432/Universal_Viewer
```

修改后必须重启后端。

### 前端打开详情时才变慢

这是正常的。fast 模式不提前解析全部 `prsm*.js`，详情页会按需读取对应文件。

### 数据集路径换了以后谱图打不开

数据库中的 `datasets.source_root` 和 `runs.file_path` 保存的是导入时的路径。

如果数据目录移动了，需要重新导入，或手动更新这两个字段。

### 能不能提交真实数据

不建议。真实数据体积大，而且包含大量 `spectrum*.js` 和 `prsm*.js`。应通过外部数据包或共享盘分发，不进入 Git。
