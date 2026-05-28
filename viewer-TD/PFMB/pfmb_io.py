"""
pfmb_io.py — PFMB 二进制文件读写对外接口（前端 / 下游服务直接 import）

格式版本：PFMB v2，带 uint64 偏移索引表，支持 O(1) 随机读取。

快速上手
--------
>>> from pfmb_io import PfmbReader, PfmbRecord

# 1. 按 prsm_index（TopPIC 编号）随机读一条 —— 偏移表 O(1)，无需扫全文件
>>> with PfmbReader("results.pfmb") as r:
...     rec: PfmbRecord = r.read_by_prsm_index(0)
...     print(rec.peptide, rec.scan, len(rec.matches))
...     for m in rec.matches[:3]:
...         print(m["fragment_series"], m["fragment_ordinal"],
...               m["mass_error_ppm"], m["intensity"])

# 2. 按顺序索引直接跳转（最快，O(1)）
>>> with PfmbReader("results.pfmb") as r:
...     rec = r.read_record(5000)   # 第 5000 条记录

# 3. 顺序迭代全量（streaming，内存友好）
>>> with PfmbReader("results.pfmb") as r:
...     for rec in r.iter_records():
...         process(rec)

# 4. 全量加载为 dict（兼容评估脚本）
>>> from pfmb_io import load_pfmb_bundle
>>> pred = load_pfmb_bundle("results.pfmb")  # {prsm_index: [match_dict, ...]}

# 5. 查看文件头信息（CLI）
#    python pfm.py bundle-show results.pfmb --head 8
#    python pfm.py bundle-export results.pfmb --prsm 0 --out prsm0.json

字段说明
--------
PfmbRecord 属性：
    record_index  : int          – 记录在文件中的顺序下标（0-based）
    prsm_index    : int          – TopPIC prsm 编号（文件名数字）
    scan          : int          – MS2 扫描号
    spec_id       : int          – 谱图 ID
    peptide       : str          – 肽段序列（含修饰，来自 TopPIC annotated_seq）
    metadata      : dict         – 其余头部字段
    summary       : dict         – 可选汇总字段
    matches       : list[dict]   – 每条匹配，字段见下

matches 列表每项字段：
    peak_id                 : int    – 对应 TopPIC 峰编号
    fragment_series         : str    – 离子系列：b / y / c / z_dot
    fragment_ordinal        : int    – 碎片序号（如 b3 → ordinal=3）
    observed_neutral_mass   : float  – 实验峰中性质量 (Da)
    theoretical_neutral_mass: float  – 理论碎片中性质量 (Da)
    mass_error_ppm          : float  – 质量误差 (ppm)
    mass_error_da           : float  – 质量误差 (Da)
    intensity               : float  – 峰强度
    charge                  : int    – 峰电荷数（来自去卷积）

文件格式布局（v2）
------------------
PFMB v3: 魔数 | bundle_hdr_len | 二进制 bundle 头 (version=3) | uint64[N] 偏移表
→ 每条: record_len | PFM2 (prsm/scan/spec/肽段UTF-8/N) | 9列×29B
仍可读 v2: bundle 头 JSON + PFM1 子记录（PfmbReader 自动识别）
"""
from __future__ import annotations

from pfm import (
    BUNDLE_FORMAT_VERSION,
    BUNDLE_MAGIC,
    INDEX_VERSION,
    MAGIC,
    MAGIC2,
    PfmbRecord,
    PfmbReader,
    load_pfmb_bundle,
    read_pfm,
    summarize_pfmb,
    export_pfmb_prsm_to_json,
    write_pfmb_lean_bundle,
    write_pfm_bundle,
    encode_pfm_columns,
    encode_pfm_record,
    _COLS as MATCH_COLUMNS,
)

__all__ = [
    # 常量
    "BUNDLE_MAGIC",
    "BUNDLE_FORMAT_VERSION",
    "INDEX_VERSION",
    "MAGIC",
    "MAGIC2",
    "MATCH_COLUMNS",
    # 核心类
    "PfmbRecord",
    "PfmbReader",
    # 函数 – 读
    "load_pfmb_bundle",
    "read_pfm",
    # 函数 – 写
    "write_pfmb_lean_bundle",
    "write_pfm_bundle",
    "encode_pfm_columns",
    "encode_pfm_record",
    # 工具
    "summarize_pfmb",
    "export_pfmb_prsm_to_json",
]
