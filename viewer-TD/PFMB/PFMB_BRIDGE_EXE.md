# `pfmb_bridge.exe` 交付说明（给前后端同事）

这个程序提供三个接口，用于直接接入同事程序，不包含任何预置结果文件。

- `ingest`：把上游输入转成统一 `prsm.cache`
- `run`：执行匹配引擎，产出二进制 `results.pfmb`
- `egress`：把 `results.pfmb` 导出为程序可消费的 JSON/CSV

---

## 1) 打包

在仓库根目录执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_pfmb_bridge_exe.ps1
```

产物：

- `dist\pfmb_bridge.exe`

---

## 2) 接口一：往里接（`ingest`）

### 2.1 TopPIC JS（histone 类）

```powershell
.\dist\pfmb_bridge.exe ingest `
  --source toppic_js `
  --prsm-dir "e:\ABC\histone_outputdata\...\data_js\prsms" `
  --cache ".\work\prsm.cache"
```

### 2.2 TopPIC XML + TopFD MSALIGN（330 类）

```powershell
.\dist\pfmb_bridge.exe ingest `
  --source xml_msalign `
  --prsm-xml "e:\ABC\xzx_PXD045330\xzx_PXD045330\toppic\xxx_toppic_prsm.xml" `
  --ms2-msalign "e:\ABC\xzx_PXD045330\xzx_PXD045330\topfd\xxx_ms2.msalign" `
  --cache ".\work\prsm.cache" `
  --manifest ".\work\cache_build.manifest.json"
```

### 2.3 DIA-NN pos.pkl（Hela 类）

```powershell
.\dist\pfmb_bridge.exe ingest `
  --source diann_pos_pkl `
  --pos-pkl "e:\ABC\bottom up\DIANN_2.0\DIANN_2.0\xxx.mzML.pos.pkl" `
  --cache ".\work\prsm.cache" `
  --manifest ".\work\cache_build.manifest.json"
```

---

## 3) 接口二：引擎运行（`run`）

> 这一步就是你原来的核心引擎能力（`run_batch_fast`），输出是二进制 PFMB。

```powershell
.\dist\pfmb_bridge.exe run `
  --cache ".\work\prsm.cache" `
  --output ".\work\engine_out" `
  --preset native_coverage `
  --rebuild-frag-cache
```

输出：

- `.\work\engine_out\results.pfmb`（二进制主结果）
- `.\work\engine_out\summary.json`

---

## 4) 接口三：往外传（`egress`）

> 由同事程序先产出 `results.pfmb`，本接口仅做读取导出。

### 3.1 导出单条 PRSM（JSON）

```powershell
.\dist\pfmb_bridge.exe egress `
  --cache ".\work\prsm.cache" `
  --pfmb ".\work\results.pfmb" `
  --prsm 0 `
  --format json `
  --out ".\out\prsm0_peaks.json"
```

### 3.2 导出全量（JSON）

```powershell
.\dist\pfmb_bridge.exe egress `
  --cache ".\work\prsm.cache" `
  --pfmb ".\work\results.pfmb" `
  --all `
  --format json `
  --out-dir ".\out\peak_status"
```

输出目录会包含：

- `prsm{N}_peaks.json`（每条 PRSM 一个文件）
- `_index.json`（全量索引与汇总）

---

## 5) 同事对接最小约定

- 输入接口：调用 `ingest`，拿到统一 `prsm.cache`
- 引擎接口：调用 `run`，生成 `results.pfmb`
- 输出接口：调用 `egress`，拿到 JSON/CSV，供前端或其他服务读取

返回日志均为单行 JSON，便于外部程序解析（`ok/interface/mode/output` 等字段）。
