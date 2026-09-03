# 双 Agent 真实联调输入输出记录

> 日期：2026-09-03（Asia/Shanghai）
> 目的：记录本地 Sol Agent 1、DeepSeek Agent 2、Sol 复核及 ZP 转换的真实输入输出，供后续开发与回归排查。
> 安全：API 密钥统一记为 `<redacted>`；记录中不包含 Authorization 头、RAW 内容、mzML 峰数组或 FASTA 正文。

## 1. 最终结论

- Agent 1：`gpt-5.6-sol`，`http://localhost:60049/v1`，本地只读工具模式，Moonshot Formula 禁用。
- Agent 2：`deepseek-v4-pro`，`https://api.deepseek.com`，配置未改变。
- Agent 1 v2：16 次工具执行记录，其中 15 次成功、1 次失败；生成合法 DatasetBlueprint。
- Agent 2 v2：状态 `READY`，操作 `convert_declared_mapping_to_zp`，8 个源角色、25 个字段映射、2 个 join；preflight 通过。
- Agent 1 复核 v2：`APPROVED`，issues=0，questions=0。
- ZP：生成 v3 文件，deep validation 与 Bottom-Up validation 均通过，issue_count=0。
- 后端全量测试：`545 passed, 12 skipped`。

## 2. 产物位置

- 运行目录：`E:\viewer\.tmp\双Agent真实联调-20260903`
- Agent 1 v2 Blueprint：`Agent1-Sol-Blueprint-v2.json`
- Agent 1 v2 工具轨迹：`Agent1-Sol-Blueprint-v2.trace.jsonl`
- Agent 2 v2 Plan：`Agent2-DeepSeek-Plan-v2.json`
- Agent 1 v2 Review：`Agent1-Sol-Review-v2.json`
- ZP：`single-sample-v3.zp`

`.tmp` 目录用于本机联调且通常不提交；本文件在后续清理 `.tmp` 后仍保留完整的 v2 模型输出。

## 3. Agent 1（Sol）输入

### 3.1 逻辑调用输入

```json
{
  "source_root": "E:\\viewer-agent\\maxquant\\maxquant-viz-data\\single-sample",
  "case_id": "live-agent1-single-sample",
  "analysis_category": "BOTTOM_UP",
  "requested_source_profile": "unknown scientific dataset",
  "format_details": "Independently inspect all available spectra, tables, metadata, FASTA, vendor provenance, cross-file relationships, established visualization practices, and missing data.",
  "user_messages": [],
  "source_manifest": "<见下方实际 manifest>",
  "zp_capabilities": "<运行时 build_zp_capabilities()；完整能力由代码注入>",
  "formula_tools": []
}
```

### 3.2 实际 source manifest

```json
{
  "schema_version": 1,
  "file_count": 10,
  "truncated": false,
  "files": [
    {
      "relative_path": ".viewer-derived/raw-conversion-logs/001-pxd000001.stderr.log",
      "size_bytes": 0,
      "suffix": ".log"
    },
    {
      "relative_path": ".viewer-derived/raw-conversion-logs/001-pxd000001.stdout.log",
      "size_bytes": 405,
      "suffix": ".log"
    },
    {
      "relative_path": ".viewer-derived/raw-converted-mzml/inputs/pxd000001-metadata.json",
      "size_bytes": 3031,
      "suffix": ".json"
    },
    {
      "relative_path": ".viewer-derived/raw-converted-mzml/inputs/pxd000001.mzML",
      "size_bytes": 78579772,
      "suffix": ".mzml"
    },
    {
      "relative_path": "evidence.txt",
      "size_bytes": 13592,
      "suffix": ".txt"
    },
    {
      "relative_path": "inputs/erwinia.fasta",
      "size_bytes": 1657668,
      "suffix": ".fasta"
    },
    {
      "relative_path": "inputs/pxd000001.raw",
      "size_bytes": 220475548,
      "suffix": ".raw"
    },
    {
      "relative_path": "mqpar.xml",
      "size_bytes": 32398,
      "suffix": ".xml"
    },
    {
      "relative_path": "proteinGroups.txt",
      "size_bytes": 6330,
      "suffix": ".txt"
    },
    {
      "relative_path": "summary.txt",
      "size_bytes": 1543,
      "suffix": ".txt"
    }
  ]
}
```

### 3.3 Chat Completions 外层协议

```json
{
  "model": "gpt-5.6-sol",
  "messages": [
    "system prompt",
    "user JSON",
    "后续 assistant/tool 消息"
  ],
  "tools": "AgentResearchToolbox.definitions()",
  "tool_choice": "required",
  "reasoning_effort": "high",
  "max_completion_tokens": 16384
}
```

最终 JSON 修复/收尾请求还会设置 `tools=[]`、`tool_choice="none"`、`reasoning_effort="low"`、`response_format={"type":"json_object"}`。

## 4. Agent 1（Sol）工具调用轨迹

```jsonl
{"round_no": 1, "call_id": "call_mquaLLBjInFUoKSJv9G2w53C", "tool_name": "inspect_source_tree", "arguments": {}, "status": "SUCCEEDED", "result_bytes": 1065, "result_summary": "result returned"}
{"round_no": 2, "call_id": "call_xMkFs45Dxg7fIN8VlOUF1WNp", "tool_name": "inspect_viewer_capabilities", "arguments": {}, "status": "SUCCEEDED", "result_bytes": 6244, "result_summary": "result returned"}
{"round_no": 2, "call_id": "call_F0gvkFDjaAmziysdrW4sDLfB", "tool_name": "inspect_json_file", "arguments": {"relative_path": ".viewer-derived/raw-converted-mzml/inputs/pxd000001-metadata.json"}, "status": "SUCCEEDED", "result_bytes": 3336, "result_summary": "result returned"}
{"round_no": 2, "call_id": "call_BsnPkj8uPWqh4V3o7z6KtImr", "tool_name": "inspect_mzml", "arguments": {"relative_path": ".viewer-derived/raw-converted-mzml/inputs/pxd000001.mzML"}, "status": "SUCCEEDED", "result_bytes": 1320, "result_summary": "result returned"}
{"round_no": 2, "call_id": "call_MQBHKs8apb0ubUZJqXZXOhRD", "tool_name": "inspect_fasta", "arguments": {"relative_path": "inputs/erwinia.fasta", "accessions": []}, "status": "SUCCEEDED", "result_bytes": 354, "result_summary": "result returned"}
{"round_no": 2, "call_id": "call_hF0ygBxJiFr7e9RX3vPmz4US", "tool_name": "inspect_xml_file", "arguments": {"relative_path": "mqpar.xml", "tag_names": ["rawFiles", "filePaths", "experiments", "fractions", "ptms", "paramGroupIndices", "referenceChannel", "fastaFiles", "fastaFilePath", "identifierParseRule", "descriptionParseRule", "fixedModifications", "variableModifications", "enzymes", "enzymeMode", "firstSearchTol", "mainSearchTol", "searchTolInPpm", "isotopeMatchTolInPpm", "minPeptideLength", "maxPeptideMass", "minUniquePeptides", "minRatioCount", "useDeltaScore", "separateLysines", "includeContaminants", "maxMissedCleavages"]}, "status": "SUCCEEDED", "result_bytes": 5646, "result_summary": "result returned"}
{"round_no": 2, "call_id": "call_HCYZrm68CoabAL7rr6ElQ2Gq", "tool_name": "inspect_tabular_file", "arguments": {"relative_path": "evidence.txt", "columns": []}, "status": "SUCCEEDED", "result_bytes": 14950, "result_summary": "result returned"}
{"round_no": 2, "call_id": "call_tWEZ9foNfFbu7R4ae2znIfiX", "tool_name": "inspect_tabular_file", "arguments": {"relative_path": "proteinGroups.txt", "columns": []}, "status": "SUCCEEDED", "result_bytes": 8783, "result_summary": "result returned"}
{"round_no": 2, "call_id": "call_DGljd0NKDpwEOyNyOjB29hlz", "tool_name": "inspect_tabular_file", "arguments": {"relative_path": "summary.txt", "columns": []}, "status": "SUCCEEDED", "result_bytes": 10099, "result_summary": "result returned"}
{"round_no": 2, "call_id": "call_6WuWBJk9j9s5rWvHX57N9w2R", "tool_name": "inspect_tabular_file", "arguments": {"relative_path": ".viewer-derived/raw-conversion-logs/001-pxd000001.stdout.log", "columns": []}, "status": "SUCCEEDED", "result_bytes": 820, "result_summary": "result returned"}
{"round_no": 2, "call_id": "call_dy270CdnOBRCzpza3z1Yh8cU", "tool_name": "inspect_tabular_file", "arguments": {"relative_path": ".viewer-derived/raw-conversion-logs/001-pxd000001.stderr.log", "columns": []}, "status": "FAILED", "result_bytes": 75, "result_summary": "{\"error\": \"ValueError: table header is empty or contains duplicate fields\"}"}
{"round_no": 2, "call_id": "call_oXlWYVAWU52EIIp2FMJtDCPA", "tool_name": "hash_source_file", "arguments": {"relative_path": "inputs/pxd000001.raw", "algorithm": "sha1"}, "status": "SUCCEEDED", "result_bytes": 141, "result_summary": "result returned"}
{"round_no": 2, "call_id": "call_FsGOzW9TBqk8S9lugR2idTIm", "tool_name": "hash_source_file", "arguments": {"relative_path": ".viewer-derived/raw-converted-mzml/inputs/pxd000001.mzML", "algorithm": "sha256"}, "status": "SUCCEEDED", "result_bytes": 202, "result_summary": "result returned"}
{"round_no": 3, "call_id": "call_k1WzGRpCSZzu6ox8JncFNdCk", "tool_name": "validate_fasta_relation", "arguments": {"table_path": "evidence.txt", "accession_field": "Proteins", "fasta_path": "inputs/erwinia.fasta", "split_semicolon": true}, "status": "SUCCEEDED", "result_bytes": 257, "result_summary": "result returned"}
{"round_no": 3, "call_id": "call_BKNf0NZEHAnOab4DK6GyoQWO", "tool_name": "validate_scan_relation", "arguments": {"table_path": "evidence.txt", "scan_field": "MS/MS scan number", "mzml_path": ".viewer-derived/raw-converted-mzml/inputs/pxd000001.mzML", "split_semicolon": false}, "status": "SUCCEEDED", "result_bytes": 245, "result_summary": "result returned"}
{"round_no": 3, "call_id": "call_NIcjQNOPc44WML8ByyNhdHxj", "tool_name": "validate_table_relation", "arguments": {"left_path": "proteinGroups.txt", "left_field": "Evidence IDs", "right_path": "evidence.txt", "right_field": "id", "split_semicolon": true}, "status": "SUCCEEDED", "result_bytes": 190, "result_summary": "result returned"}
```

其中一次 `inspect_tabular_file` 失败是模型请求了无效表格参数；错误已作为工具结果回传，其他必需检查均成功，最终 Blueprint 仍通过 Pydantic 校验。

## 5. Agent 1（Sol）完整 v2 输出

类型：`AgentResearchResult`。

```json
{
  "schema_version": 1,
  "provider": "openai-compatible",
  "model": "gpt-5.6-sol",
  "blueprint": {
    "schema_version": 1,
    "dataset_family": "Single-run MaxQuant DDA bottom-up proteomics",
    "source_profile": "maxquant_mzml_v1 single-sample bundle",
    "analysis_category": "BOTTOM_UP",
    "executive_summary": "Confirmed: one Thermo LTQ Orbitrap Velos run, converted to centroid mzML, with 7,534 spectra, 6,103 precursors, 35 evidence rows, 32 protein groups, MaxQuant parameters, summary QC, and a 4,499-record FASTA. All evidence scans match mzML scans; all protein-group evidence links resolve. Four contaminant accessions lack FASTA sequences. Inferred: this is a label-free, single-run DDA dataset. Preserve spectra, precursor links, BPC, source rows, search metadata, ordinary intensity, null-versus-zero state, and two provenance hashes. Fragment-ion annotations are unavailable.",
    "source_assets": [
      {
        "relative_path": ".viewer-derived/raw-converted-mzml/inputs/pxd000001.mzML",
        "role": "spectrum_source",
        "media_type": "application/mzml+xml",
        "content_summary": "Centroid positive-mode run with 1,431 MS1 and 6,103 HCD MS2 spectra, 3,949,930 peak pairs, 6,103 precursors, and one BPC.",
        "required_for_default_import": true,
        "evidence_ids": [
          "E1",
          "E2"
        ],
        "details": {
          "sha256": "e7b2afdc5a115038324bcb8814d59752d1a6a49cc3015cdb23e118b8046abad6"
        }
      },
      {
        "relative_path": "inputs/pxd000001.raw",
        "role": "vendor_raw",
        "media_type": "application/vnd.thermo.raw",
        "content_summary": "Original Thermo RAW retained only as hashed provenance; vendor bytes are not embedded in ZP.",
        "required_for_default_import": true,
        "evidence_ids": [
          "E3"
        ],
        "details": {
          "sha1": "5e050c8abc697891e2286271e062a8144518108a"
        }
      },
      {
        "relative_path": "evidence.txt",
        "role": "evidence",
        "media_type": "text/tab-separated-values",
        "content_summary": "MaxQuant evidence table with 35 rows and 70 physical columns covering PSM-level identity, scores, modifications, RT, scan links, proteins, and intensity.",
        "required_for_default_import": true,
        "evidence_ids": [
          "E4",
          "E8"
        ],
        "details": {
          "row_count": 35,
          "raw_file": "pxd000001"
        }
      },
      {
        "relative_path": "proteinGroups.txt",
        "role": "protein_groups",
        "media_type": "text/tab-separated-values",
        "content_summary": "MaxQuant protein-group table with 32 rows and 41 columns, including memberships, scores, q-values, coverage, contaminant flags, evidence links, and intensity.",
        "required_for_default_import": true,
        "evidence_ids": [
          "E5",
          "E9"
        ],
        "details": {
          "row_count": 32
        }
      },
      {
        "relative_path": "mqpar.xml",
        "role": "parameters",
        "media_type": "application/xml",
        "content_summary": "MaxQuant search configuration referencing erwinia.fasta, Trypsin/P-compatible settings, two missed cleavages, 4.5 ppm main tolerance, and contaminant inclusion.",
        "required_for_default_import": true,
        "evidence_ids": [
          "E6"
        ],
        "details": {
          "root": "MaxQuantParams"
        }
      },
      {
        "relative_path": "inputs/erwinia.fasta",
        "role": "fasta",
        "media_type": "chemical/seq-aa-fasta",
        "content_summary": "Protein sequence database with 4,499 records, 4,476 unique sequences, and 1,455,924 residues.",
        "required_for_default_import": true,
        "evidence_ids": [
          "E7",
          "E10"
        ],
        "details": {
          "record_count": 4499
        }
      },
      {
        "relative_path": "summary.txt",
        "role": "summary",
        "media_type": "text/tab-separated-values",
        "content_summary": "Optional MaxQuant run and total QC rows covering search vocabulary, submitted and identified MS/MS counts, peak statistics, and mass deviations.",
        "required_for_default_import": false,
        "evidence_ids": [
          "E11"
        ],
        "details": {
          "row_count": 2
        }
      },
      {
        "relative_path": ".viewer-derived/raw-converted-mzml/inputs/pxd000001-metadata.json",
        "role": "vendor_metadata",
        "media_type": "application/json",
        "content_summary": "Optional converted vendor metadata identifying an LTQ Orbitrap Velos, acquisition timing, sample D6, 7,534 scans, HCD, and a 60-minute runtime.",
        "required_for_default_import": false,
        "evidence_ids": [
          "E12"
        ],
        "details": {
          "instrument": "LTQ Orbitrap Velos"
        }
      },
      {
        "relative_path": ".viewer-derived/raw-conversion-logs/001-pxd000001.stdout.log",
        "role": "local_evidence",
        "media_type": "text/plain",
        "content_summary": "Conversion log reports processing 7,534 scans with zero errors and zero warnings; it is evidence only, not a binary input.",
        "required_for_default_import": false,
        "evidence_ids": [
          "E13"
        ],
        "details": {}
      },
      {
        "relative_path": ".viewer-derived/raw-conversion-logs/001-pxd000001.stderr.log",
        "role": "local_evidence",
        "media_type": "text/plain",
        "content_summary": "Empty conversion stderr log; evidence only and not a binary input.",
        "required_for_default_import": false,
        "evidence_ids": [
          "E13"
        ],
        "details": {}
      }
    ],
    "scientific_entities": [
      {
        "entity_name": "LC-MS/MS run",
        "scientific_level": "acquisition run",
        "description": "Single run named pxd000001 with approximately 60 minutes of positive-mode centroid acquisition.",
        "source_fields": [
          "Raw file",
          "Experiment"
        ],
        "identifiers": [
          "pxd000001"
        ],
        "relationships": [
          "contains spectra",
          "has search metadata",
          "derived from vendor RAW"
        ],
        "evidence_ids": [
          "E1",
          "E4",
          "E12"
        ],
        "details": {}
      },
      {
        "entity_name": "Spectrum",
        "scientific_level": "mass spectrum",
        "description": "MS1 or MS2 scan with native identity, scan number, retention time, polarity, representation, and m/z-intensity arrays.",
        "source_fields": [],
        "identifiers": [
          "scan_number",
          "native_id"
        ],
        "relationships": [
          "belongs to run",
          "MS2 may reference precursor",
          "MS2 may have evidence identification"
        ],
        "evidence_ids": [
          "E1",
          "E8"
        ],
        "details": {}
      },
      {
        "entity_name": "Precursor",
        "scientific_level": "selected ion",
        "description": "Selected precursor for each MS2 spectrum, preserving m/z, charge where declared, activation method, and collision energy.",
        "source_fields": [
          "Charge",
          "m/z",
          "MS/MS m/z"
        ],
        "identifiers": [],
        "relationships": [
          "belongs to MS2 spectrum",
          "may correspond to evidence row"
        ],
        "evidence_ids": [
          "E1",
          "E4"
        ],
        "details": {}
      },
      {
        "entity_name": "Chromatogram",
        "scientific_level": "run trace",
        "description": "Base-peak chromatogram with 7,534 time-intensity points; derived TIC views may be computed only if supported from preserved spectra.",
        "source_fields": [],
        "identifiers": [
          "BasePeak_0"
        ],
        "relationships": [
          "belongs to run"
        ],
        "evidence_ids": [
          "E1"
        ],
        "details": {}
      },
      {
        "entity_name": "Evidence identification",
        "scientific_level": "PSM/evidence row",
        "description": "MaxQuant evidence record linking peptide identity and scores to one MS2 scan while retaining every physical source column.",
        "source_fields": [
          "id",
          "Sequence",
          "Modified sequence",
          "Modifications",
          "Charge",
          "m/z",
          "Mass",
          "Retention time",
          "MS/MS scan number",
          "Score",
          "PEP",
          "Intensity"
        ],
        "identifiers": [
          "id"
        ],
        "relationships": [
          "links to one MS2 scan",
          "links to proteins and protein groups",
          "may carry intensity"
        ],
        "evidence_ids": [
          "E4",
          "E8"
        ],
        "details": {}
      },
      {
        "entity_name": "Peptide",
        "scientific_level": "peptide sequence",
        "description": "Unmodified sequence and modified form inferred from evidence rows; observed states are Unmodified and Oxidation (M).",
        "source_fields": [
          "Sequence",
          "Modified sequence",
          "Peptide ID",
          "Mod. peptide ID"
        ],
        "identifiers": [
          "Peptide ID",
          "Mod. peptide ID"
        ],
        "relationships": [
          "supported by evidence",
          "maps to proteins and protein groups"
        ],
        "evidence_ids": [
          "E4",
          "E14"
        ],
        "details": {}
      },
      {
        "entity_name": "Modification",
        "scientific_level": "peptide modification",
        "description": "Observed oxidation on methionine plus preserved search vocabulary for oxidation, protein N-terminal acetylation, and fixed carbamidomethylation.",
        "source_fields": [
          "Modifications",
          "Oxidation (M)",
          "Oxidation (M) Probabilities"
        ],
        "identifiers": [],
        "relationships": [
          "annotates peptide"
        ],
        "evidence_ids": [
          "E4",
          "E6",
          "E11",
          "E14"
        ],
        "details": {}
      },
      {
        "entity_name": "Protein",
        "scientific_level": "protein sequence/accession",
        "description": "Protein accession referenced by evidence or protein groups, optionally linked to a supplied FASTA sequence and description.",
        "source_fields": [
          "Proteins",
          "Protein IDs",
          "Majority protein IDs",
          "Fasta headers"
        ],
        "identifiers": [
          "FASTA identifier",
          "MaxQuant protein ID"
        ],
        "relationships": [
          "member of protein group",
          "contains identified peptides",
          "may link to FASTA record"
        ],
        "evidence_ids": [
          "E5",
          "E7",
          "E10"
        ],
        "details": {}
      },
      {
        "entity_name": "Protein group",
        "scientific_level": "protein inference group",
        "description": "MaxQuant protein group with protein membership, peptide support, q-value, score, coverage, contaminant state, evidence membership, and intensity.",
        "source_fields": [
          "id",
          "Protein IDs",
          "Majority protein IDs",
          "Q-value",
          "Score",
          "Intensity",
          "Peptide sequences",
          "Potential contaminant",
          "Evidence IDs"
        ],
        "identifiers": [
          "id"
        ],
        "relationships": [
          "contains proteins",
          "supported by evidence rows",
          "aggregates peptide sequences"
        ],
        "evidence_ids": [
          "E5",
          "E9"
        ],
        "details": {}
      },
      {
        "entity_name": "Quantification measurement",
        "scientific_level": "label-free abundance",
        "description": "Ordinary MaxQuant intensity at evidence and protein-group levels, preserving missing values separately from numeric zero.",
        "source_fields": [
          "Intensity",
          "Intensity pxd000001"
        ],
        "identifiers": [],
        "relationships": [
          "measures evidence or protein group"
        ],
        "evidence_ids": [
          "E4",
          "E5",
          "E15"
        ],
        "details": {}
      },
      {
        "entity_name": "Search and QC metadata",
        "scientific_level": "analysis provenance",
        "description": "MaxQuant parameters, summary statistics, instrument metadata, run labels, modification vocabulary, enzyme settings, and conversion status.",
        "source_fields": [],
        "identifiers": [],
        "relationships": [
          "describes run and identifications"
        ],
        "evidence_ids": [
          "E6",
          "E11",
          "E12",
          "E13"
        ],
        "details": {}
      }
    ],
    "binary_content": [
      {
        "logical_section": "global_meta",
        "content": "Dataset identity, BOTTOM_UP category, adapter flavor, source provenance, instrument metadata, search/QC metadata, expected counts, and source hashes.",
        "source_assets": [
          "mqpar.xml",
          "summary.txt",
          ".viewer-derived/raw-converted-mzml/inputs/pxd000001-metadata.json",
          "inputs/pxd000001.raw",
          ".viewer-derived/raw-converted-mzml/inputs/pxd000001.mzML"
        ],
        "required": true,
        "loss_policy": "Preserve available metadata and exact two hashes; do not embed RAW bytes or invent missing vendor fields.",
        "evidence_ids": [
          "E2",
          "E3",
          "E6",
          "E11",
          "E12"
        ],
        "details": {}
      },
      {
        "logical_section": "core_runs",
        "content": "One run named pxd000001 with source-file links, acquisition range, polarity, spectrum counts, and experiment name.",
        "source_assets": [
          ".viewer-derived/raw-converted-mzml/inputs/pxd000001.mzML",
          "evidence.txt"
        ],
        "required": true,
        "loss_policy": "Retain source run naming and mzML identity without normalization that breaks joins.",
        "evidence_ids": [
          "E1",
          "E4"
        ],
        "details": {}
      },
      {
        "logical_section": "core_spectra",
        "content": "All 7,534 mzML spectra with scan number, native ID, MS level, retention time, centroid status, polarity, and array references.",
        "source_assets": [
          ".viewer-derived/raw-converted-mzml/inputs/pxd000001.mzML"
        ],
        "required": true,
        "loss_policy": "No spectrum omission or downsampling; preserve source scan and native identifiers.",
        "evidence_ids": [
          "E1"
        ],
        "details": {}
      },
      {
        "logical_section": "core_precursors",
        "content": "All 6,103 selected precursors and their MS2 associations, charge where present, HCD activation, and collision energy.",
        "source_assets": [
          ".viewer-derived/raw-converted-mzml/inputs/pxd000001.mzML"
        ],
        "required": true,
        "loss_policy": "Preserve declared values and nulls; do not infer absent precursor attributes.",
        "evidence_ids": [
          "E1"
        ],
        "details": {}
      },
      {
        "logical_section": "core_chromatograms",
        "content": "The source base-peak chromatogram and its 7,534 time-intensity points.",
        "source_assets": [
          ".viewer-derived/raw-converted-mzml/inputs/pxd000001.mzML"
        ],
        "required": true,
        "loss_policy": "Preserve source BPC exactly; computed traces must remain distinguishable from source traces.",
        "evidence_ids": [
          "E1"
        ],
        "details": {}
      },
      {
        "logical_section": "arrays",
        "content": "All MS1 and MS2 m/z-intensity peak arrays totaling 3,949,930 pairs, plus chromatogram arrays.",
        "source_assets": [
          ".viewer-derived/raw-converted-mzml/inputs/pxd000001.mzML"
        ],
        "required": true,
        "loss_policy": "Lossless numeric preservation within trusted writer representation; no peak filtering.",
        "evidence_ids": [
          "E1"
        ],
        "details": {}
      },
      {
        "logical_section": "indexes",
        "content": "Indexes for run, scan number, native ID, MS level, retention time, precursor, evidence ID, peptide, protein, and protein-group navigation.",
        "source_assets": [
          ".viewer-derived/raw-converted-mzml/inputs/pxd000001.mzML",
          "evidence.txt",
          "proteinGroups.txt"
        ],
        "required": true,
        "loss_policy": "Indexes may optimize access but must not alter cardinality or source identifiers.",
        "evidence_ids": [
          "E1",
          "E4",
          "E5",
          "E8",
          "E9"
        ],
        "details": {}
      },
      {
        "logical_section": "string_pool",
        "content": "Deduplicated source strings for identifiers, sequences, modified sequences, protein accessions, headers, vocabulary, and source column names.",
        "source_assets": [
          "evidence.txt",
          "proteinGroups.txt",
          "mqpar.xml",
          "summary.txt",
          "inputs/erwinia.fasta"
        ],
        "required": true,
        "loss_policy": "Preserve exact spelling, case, separators, empty strings, and source-column labels.",
        "evidence_ids": [
          "E4",
          "E5",
          "E6",
          "E7",
          "E11"
        ],
        "details": {}
      },
      {
        "logical_section": "bottom_up_metadata",
        "content": "Search parameters, run summary, instrument metadata, conversion provenance, source rows, and dataset-level QC.",
        "source_assets": [
          "mqpar.xml",
          "summary.txt",
          ".viewer-derived/raw-converted-mzml/inputs/pxd000001-metadata.json",
          "evidence.txt",
          "proteinGroups.txt"
        ],
        "required": true,
        "loss_policy": "Preserve source metadata without asserting semantics for unverified fields.",
        "evidence_ids": [
          "E4",
          "E5",
          "E6",
          "E11",
          "E12"
        ],
        "details": {}
      },
      {
        "logical_section": "bottom_up_identifications",
        "content": "All 35 evidence rows, canonical required mappings, source scan/native-ID association, scores, PEP, and lossless source_fields.",
        "source_assets": [
          "evidence.txt",
          ".viewer-derived/raw-converted-mzml/inputs/pxd000001.mzML"
        ],
        "required": true,
        "loss_policy": "Preserve every physical column, NaN, empty, zero, and exact source row; RT converts minutes to seconds canonically.",
        "evidence_ids": [
          "E4",
          "E8"
        ],
        "details": {}
      },
      {
        "logical_section": "bottom_up_peptides",
        "content": "Distinct peptide and modified-peptide identities derived from evidence, retaining source peptide IDs and sequence strings.",
        "source_assets": [
          "evidence.txt"
        ],
        "required": true,
        "loss_policy": "Do not infer peptide attributes absent from evidence or reconstruct omitted MaxQuant tables.",
        "evidence_ids": [
          "E4",
          "E14"
        ],
        "details": {}
      },
      {
        "logical_section": "bottom_up_proteins",
        "content": "Referenced protein accessions with available FASTA sequence/header links and explicit unresolved contaminant accessions.",
        "source_assets": [
          "evidence.txt",
          "proteinGroups.txt",
          "inputs/erwinia.fasta"
        ],
        "required": true,
        "loss_policy": "Embed supplied FASTA content; preserve unmatched accessions without fabricated sequences.",
        "evidence_ids": [
          "E5",
          "E7",
          "E10"
        ],
        "details": {}
      },
      {
        "logical_section": "bottom_up_protein_groups",
        "content": "All 32 protein-group rows, required canonical fields, evidence memberships, and lossless source_fields.",
        "source_assets": [
          "proteinGroups.txt",
          "evidence.txt"
        ],
        "required": true,
        "loss_policy": "Preserve semicolon memberships, row order, exact values, and all physical columns.",
        "evidence_ids": [
          "E5",
          "E9"
        ],
        "details": {}
      },
      {
        "logical_section": "bottom_up_modifications",
        "content": "Observed modification states and localization text, plus search vocabulary from parameters and summary.",
        "source_assets": [
          "evidence.txt",
          "mqpar.xml",
          "summary.txt"
        ],
        "required": true,
        "loss_policy": "Represent only physically observed states as observations; retain other configured modifications as vocabulary.",
        "evidence_ids": [
          "E4",
          "E6",
          "E11",
          "E14"
        ],
        "details": {}
      },
      {
        "logical_section": "bottom_up_quantification",
        "content": "Evidence and protein-group ordinary Intensity values with run-specific protein-group intensity retained in source_fields.",
        "source_assets": [
          "evidence.txt",
          "proteinGroups.txt"
        ],
        "required": true,
        "loss_policy": "Preserve null versus zero and numeric values; do not infer normalization or substitute missing values.",
        "evidence_ids": [
          "E4",
          "E5",
          "E15"
        ],
        "details": {}
      }
    ],
    "visualizations": [
      {
        "view_id": "run-overview",
        "title": "Run overview and provenance",
        "purpose": "Summarize acquisition, conversion, search, counts, hashes, and known gaps.",
        "entities": [
          "LC-MS/MS run",
          "Search and QC metadata"
        ],
        "visual_components": [
          "count cards",
          "RT range",
          "instrument panel",
          "provenance panel",
          "gap badges"
        ],
        "interactions": [
          "open source metadata",
          "filter by MS level"
        ],
        "prerequisites": [],
        "limitations": [
          "Vendor RAW bytes are not viewable from ZP."
        ],
        "evidence_ids": [
          "E1",
          "E2",
          "E3",
          "E6",
          "E11",
          "E12"
        ],
        "details": {}
      },
      {
        "view_id": "chromatogram-explorer",
        "title": "Chromatogram and acquisition map",
        "purpose": "Navigate run intensity over time and inspect nearby MS1/MS2 scans.",
        "entities": [
          "Chromatogram",
          "Spectrum",
          "Precursor"
        ],
        "visual_components": [
          "BPC line",
          "MS2 event rug",
          "RT brush",
          "scan detail panel"
        ],
        "interactions": [
          "brush RT",
          "select scan",
          "zoom",
          "jump to identification"
        ],
        "prerequisites": [],
        "limitations": [],
        "evidence_ids": [
          "E1",
          "E8"
        ],
        "details": {}
      },
      {
        "view_id": "spectrum-browser",
        "title": "Spectrum browser",
        "purpose": "Inspect complete peak arrays and precursor context for any scan.",
        "entities": [
          "Spectrum",
          "Precursor",
          "Evidence identification"
        ],
        "visual_components": [
          "stick spectrum",
          "precursor card",
          "scan metadata",
          "identification panel"
        ],
        "interactions": [
          "search scan",
          "zoom m/z",
          "scale intensity",
          "navigate adjacent scans"
        ],
        "prerequisites": [],
        "limitations": [
          "No b/y fragment labels are available."
        ],
        "evidence_ids": [
          "E1",
          "E8"
        ],
        "details": {}
      },
      {
        "view_id": "identification-table",
        "title": "Evidence identifications",
        "purpose": "Explore all evidence rows while exposing canonical fields and original MaxQuant columns.",
        "entities": [
          "Evidence identification",
          "Peptide",
          "Modification",
          "Quantification measurement"
        ],
        "visual_components": [
          "sortable table",
          "column chooser",
          "score and PEP filters",
          "missing-value indicators"
        ],
        "interactions": [
          "filter",
          "sort",
          "export displayed rows",
          "open spectrum",
          "open protein group"
        ],
        "prerequisites": [],
        "limitations": [],
        "evidence_ids": [
          "E4",
          "E8",
          "E14",
          "E15"
        ],
        "details": {}
      },
      {
        "view_id": "score-qc",
        "title": "Identification score QC",
        "purpose": "Assess score, PEP, charge, mass error, retention time, and contaminant patterns.",
        "entities": [
          "Evidence identification",
          "Precursor"
        ],
        "visual_components": [
          "score histogram",
          "PEP plot",
          "mass-error scatter",
          "charge bars",
          "contaminant color"
        ],
        "interactions": [
          "brush and link",
          "toggle missing values",
          "select points"
        ],
        "prerequisites": [],
        "limitations": [
          "Only 35 evidence rows are present."
        ],
        "evidence_ids": [
          "E4"
        ],
        "details": {}
      },
      {
        "view_id": "peptide-modification",
        "title": "Peptides and modifications",
        "purpose": "Compare unmodified and oxidized peptides and inspect localization evidence.",
        "entities": [
          "Peptide",
          "Modification",
          "Evidence identification"
        ],
        "visual_components": [
          "peptide table",
          "modification counts",
          "sequence renderer",
          "localization text"
        ],
        "interactions": [
          "filter modification",
          "open supporting spectra",
          "group by sequence"
        ],
        "prerequisites": [],
        "limitations": [
          "Protein N-terminal acetylation is configured but not observed."
        ],
        "evidence_ids": [
          "E4",
          "E14"
        ],
        "details": {}
      },
      {
        "view_id": "protein-groups",
        "title": "Protein-group explorer",
        "purpose": "Navigate protein inference, peptide support, evidence membership, scores, coverage, and contaminant status.",
        "entities": [
          "Protein group",
          "Protein",
          "Peptide",
          "Evidence identification"
        ],
        "visual_components": [
          "group table",
          "membership graph",
          "coverage bar",
          "support counts"
        ],
        "interactions": [
          "expand group",
          "open evidence",
          "open FASTA record",
          "exclude contaminants"
        ],
        "prerequisites": [],
        "limitations": [],
        "evidence_ids": [
          "E5",
          "E9",
          "E10"
        ],
        "details": {}
      },
      {
        "view_id": "protein-coverage",
        "title": "Protein sequence coverage",
        "purpose": "Display identified peptide placement on supplied FASTA sequences when sequence links resolve.",
        "entities": [
          "Protein",
          "Peptide",
          "Protein group"
        ],
        "visual_components": [
          "sequence track",
          "peptide overlays",
          "oxidation marker",
          "coverage summary"
        ],
        "interactions": [
          "select accession",
          "highlight peptide",
          "switch group member"
        ],
        "prerequisites": [
          "Protein accession must match supplied FASTA."
        ],
        "limitations": [
          "Four contaminant accessions have no supplied sequence."
        ],
        "evidence_ids": [
          "E5",
          "E7",
          "E10"
        ],
        "details": {}
      },
      {
        "view_id": "quantification",
        "title": "Label-free intensity overview",
        "purpose": "Compare evidence and protein-group ordinary intensity while preserving missing and zero states.",
        "entities": [
          "Quantification measurement",
          "Evidence identification",
          "Protein group"
        ],
        "visual_components": [
          "log intensity plots",
          "rank chart",
          "missing-zero legend",
          "linked table"
        ],
        "interactions": [
          "toggle evidence/group level",
          "filter contaminants",
          "inspect source value"
        ],
        "prerequisites": [],
        "limitations": [
          "Single-run data do not support between-run differential analysis."
        ],
        "evidence_ids": [
          "E4",
          "E5",
          "E15"
        ],
        "details": {}
      },
      {
        "view_id": "search-qc",
        "title": "Search settings and summary QC",
        "purpose": "Present enzyme, modifications, tolerances, submission counts, identification rate, and mass-deviation metrics.",
        "entities": [
          "Search and QC metadata",
          "LC-MS/MS run"
        ],
        "visual_components": [
          "parameter sections",
          "QC cards",
          "submitted-vs-identified bars",
          "mass deviation panel"
        ],
        "interactions": [
          "compare parameter and summary values",
          "show source field"
        ],
        "prerequisites": [],
        "limitations": [],
        "evidence_ids": [
          "E6",
          "E11"
        ],
        "details": {}
      }
    ],
    "default_import": {
      "profile_name": "maxquant_mzml_v1 single-run bottom-up",
      "match_rules": [
        "Use adapter maxquant_mzml_v1 and analysis category BOTTOM_UP.",
        "Require one mzML run and exactly one evidence Raw file value.",
        "Require evidence.txt and proteinGroups.txt exact required columns.",
        "Require all evidence MS/MS scan numbers to resolve uniquely in same-run mzML MS2 spectra.",
        "Require all proteinGroups Evidence IDs to resolve to evidence id.",
        "Require one Thermo RAW, one mzML, one mqpar-referenced FASTA, and matching run stem.",
        "Require mzML-declared RAW SHA-1 to equal bundled RAW content.",
        "Observed evidence modifications must be limited to Unmodified and Oxidation (M)."
      ],
      "required_assets": [
        "evidence.txt",
        "proteinGroups.txt",
        "mqpar.xml",
        ".viewer-derived/raw-converted-mzml/inputs/pxd000001.mzML",
        "inputs/pxd000001.raw",
        "inputs/erwinia.fasta"
      ],
      "optional_assets": [
        "summary.txt",
        ".viewer-derived/raw-converted-mzml/inputs/pxd000001-metadata.json"
      ],
      "variability_rules": [
        "Paths may vary while role and validated relations remain stable.",
        "Preserve additional physical table columns as source_fields.",
        "Summary and vendor metadata may be absent.",
        "FASTA may contain duplicate sequences but identifiers must remain distinct."
      ],
      "editable_fields": [
        "dataset display name",
        "run display label",
        "sample display label",
        "optional notes"
      ],
      "unsafe_automatic_assumptions": [
        "Do not decode unsupported RAW fields.",
        "Do not infer missing fragment-ion annotations.",
        "Do not treat empty, NaN, and zero as equivalent.",
        "Do not fabricate contaminant FASTA sequences.",
        "Do not claim configured modifications were observed.",
        "Do not infer multi-run quantification or differential abundance."
      ]
    },
    "evidence": [
      {
        "evidence_id": "E1",
        "kind": "local_tool",
        "reference": "mzML inspection",
        "fact": "mzML has 7,534 centroid positive spectra: 1,431 MS1, 6,103 MS2, 6,103 precursors, 3,949,930 peak pairs, HCD at 45, and one 7,534-point BPC."
      },
      {
        "evidence_id": "E2",
        "kind": "local_tool",
        "reference": "mzML source hash",
        "fact": "Primary derived mzML SHA-256 is e7b2afdc5a115038324bcb8814d59752d1a6a49cc3015cdb23e118b8046abad6."
      },
      {
        "evidence_id": "E3",
        "kind": "local_tool",
        "reference": "vendor RAW source hash",
        "fact": "Original RAW SHA-1 is 5e050c8abc697891e2286271e062a8144518108a; size is 220,475,548 bytes."
      },
      {
        "evidence_id": "E4",
        "kind": "local_tool",
        "reference": "evidence.txt inspection",
        "fact": "evidence.txt has 35 rows and 70 columns; required adapter columns exist. It contains one Raw file and Experiment value: pxd000001."
      },
      {
        "evidence_id": "E5",
        "kind": "local_tool",
        "reference": "proteinGroups.txt inspection",
        "fact": "proteinGroups.txt has 32 rows and 41 columns; all required adapter columns exist."
      },
      {
        "evidence_id": "E6",
        "kind": "local_tool",
        "reference": "mqpar.xml inspection",
        "fact": "MaxQuantParams references erwinia.fasta, includes contaminants, uses two missed cleavages, 4.5 ppm main tolerance, minimum peptide length 7, and maximum mass 4,600."
      },
      {
        "evidence_id": "E7",
        "kind": "local_tool",
        "reference": "FASTA inspection",
        "fact": "erwinia.fasta has 4,499 unique identifiers, 4,476 unique sequences, 23 duplicate sequences, and 1,455,924 residues."
      },
      {
        "evidence_id": "E8",
        "kind": "local_tool",
        "reference": "evidence-to-mzML scan validation",
        "fact": "All 35 distinct evidence MS/MS scan numbers match mzML scan numbers; none are missing."
      },
      {
        "evidence_id": "E9",
        "kind": "local_tool",
        "reference": "protein-group-to-evidence validation",
        "fact": "All 35 distinct protein-group Evidence ID members match the 35 evidence ids."
      },
      {
        "evidence_id": "E10",
        "kind": "local_tool",
        "reference": "protein-to-FASTA validation",
        "fact": "Of 33 distinct evidence protein accessions, 29 match FASTA and four contaminant accessions do not."
      },
      {
        "evidence_id": "E11",
        "kind": "local_tool",
        "reference": "summary.txt inspection",
        "fact": "Summary reports Trypsin/P, specific digestion, oxidation and protein N-terminal acetylation as variable, carbamidomethyl C as fixed, 6,713 submitted MS/MS, and 25 identified."
      },
      {
        "evidence_id": "E12",
        "kind": "local_tool",
        "reference": "vendor metadata JSON inspection",
        "fact": "Metadata identifies an LTQ Orbitrap Velos, sample D6, 7,534 scans, HCD, approximately 60 minutes, and source creation date 2010-06-15."
      },
      {
        "evidence_id": "E13",
        "kind": "local_tool",
        "reference": "conversion logs inspection",
        "fact": "stdout reports 7,534 scans processed with zero errors and warnings; stderr is empty."
      },
      {
        "evidence_id": "E14",
        "kind": "local_tool",
        "reference": "evidence modification columns",
        "fact": "Observed Modifications values are Unmodified and Oxidation (M); one oxidized evidence row exists, while Acetyl (Protein N-term) counts are all zero."
      },
      {
        "evidence_id": "E15",
        "kind": "local_tool",
        "reference": "quantification columns inspection",
        "fact": "Evidence Intensity is numeric in 20 rows and empty in 15; protein-group Intensity is numeric in all 32 rows and includes zeros."
      },
      {
        "evidence_id": "E16",
        "kind": "inference",
        "reference": "cross-file profile interpretation",
        "fact": "One run, multiplicity 1, ordinary Intensity fields, and scan-linked MS2 evidence support a single-run label-free DDA interpretation."
      },
      {
        "evidence_id": "E17",
        "kind": "user_input",
        "reference": "viewer_zp_capabilities",
        "fact": "The advertised maxquant_mzml_v1 adapter defines required roles, mappings, joins, preserves, count keys, transforms, and first-version limits for ZP v3."
      }
    ],
    "gaps": [
      {
        "gap": "msms.txt is absent.",
        "consequence": "No source b/y fragment matches or annotated fragment series can be preserved.",
        "resolution": "Add a supported msms.txt role in a future adapter; until then show unannotated spectra."
      },
      {
        "gap": "Four contaminant accessions lack supplied FASTA sequences.",
        "consequence": "Their sequence coverage and peptide placement cannot be rendered.",
        "resolution": "Supply the exact contaminant FASTA used by MaxQuant without replacing the existing database."
      },
      {
        "gap": "Vendor RAW bytes are not embedded by the adapter.",
        "consequence": "ZP cannot reproduce unsupported vendor-only fields or act as a RAW archive.",
        "resolution": "Retain the original RAW externally and verify it using the stored SHA-1."
      },
      {
        "gap": "No peptides.txt or msms.txt table is supplied.",
        "consequence": "Peptide entities must be derived from evidence and omitted table-specific fields remain unavailable.",
        "resolution": "Provide those tables only after an advertised adapter role supports them."
      },
      {
        "gap": "Taxonomy fields are empty or unresolved.",
        "consequence": "Taxonomic visualization and confident organism-level summaries are unavailable.",
        "resolution": "Supply validated taxonomy annotations or a supported annotated FASTA."
      },
      {
        "gap": "Only one run is present.",
        "consequence": "Between-run alignment, replicate QC, differential abundance, and cohort views are unsupported.",
        "resolution": "Use a future multi-run adapter with validated run associations."
      },
      {
        "gap": "No authoritative web sources were verified in this session.",
        "consequence": "Visualization practices are based on local evidence and established general conventions without citations.",
        "resolution": "Perform a separate standards review when web research tools are available."
      }
    ],
    "citations": [],
    "acceptance_criteria": [
      "Importer selects maxquant_mzml_v1 and produces target ZP format version 3.",
      "Exactly one run named pxd000001 is created.",
      "Expected counts equal spectra 7,534; precursors 6,103; evidence_rows 35; protein_groups 32.",
      "MS-level counts equal 1,431 MS1 and 6,103 MS2.",
      "All 3,949,930 mzML peak pairs and all source BPC points are retained.",
      "All 35 evidence scan links resolve to unique same-run MS2 spectra.",
      "All protein-group Evidence ID members resolve to evidence ids.",
      "Every required canonical mapping uses the declared transform only.",
      "Retention time canonical values equal source minutes multiplied by 60.",
      "All physical evidence and protein-group columns are retained in source_fields.",
      "Empty, NaN, and numeric zero remain distinguishable.",
      "Observed modification states are only Unmodified and Oxidation (M).",
      "Configured Acetyl (Protein N-term) is metadata, not an observed modification.",
      "All 4,499 FASTA records and identifiers are preserved; unmatched contaminant accessions remain explicit.",
      "RAW SHA-1 and mzML SHA-256 equal the recorded digests.",
      "RAW content is not embedded in ZP.",
      "Spectrum view can retrieve any scan by scan number and display complete arrays.",
      "Protein-group view can navigate to every linked evidence row.",
      "Views do not display fragment-ion labels unless fragment matches exist.",
      "No file outside adapter required or optional roles becomes a required binary input."
    ],
    "assumptions": [
      "The supplied mzML is the primary derived spectrum file.",
      "The adapter can obtain and verify the mzML-declared RAW SHA-1 during import.",
      "Single-value Raw file and Experiment fields identify the same run.",
      "Label-free DDA is an inference, not an explicit vendor declaration."
    ]
  },
  "trace": [
    {
      "round_no": 1,
      "call_id": "call_mquaLLBjInFUoKSJv9G2w53C",
      "tool_name": "inspect_source_tree",
      "arguments": {},
      "status": "SUCCEEDED",
      "result_bytes": 1065,
      "result_summary": "result returned"
    },
    {
      "round_no": 2,
      "call_id": "call_xMkFs45Dxg7fIN8VlOUF1WNp",
      "tool_name": "inspect_viewer_capabilities",
      "arguments": {},
      "status": "SUCCEEDED",
      "result_bytes": 6244,
      "result_summary": "result returned"
    },
    {
      "round_no": 2,
      "call_id": "call_F0gvkFDjaAmziysdrW4sDLfB",
      "tool_name": "inspect_json_file",
      "arguments": {
        "relative_path": ".viewer-derived/raw-converted-mzml/inputs/pxd000001-metadata.json"
      },
      "status": "SUCCEEDED",
      "result_bytes": 3336,
      "result_summary": "result returned"
    },
    {
      "round_no": 2,
      "call_id": "call_BsnPkj8uPWqh4V3o7z6KtImr",
      "tool_name": "inspect_mzml",
      "arguments": {
        "relative_path": ".viewer-derived/raw-converted-mzml/inputs/pxd000001.mzML"
      },
      "status": "SUCCEEDED",
      "result_bytes": 1320,
      "result_summary": "result returned"
    },
    {
      "round_no": 2,
      "call_id": "call_MQBHKs8apb0ubUZJqXZXOhRD",
      "tool_name": "inspect_fasta",
      "arguments": {
        "relative_path": "inputs/erwinia.fasta",
        "accessions": []
      },
      "status": "SUCCEEDED",
      "result_bytes": 354,
      "result_summary": "result returned"
    },
    {
      "round_no": 2,
      "call_id": "call_hF0ygBxJiFr7e9RX3vPmz4US",
      "tool_name": "inspect_xml_file",
      "arguments": {
        "relative_path": "mqpar.xml",
        "tag_names": [
          "rawFiles",
          "filePaths",
          "experiments",
          "fractions",
          "ptms",
          "paramGroupIndices",
          "referenceChannel",
          "fastaFiles",
          "fastaFilePath",
          "identifierParseRule",
          "descriptionParseRule",
          "fixedModifications",
          "variableModifications",
          "enzymes",
          "enzymeMode",
          "firstSearchTol",
          "mainSearchTol",
          "searchTolInPpm",
          "isotopeMatchTolInPpm",
          "minPeptideLength",
          "maxPeptideMass",
          "minUniquePeptides",
          "minRatioCount",
          "useDeltaScore",
          "separateLysines",
          "includeContaminants",
          "maxMissedCleavages"
        ]
      },
      "status": "SUCCEEDED",
      "result_bytes": 5646,
      "result_summary": "result returned"
    },
    {
      "round_no": 2,
      "call_id": "call_HCYZrm68CoabAL7rr6ElQ2Gq",
      "tool_name": "inspect_tabular_file",
      "arguments": {
        "relative_path": "evidence.txt",
        "columns": []
      },
      "status": "SUCCEEDED",
      "result_bytes": 14950,
      "result_summary": "result returned"
    },
    {
      "round_no": 2,
      "call_id": "call_tWEZ9foNfFbu7R4ae2znIfiX",
      "tool_name": "inspect_tabular_file",
      "arguments": {
        "relative_path": "proteinGroups.txt",
        "columns": []
      },
      "status": "SUCCEEDED",
      "result_bytes": 8783,
      "result_summary": "result returned"
    },
    {
      "round_no": 2,
      "call_id": "call_DGljd0NKDpwEOyNyOjB29hlz",
      "tool_name": "inspect_tabular_file",
      "arguments": {
        "relative_path": "summary.txt",
        "columns": []
      },
      "status": "SUCCEEDED",
      "result_bytes": 10099,
      "result_summary": "result returned"
    },
    {
      "round_no": 2,
      "call_id": "call_6WuWBJk9j9s5rWvHX57N9w2R",
      "tool_name": "inspect_tabular_file",
      "arguments": {
        "relative_path": ".viewer-derived/raw-conversion-logs/001-pxd000001.stdout.log",
        "columns": []
      },
      "status": "SUCCEEDED",
      "result_bytes": 820,
      "result_summary": "result returned"
    },
    {
      "round_no": 2,
      "call_id": "call_dy270CdnOBRCzpza3z1Yh8cU",
      "tool_name": "inspect_tabular_file",
      "arguments": {
        "relative_path": ".viewer-derived/raw-conversion-logs/001-pxd000001.stderr.log",
        "columns": []
      },
      "status": "FAILED",
      "result_bytes": 75,
      "result_summary": "{\"error\": \"ValueError: table header is empty or contains duplicate fields\"}"
    },
    {
      "round_no": 2,
      "call_id": "call_oXlWYVAWU52EIIp2FMJtDCPA",
      "tool_name": "hash_source_file",
      "arguments": {
        "relative_path": "inputs/pxd000001.raw",
        "algorithm": "sha1"
      },
      "status": "SUCCEEDED",
      "result_bytes": 141,
      "result_summary": "result returned"
    },
    {
      "round_no": 2,
      "call_id": "call_FsGOzW9TBqk8S9lugR2idTIm",
      "tool_name": "hash_source_file",
      "arguments": {
        "relative_path": ".viewer-derived/raw-converted-mzml/inputs/pxd000001.mzML",
        "algorithm": "sha256"
      },
      "status": "SUCCEEDED",
      "result_bytes": 202,
      "result_summary": "result returned"
    },
    {
      "round_no": 3,
      "call_id": "call_k1WzGRpCSZzu6ox8JncFNdCk",
      "tool_name": "validate_fasta_relation",
      "arguments": {
        "table_path": "evidence.txt",
        "accession_field": "Proteins",
        "fasta_path": "inputs/erwinia.fasta",
        "split_semicolon": true
      },
      "status": "SUCCEEDED",
      "result_bytes": 257,
      "result_summary": "result returned"
    },
    {
      "round_no": 3,
      "call_id": "call_BKNf0NZEHAnOab4DK6GyoQWO",
      "tool_name": "validate_scan_relation",
      "arguments": {
        "table_path": "evidence.txt",
        "scan_field": "MS/MS scan number",
        "mzml_path": ".viewer-derived/raw-converted-mzml/inputs/pxd000001.mzML",
        "split_semicolon": false
      },
      "status": "SUCCEEDED",
      "result_bytes": 245,
      "result_summary": "result returned"
    },
    {
      "round_no": 3,
      "call_id": "call_NIcjQNOPc44WML8ByyNhdHxj",
      "tool_name": "validate_table_relation",
      "arguments": {
        "left_path": "proteinGroups.txt",
        "left_field": "Evidence IDs",
        "right_path": "evidence.txt",
        "right_field": "id",
        "split_semicolon": true
      },
      "status": "SUCCEEDED",
      "result_bytes": 190,
      "result_summary": "result returned"
    }
  ],
  "local_tool_calls": 15,
  "web_search_calls": 0,
  "fetch_calls": 0
}
```

## 6. Agent 2（DeepSeek）输入

### 6.1 逻辑调用输入

```json
{
  "context": {
    "case_id": "live-deepseek-single-sample",
    "context_revision": 1,
    "source_root": "E:\\viewer-agent\\maxquant\\maxquant-viz-data\\single-sample",
    "analysis_category": "BOTTOM_UP",
    "requested_source_profile": "maxquant_mzml_v1 single-sample bundle",
    "format_details": "Implement the approved Agent 1 DatasetBlueprint without dropping content.",
    "dataset_fingerprint": "00000000000000000000000000000000",
    "source_summary": "<与上方 manifest 相同，另含有界 samples>",
    "user_messages": []
  },
  "strategy": {
    "schema_version": 3,
    "decision": "BLUEPRINT_READY",
    "analysis_category": "BOTTOM_UP",
    "proposed_source_profile": "maxquant_mzml_v1 single-sample bundle",
    "agent_research_result": "<即下方完整 Agent 1 输出>"
  },
  "zp_capabilities": "<运行时 build_zp_capabilities()>",
  "candidate_json_schema": "<AgentCandidatePlan.model_json_schema()>"
}
```

### 6.2 Chat Completions 外层协议

```json
{
  "model": "deepseek-v4-pro",
  "messages": [
    "system prompt",
    "user JSON"
  ],
  "response_format": {
    "type": "json_object"
  },
  "max_completion_tokens": 8192,
  "repair_loop": "最多 3 次；schema 或 deterministic preflight 失败会把结构化 repair_feedback 加入下一次输入"
}
```

## 7. Agent 2（DeepSeek）完整 v2 输出

类型：`AgentCandidatePlan`。

```json
{
  "schema_version": 2,
  "status": "READY",
  "analysis_category": "BOTTOM_UP",
  "source_profile": "maxquant_mzml_v1 single-sample bundle",
  "binary_operation": "convert_declared_mapping_to_zp",
  "zp_conversion_plan": {
    "relative_source": ".",
    "target_format_version": 3,
    "mapping_plan": {
      "schema_version": 1,
      "adapter_id": "maxquant_mzml_v1",
      "source_format": "maxquant_mzml_bundle",
      "target_format_version": 3,
      "source_files": [
        {
          "relative_path": "evidence.txt",
          "role": "evidence",
          "source_format": "tsv",
          "required": true,
          "required_columns": [
            "Raw file",
            "Experiment",
            "Sequence",
            "Modifications",
            "Modified sequence",
            "Charge",
            "m/z",
            "Mass",
            "Retention time",
            "MS/MS scan number",
            "Proteins",
            "id",
            "Protein group IDs",
            "Score",
            "PEP",
            "Intensity"
          ]
        },
        {
          "relative_path": "proteinGroups.txt",
          "role": "protein_groups",
          "source_format": "tsv",
          "required": true,
          "required_columns": [
            "Protein IDs",
            "Majority protein IDs",
            "Q-value",
            "Score",
            "Intensity",
            "Peptide sequences",
            "Potential contaminant",
            "id",
            "Evidence IDs"
          ]
        },
        {
          "relative_path": "mqpar.xml",
          "role": "parameters",
          "source_format": "xml",
          "required": true,
          "required_columns": []
        },
        {
          "relative_path": ".viewer-derived/raw-converted-mzml/inputs/pxd000001.mzML",
          "role": "spectrum_source",
          "source_format": "mzml",
          "required": true,
          "required_columns": []
        },
        {
          "relative_path": "inputs/pxd000001.raw",
          "role": "vendor_raw",
          "source_format": "vendor",
          "required": true,
          "required_columns": []
        },
        {
          "relative_path": "inputs/erwinia.fasta",
          "role": "fasta",
          "source_format": "fasta",
          "required": true,
          "required_columns": []
        },
        {
          "relative_path": "summary.txt",
          "role": "summary",
          "source_format": "tsv",
          "required": false,
          "required_columns": []
        },
        {
          "relative_path": ".viewer-derived/raw-converted-mzml/inputs/pxd000001-metadata.json",
          "role": "vendor_metadata",
          "source_format": "json",
          "required": false,
          "required_columns": []
        }
      ],
      "field_mappings": [
        {
          "source_file": "evidence.txt",
          "source_field": "id",
          "target_entity": "identification",
          "target_field": "evidence_id",
          "value_kind": "integer",
          "required": true,
          "unit": null,
          "transform": "identity",
          "evidence": "E4"
        },
        {
          "source_file": "evidence.txt",
          "source_field": "Raw file",
          "target_entity": "run",
          "target_field": "raw_file",
          "value_kind": "string",
          "required": true,
          "unit": null,
          "transform": "identity",
          "evidence": "E4"
        },
        {
          "source_file": "evidence.txt",
          "source_field": "Experiment",
          "target_entity": "metadata",
          "target_field": "experiment_name",
          "value_kind": "string",
          "required": true,
          "unit": null,
          "transform": "identity",
          "evidence": "E4"
        },
        {
          "source_file": "evidence.txt",
          "source_field": "Sequence",
          "target_entity": "identification",
          "target_field": "sequence",
          "value_kind": "string",
          "required": true,
          "unit": null,
          "transform": "identity",
          "evidence": "E4"
        },
        {
          "source_file": "evidence.txt",
          "source_field": "Modifications",
          "target_entity": "identification",
          "target_field": "modifications",
          "value_kind": "string",
          "required": true,
          "unit": null,
          "transform": "identity",
          "evidence": "E4"
        },
        {
          "source_file": "evidence.txt",
          "source_field": "Modified sequence",
          "target_entity": "identification",
          "target_field": "modified_sequence",
          "value_kind": "string",
          "required": true,
          "unit": null,
          "transform": "identity",
          "evidence": "E4"
        },
        {
          "source_file": "evidence.txt",
          "source_field": "Charge",
          "target_entity": "identification",
          "target_field": "charge",
          "value_kind": "integer",
          "required": true,
          "unit": null,
          "transform": "identity",
          "evidence": "E4"
        },
        {
          "source_file": "evidence.txt",
          "source_field": "m/z",
          "target_entity": "identification",
          "target_field": "mz",
          "value_kind": "float",
          "required": true,
          "unit": null,
          "transform": "identity",
          "evidence": "E4"
        },
        {
          "source_file": "evidence.txt",
          "source_field": "Mass",
          "target_entity": "identification",
          "target_field": "mass",
          "value_kind": "float",
          "required": true,
          "unit": null,
          "transform": "identity",
          "evidence": "E4"
        },
        {
          "source_file": "evidence.txt",
          "source_field": "Retention time",
          "target_entity": "identification",
          "target_field": "retention_time_seconds",
          "value_kind": "float",
          "required": true,
          "unit": null,
          "transform": "minute_to_second",
          "evidence": "E4"
        },
        {
          "source_file": "evidence.txt",
          "source_field": "MS/MS scan number",
          "target_entity": "identification",
          "target_field": "msms_scan_number",
          "value_kind": "integer",
          "required": true,
          "unit": null,
          "transform": "identity",
          "evidence": "E8"
        },
        {
          "source_file": "evidence.txt",
          "source_field": "Proteins",
          "target_entity": "identification",
          "target_field": "protein_ids",
          "value_kind": "string",
          "required": true,
          "unit": null,
          "transform": "semicolon_split",
          "evidence": "E4"
        },
        {
          "source_file": "evidence.txt",
          "source_field": "Protein group IDs",
          "target_entity": "identification",
          "target_field": "protein_group_ids",
          "value_kind": "string",
          "required": true,
          "unit": null,
          "transform": "semicolon_split",
          "evidence": "E4"
        },
        {
          "source_file": "evidence.txt",
          "source_field": "Score",
          "target_entity": "identification",
          "target_field": "score",
          "value_kind": "float",
          "required": true,
          "unit": null,
          "transform": "identity",
          "evidence": "E4"
        },
        {
          "source_file": "evidence.txt",
          "source_field": "PEP",
          "target_entity": "identification",
          "target_field": "pep",
          "value_kind": "float",
          "required": true,
          "unit": null,
          "transform": "identity",
          "evidence": "E4"
        },
        {
          "source_file": "evidence.txt",
          "source_field": "Intensity",
          "target_entity": "quantification",
          "target_field": "evidence_intensity",
          "value_kind": "float",
          "required": true,
          "unit": null,
          "transform": "identity",
          "evidence": "E15"
        },
        {
          "source_file": "proteinGroups.txt",
          "source_field": "id",
          "target_entity": "protein_group",
          "target_field": "protein_group_id",
          "value_kind": "integer",
          "required": true,
          "unit": null,
          "transform": "identity",
          "evidence": "E5"
        },
        {
          "source_file": "proteinGroups.txt",
          "source_field": "Protein IDs",
          "target_entity": "protein_group",
          "target_field": "protein_ids",
          "value_kind": "string",
          "required": true,
          "unit": null,
          "transform": "semicolon_split",
          "evidence": "E5"
        },
        {
          "source_file": "proteinGroups.txt",
          "source_field": "Majority protein IDs",
          "target_entity": "protein_group",
          "target_field": "majority_protein_ids",
          "value_kind": "string",
          "required": true,
          "unit": null,
          "transform": "semicolon_split",
          "evidence": "E5"
        },
        {
          "source_file": "proteinGroups.txt",
          "source_field": "Q-value",
          "target_entity": "protein_group",
          "target_field": "q_value",
          "value_kind": "float",
          "required": true,
          "unit": null,
          "transform": "identity",
          "evidence": "E5"
        },
        {
          "source_file": "proteinGroups.txt",
          "source_field": "Score",
          "target_entity": "protein_group",
          "target_field": "score",
          "value_kind": "float",
          "required": true,
          "unit": null,
          "transform": "identity",
          "evidence": "E5"
        },
        {
          "source_file": "proteinGroups.txt",
          "source_field": "Intensity",
          "target_entity": "quantification",
          "target_field": "protein_group_intensity",
          "value_kind": "float",
          "required": true,
          "unit": null,
          "transform": "identity",
          "evidence": "E15"
        },
        {
          "source_file": "proteinGroups.txt",
          "source_field": "Peptide sequences",
          "target_entity": "protein_group",
          "target_field": "peptide_sequences",
          "value_kind": "string",
          "required": true,
          "unit": null,
          "transform": "semicolon_split",
          "evidence": "E5"
        },
        {
          "source_file": "proteinGroups.txt",
          "source_field": "Potential contaminant",
          "target_entity": "protein_group",
          "target_field": "potential_contaminant",
          "value_kind": "boolean",
          "required": true,
          "unit": null,
          "transform": "plus_marker_to_bool",
          "evidence": "E5"
        },
        {
          "source_file": "proteinGroups.txt",
          "source_field": "Evidence IDs",
          "target_entity": "protein_group",
          "target_field": "evidence_ids",
          "value_kind": "string",
          "required": true,
          "unit": null,
          "transform": "semicolon_split",
          "evidence": "E9"
        }
      ],
      "join_rules": [
        {
          "left_file": "evidence.txt",
          "left_field": "MS/MS scan number",
          "right_file": ".viewer-derived/raw-converted-mzml/inputs/pxd000001.mzML",
          "right_field": "scan_number",
          "cardinality": "many_to_one",
          "transform": "identity"
        },
        {
          "left_file": "proteinGroups.txt",
          "left_field": "Evidence IDs",
          "right_file": "evidence.txt",
          "right_field": "id",
          "cardinality": "many_to_one",
          "transform": "semicolon_membership"
        }
      ],
      "row_policy": "preserve_all_rows",
      "unmapped_fields": {},
      "expected_counts": {
        "spectra": 7534,
        "precursors": 6103,
        "evidence_rows": 35,
        "protein_groups": 32
      },
      "evidence": [
        {
          "source_file": "evidence.txt",
          "source_field": null,
          "fact": "evidence.txt has 35 rows and 70 columns; required adapter columns exist and all 35 evidence scan numbers resolve to mzML MS2 scans."
        },
        {
          "source_file": "proteinGroups.txt",
          "source_field": null,
          "fact": "proteinGroups.txt has 32 rows and 41 columns; required adapter columns exist and all Evidence IDs resolve to evidence ids."
        },
        {
          "source_file": ".viewer-derived/raw-converted-mzml/inputs/pxd000001.mzML",
          "source_field": null,
          "fact": "mzML has 7,534 centroid positive spectra, 6,103 precursors, and 3,949,930 peak pairs."
        },
        {
          "source_file": "inputs/pxd000001.raw",
          "source_field": null,
          "fact": "Original RAW SHA-1 is 5e050c8abc697891e2286271e062a8144518108a; vendor bytes are not embedded."
        },
        {
          "source_file": "inputs/erwinia.fasta",
          "source_field": null,
          "fact": "erwinia.fasta has 4,499 identifiers and 4,476 unique sequences; 29 of 33 distinct evidence protein accessions match."
        },
        {
          "source_file": "mqpar.xml",
          "source_field": null,
          "fact": "MaxQuantParams references erwinia.fasta, Trypsin/P-compatible settings, two missed cleavages, and 4.5 ppm main tolerance."
        },
        {
          "source_file": "summary.txt",
          "source_field": null,
          "fact": "Summary reports Trypsin/P, 6,713 submitted MS/MS, and 25 identified."
        },
        {
          "source_file": ".viewer-derived/raw-converted-mzml/inputs/pxd000001-metadata.json",
          "source_field": null,
          "fact": "Vendor metadata identifies an LTQ Orbitrap Velos, sample D6, HCD, and 7,534 scans."
        }
      ]
    }
  },
  "questions": []
}
```

## 8. Agent 1（Sol）复核输入

```json
{
  "case_id": "live-agent1-review-single-sample",
  "context_revision": 1,
  "dataset_blueprint": "<下方完整 Agent 1 输出中的 blueprint>",
  "candidate": "<下方完整 Agent 2 输出>",
  "candidate_json_schema": "<AgentCandidatePlan.model_json_schema()>",
  "deterministic_preflight": {
    "schema_version": 1,
    "status": "PASSED",
    "binary_operation": "convert_declared_mapping_to_zp",
    "mapping_adapter": "maxquant_mzml_v1",
    "source_type": "real_blueprint_bottom_up_bundle",
    "detected_roles": [
      "evidence",
      "fasta",
      "parameters",
      "protein_groups",
      "spectrum_source",
      "summary",
      "vendor_metadata",
      "vendor_raw"
    ]
  },
  "zp_capabilities": "<运行时 build_zp_capabilities()>",
  "review_json_schema": "<AgentPlanReview.model_json_schema()>"
}
```

复核请求使用本地 Sol、JSON mode，并明确候选计划是窄执行合同；可视化设计和超出 `expected_count_keys` 的下游语义验收不要求在 CandidatePlan 中重复声明。

## 9. Agent 1（Sol）完整 v2 复核输出

类型：`AgentPlanReview`。

```json
{
  "schema_version": 1,
  "status": "APPROVED",
  "issues": [],
  "questions": [],
  "evidence": [
    "Deterministic preflight passed for convert_declared_mapping_to_zp with adapter maxquant_mzml_v1 and all required and optional detected roles.",
    "Candidate uses target ZP format version 3, analysis category BOTTOM_UP, source format maxquant_mzml_bundle, and the Viewer-advertised mapping adapter.",
    "All six required adapter roles are declared with matching source formats and exact required columns; supported summary and vendor_metadata roles remain optional.",
    "All 25 advertised required canonical field mappings are present with matching source fields, target entities, target fields, value kinds, and transforms, including minute_to_second for retention time.",
    "Both advertised required joins are declared: evidence scan number to mzML scan_number and protein-group Evidence IDs to evidence id via semicolon membership.",
    "The row policy preserves all rows, and unmapped_fields does not introduce guessed columns; the adapter preserves remaining physical table columns in source_fields.",
    "Expected counts use only advertised keys and match the Blueprint: 7,534 spectra, 6,103 precursors, 35 evidence rows, and 32 protein groups.",
    "The plan includes mzML, RAW provenance, FASTA, MaxQuant parameters, evidence, protein groups, and supported optional metadata without adding unsupported required inputs.",
    "The candidate does not request RAW-byte embedding, fragment-ion fabrication, modification inference, or unsupported binary handling."
  ]
}
```

## 10. ZP 实际验收输入输出

输入：

```json
{
  "source": "E:\\viewer-agent\\maxquant\\maxquant-viz-data\\single-sample",
  "output": "E:\\viewer\\.tmp\\双Agent真实联调-20260903\\single-sample-v3.zp",
  "format_version": 3,
  "adapter": "maxquant_mzml_v1"
}
```

输出摘要：

```json
{
  "status": "PASSED",
  "source_type": "real_blueprint_bottom_up_bundle",
  "output": "E:\\viewer\\.tmp\\双Agent真实联调-20260903\\single-sample-v3.zp",
  "output_size": 41694812,
  "output_sha256": "0756a16faba18076c76665b32fba70d1bca67571d403af1ef7a17c703a916bca",
  "counts": {
    "spectra": 7534,
    "ms1": 1431,
    "ms2": 6103,
    "precursors": 6103,
    "peak_pairs": 3949930,
    "chromatograms": 1,
    "bpc_points": 7534,
    "identifications": 35,
    "peptides": 32,
    "proteins": 33,
    "protein_groups": 32,
    "modifications": 1,
    "quantification": 67,
    "exact_ms2_links": 35,
    "null_evidence_intensity": 15,
    "zero_group_intensity": 15
  },
  "deep_validation": {
    "valid": true,
    "bottom_up_valid": true,
    "issue_count": 0
  },
  "performance": {
    "zp_write_seconds": 1.026719,
    "zp_validate_seconds": 0.170384,
    "total_seconds": 4.603727300011087
  }
}
```

## 11. 首轮失败与修正记录

### 11.1 DeepSeek 首轮路径错误

首轮候选把 `relative_source` 写成 `maxquant_mzml_v1 single-sample bundle`。该路径不存在，旧 preflight 抛出裸 `FileNotFoundError`，导致 repair loop 无法接管。

修正：`mapping_preflight` 现在把不存在或不可访问的候选源路径统一转换为 `AgentBinaryPlanError`，使已有结构化修复循环能够反馈给 Agent 2。新增单测覆盖缺失 `relative_source` 和缺失 source file。

### 11.2 首轮 Sol 复核结果

首轮 Blueprint 把能力之外的转换日志设为必需内容，同时复核提示词要求 CandidatePlan 重复无法表达的可视化与额外计数，因此首轮复核正确阻止执行但包含合同边界误判。

首轮实际复核输出：

```json
{
  "schema_version": 1,
  "status": "REJECTED",
  "issues": [
    "The conversion logs are omitted from source_files and detected_roles, even though the Blueprint requires conversion status and provenance from the stdout log in required global_meta and source_provenance sections. The candidate therefore silently drops Blueprint-required content.",
    "The plan does not declare or enforce several deterministic acceptance checks required by the Blueprint: 1,431 MS1 versus 6,103 MS2 spectra, 3,949,930 spectral peak pairs, one BasePeak_0 chromatogram with 7,534 points, 4,499 FASTA records, four unmatched contaminant accessions, and the exact RAW and mzML digests.",
    "The candidate provides no implementation or preservation declaration for the Blueprint's required visualization suite, including run overview, chromatogram map, spectrum inspector, identification explorer, protein-group, sequence, quantification, modification, and provenance views.",
    "The mandatory mzML-declared RAW SHA-1 comparison is not represented as a declared validation rule in the mapping plan. A factual statement of the RAW digest is not equivalent to enforcing the checksum relation during import.",
    "The plan does not explicitly validate that all 70 evidence columns and all 41 protein-group columns remain recoverable, nor that empty, NaN literal, null, and numeric zero remain distinguishable. Adapter policy suggests preservation, but the candidate lacks acceptance assertions for these Blueprint requirements.",
    "The candidate is marked READY despite dropping required provenance inputs and omitting multiple Blueprint acceptance validations; deterministic preflight passing only establishes adapter/schema compatibility, not faithful Blueprint implementation."
  ],
  "questions": [],
  "evidence": [
    "Blueprint binary_content.global_meta requires conversion status and cites .viewer-derived/raw-conversion-logs/001-pxd000001.stdout.log.",
    "Blueprint binary_content.source_provenance requires conversion log status and the conversion-log asset path.",
    "Candidate source_files includes neither conversion stdout nor stderr logs, and deterministic_preflight.detected_roles contains no conversion-log role.",
    "Candidate expected_counts contains only spectra, precursors, evidence_rows, and protein_groups.",
    "Blueprint acceptance criteria additionally require exact MS-level counts, peak-pair count, chromatogram identity and point count, FASTA count, unmatched contaminants, exact digests, full physical-column recovery, and null/NaN/empty/zero distinctions.",
    "Blueprint default_import requires the mzML-declared RAW SHA-1 to match the bundled RAW checksum when available; the candidate join_rules contain only scan and protein-group evidence joins.",
    "The candidate contains no visualization or view configuration corresponding to the eleven Blueprint visualizations.",
    "Runtime capabilities support the required core and bottom-up blocks, so these omissions are implementation deviations rather than unresolved scientific choices."
  ]
}
```

修正：

- Agent 1 研究提示词要求所有 `required` 内容严格落在 `zp_capabilities` 的角色、preserves、expected-count keys 和 first-version limits 内。
- Agent 1 复核提示词只检查 `candidate_json_schema` 可表达的内容；Blueprint 可视化和下游语义验收不要求在 CandidatePlan 中重复。
- 重新生成的 v2 Blueprint 不再把转换日志设为必需输入；v2 Plan 通过 preflight，v2 Review 返回 `APPROVED`。

## 12. 复现命令

在 `E:\viewer` 执行：

```powershell
back\.venv\Scripts\python.exe cs\Kimi研究Agent真实验收.py --source E:\viewer-agent\maxquant\maxquant-viz-data\single-sample --output .tmp\双Agent真实联调-20260903\Agent1-Sol-Blueprint-v2.json
back\.venv\Scripts\python.exe cs\DeepSeek实施Agent真实验收.py --source E:\viewer-agent\maxquant\maxquant-viz-data\single-sample --blueprint .tmp\双Agent真实联调-20260903\Agent1-Sol-Blueprint-v2.json --output .tmp\双Agent真实联调-20260903\Agent2-DeepSeek-Plan-v2.json
back\.venv\Scripts\python.exe cs\Kimi复核Agent2真实验收.py --source E:\viewer-agent\maxquant\maxquant-viz-data\single-sample --blueprint .tmp\双Agent真实联调-20260903\Agent1-Sol-Blueprint-v2.json --plan .tmp\双Agent真实联调-20260903\Agent2-DeepSeek-Plan-v2.json --output .tmp\双Agent真实联调-20260903\Agent1-Sol-Review-v2.json
back\.venv\Scripts\python.exe cs\MaxQuant复合二进制验收.py --source E:\viewer-agent\maxquant\maxquant-viz-data\single-sample --output .tmp\双Agent真实联调-20260903\single-sample-v3.zp
```

后端回归：

```powershell
cd E:\viewer\back
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
```

## 13. 开发时应关注的稳定合同

- Agent 1 输出必须通过 `AgentResearchResult`；本地模式允许 `citations=[]`、`web_search_calls=0`、`fetch_calls=0`。
- Agent 2 只能输出 `AgentCandidatePlan`，READY mapping 方案必须通过 Pydantic、capability 白名单和 deterministic preflight。
- `relative_source` 与每个 `source_file.relative_path` 必须是 Case 根目录内真实存在的相对路径。
- Review 只接受 `APPROVED`、`NEEDS_USER`、`REJECTED`；只有 `APPROVED` 才能进入二进制执行。
- 模型不写 `.zp`；唯一写入路径仍是 Viewer ZP engine，写后必须重新打开、核对声明计数与 RAW↔mzML provenance。
- API key 不属于模型输入输出合同，任何日志和记录都必须保持脱敏。
