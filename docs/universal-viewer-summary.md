# Universal Viewer 改造总结

## 1. 改造目标

本次改造的目标是把原来只面向 TopPIC / TopFD PrSM 的数据库与导入流程，调整为更通用的 Universal Viewer 数据层。

核心目标有三个：

1. 使用新数据库 `Universal_Viewer`。
2. 使用统一的 7 张核心表承接 Top-down 和未来 Bottom-up 数据。
3. 实现 TopPIC / TopFD 数据的快速导入，谱图峰列表不入库，详情按需读取。

---

## 2. 新数据库结构

当前新库使用 7 张核心表：

- `datasets`：数据集总入口，区分不同导入包或项目。
- `runs`：实验文件表，记录数据目录、原始文件或标准化文件位置。
- `proteins`：基础蛋白表，Bottom-up 和 Top-down 共用。
- `peptides`：肽段表，Bottom-up 专用；当前 Top-down 数据不写入。
- `proteoforms`：蛋白形态表，Top-down 专用。
- `identification_matches`：统一匹配表，替代传统 PSM / PrSM。
- `protein_relation_mapping`：统一关系映射表，表达 protein -> peptide 或 protein -> proteoform。

本次 TopPIC / TopFD 数据属于 Top-down 数据，因此：

- `datasets` 写入 1 条。
- `runs` 写入 1 条。
- `proteins` 从 `proteins.js` 写入。
- `proteoforms` 从 `compatible_proteoform` 写入。
- `identification_matches` 以 `entity_type = PROTEOFORM` 写入。
- `protein_relation_mapping` 写入 protein -> proteoform 关系。
- `peptides` 保持 0 条。

---

## 3. 谱图不入库策略

谱图峰列表不写入 PostgreSQL。

数据库只保存：

- 数据集根目录：`datasets.source_root`
- 运行目录：`runs.file_path`
- 谱图和 PrSM 详情定位信息：`identification_matches.detail_path`
- PrSM 摘要字段：`e_value`、`q_value`、`matched_fragment_number`、`matched_peak_number` 等

前端需要画谱时，后端仍然从磁盘读取：

```text
<dataset_root>/topfd/ms1_json/spectrum*.js
<dataset_root>/topfd/ms2_json/spectrum*.js
```

前端打开 PrSM 详情时，后端通过：

```text
identification_matches.detail_path
```

按需读取对应的：

```text
toppic_*_cutoff/data_js/prsms/prsm*.js
```

这样可以控制数据库体积，并显著缩短导入时间。

---

## 4. TopPIC / TopFD Adapter

新增文件：

```text
back/app/ingest/universal_toppic_adapter.py
```

它负责把 TopPIC / TopFD HTML 输出目录导入到 Universal Viewer 新库。

支持两种模式：

### fast 模式

默认模式。

特点：

- 只读取 `proteins.js`。
- 不逐个打开所有 `prsm*.js`。
- 从 `proteins.js` 中已有的 PrSM 摘要登记 `identification_matches`。
- 只保存 `detail_path`，详情页点击时再读取完整 PrSM 文件。
- 当前数据集实测导入约 9 秒。

适合：

- 快速上线。
- 大数据集快速登记。
- 30 秒内完成入库目标。

### full 模式

完整摘要模式。

特点：

- 读取 `proteins.js`。
- 逐个打开 `prsm*.js`。
- 从每个详情文件提取更完整的前体、scan、ms id 等字段。
- 导入更慢，当前数据集约 4 分钟。

适合：

- 需要把更多摘要字段提前落库。
- 不追求 30 秒导入。

---

## 5. 当前数据集导入结果

当前数据集路径：

```text
E:/viewer/shuju/MZ20160222DS_histone48_html
```

导入命令：

```powershell
uv run python -m app.ingest.universal_toppic_adapter `
  --root "E:/viewer/shuju/MZ20160222DS_histone48_html" `
  --database-url "postgresql+psycopg://postgres:1wsx3qaz@localhost:5432/Universal_Viewer" `
  --slug mz20160222ds_histone48 `
  --name MZ20160222DS_histone48_html `
  --mode fast `
  --replace
```

fast 模式导入结果：

```text
datasets                         1
runs                             1
proteins                         32
peptides                         0
proteoforms                      1236
identification_matches           14169
protein_relation_mapping         1236
```

`identification_matches` 中的 cutoff 来源：

```text
prsm          8008
proteoform    6161
```

所有 `identification_matches.extra_metadata.import_mode` 均为：

```text
fast
```

---

## 6. 后端兼容层

现有前端仍然使用旧 API 路径和旧响应字段，例如：

```text
/api/v1/datasets
/api/v1/datasets/{slug}/cutoffs/{cutoff}/proteins
/api/v1/datasets/{slug}/cutoffs/{cutoff}/proteoforms
/api/v1/datasets/{slug}/cutoffs/{cutoff}/prsms
/api/v1/datasets/{slug}/cutoffs/{cutoff}/prsms/{prsm_id}
/api/v1/datasets/{slug}/spectra/ms1/{spec_id}
/api/v1/datasets/{slug}/spectra/ms2/{spec_id}
```

为了让前端先不大改，本次增加了兼容层：

```text
back/app/api/v1/universal_compat.py
```

并改造了：

```text
back/app/api/v1/datasets.py
back/app/api/v1/proteins.py
back/app/api/v1/proteoforms.py
back/app/api/v1/prsms.py
back/app/api/v1/spectra.py
```

这些 API 现在从新库 7 表读取数据，但仍然返回旧前端需要的字段形状。

---

## 7. 数据库连接切换

后端配置已切换到新库：

```text
back/.env
back/.env.example
```

当前连接串：

```text
DATABASE_URL=postgresql+psycopg://postgres:1wsx3qaz@localhost:5432/Universal_Viewer
```

修改 `.env` 后必须重启后端服务，否则旧进程仍会连接旧数据库。

---

## 8. 已验证内容

已验证：

- fast 模式导入成功。
- fast 模式导入时间约 9 秒。
- 7 张表计数正确。
- `datasets`、`runs` 状态为 `READY`。
- protein 列表可读。
- proteoform 列表可读。
- PrSM 列表可读。
- PrSM 详情可通过 `detail_path` 懒加载完整 `prsm*.js`。
- MS2 谱图可从 `topfd/ms2_json` 读取。

---

## 9. 后续建议

后续可以继续做三件事：

1. 把当前兼容 API 逐步升级为真正的 Universal API，例如 `identification_matches` 页面。
2. 给 Bottom-up 数据新增 Adapter，写入 `peptides` 和 `entity_type = PEPTIDE` 的 `identification_matches`。
3. 如果需要更快的极限导入，可以进一步批量写入 `identification_matches`，减少逐条 SQL insert。
