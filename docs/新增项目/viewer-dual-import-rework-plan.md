# Viewer本地与服务器双模式导入改造实施计划

## 1. 文档目的

本计划用于指导Viewer导入系统完成以下改造：

1. 保留当前本地路径导入能力，现有使用方式和导入结果不得被破坏。
2. 新增服务器上传导入能力：

   * 用户通过浏览器选择本地文件。
   * 文件上传到服务器的`/root/shuju-viewer/shuju/<数据集目录>/`。
   * 服务器从该目录执行现有解析和入库程序。
3. 本地上传和服务器上传均支持：

   * 显示上传或导入进度。
   * 用户主动暂停。
   * 保存安全检查点。
   * 24小时内继续。
4. 暂停或可恢复失败超过24小时后：

   * 本地模式删除未完成数据库数据和派生数据，不删除用户原始文件。
   * 服务器模式删除未完成数据库数据、派生数据，以及本次上传到服务器的数据集目录。
5. 前端根据当前运行环境显示不同的导入入口、说明文案和清理警告。
6. 使用同一个Git仓库、同一个`main`分支和同一套代码，通过每台机器自己的`back/.env`决定启用的功能。

---

# 2. 当前环境基线

## 2.1 服务器目录

服务器根目录：

```text
/root/shuju-viewer/
```

程序和数据结构：

```text
/root/shuju-viewer/
├── back/
├── front/
├── docs/universal_schema.sql
├── shuju/
│   ├── <现有数据集>/
│   └── .viewer-derived/
├── logs/
├── start-backend.sh
├── start-all.sh
└── update.sh
```

服务器配置：

```text
/root/shuju-viewer/back/.env
```

已有配置：

```env
DATA_ROOT=../shuju
```

服务器数据规则：

```text
原始数据：
/root/shuju-viewer/shuju/<数据集目录>/

派生数据：
/root/shuju-viewer/shuju/.viewer-derived/
```

服务器端新增上传文件也必须进入现有`shuju/`数据体系，不创建另一套永久数据根目录。

## 2.2 服务结构

```text
浏览器:50001
    ↓
Nginx
    ├── front/dist/
    └── /api/* → 127.0.0.1:50002
                       ↓
                    FastAPI
                       ↓
             PostgreSQL + shuju/
```

后端目前通过`nohup`运行，没有systemd。

## 2.3 Git更新方式

本地开发并提交：

```bash
git add .
git commit
git push origin main
```

服务器更新：

```bash
cd /root/shuju-viewer
git pull --ff-only
./update.sh
```

服务器真实`.env`、`shuju/`和日志不得被Git跟踪或覆盖。

---

# 3. 第一性原理推导

实施前必须先接受以下基本事实。

## 3.1 浏览器不能直接读取服务器文件系统

本地部署时，浏览器和后端运行在同一台电脑，后端可以读取本地路径。

服务器部署时，用户浏览器位于用户电脑，后端位于服务器：

```text
用户电脑文件路径 ≠ 服务器文件路径
```

因此服务器版不能继续使用本地路径读取，必须先上传文件。

## 3.2 上传和导入是两个不同过程

服务器模式至少包含：

```text
上传过程
    ↓
文件完整性确认
    ↓
解析和入库过程
```

两者必须分别保存状态和进度，不能只维护一个模糊的百分比。

需要分别记录：

```text
upload_progress
import_progress
```

## 3.3 暂停不能通过强制停止线程实现

“随时暂停”在工程上应解释为：

> 用户可以随时提交暂停请求，程序在下一个安全检查点完成当前批次、提交事务、保存检查点，然后进入暂停状态。

不能：

* 强制终止Python线程。
* 在数据库事务中间停止。
* 在文件写入一半时直接杀死进程。
* 假设所有第三方程序都支持内部断点续跑。

## 3.4 RAW转换不能保证内部断点续跑

ThermoRawFileParser等外部转换程序通常只能支持阶段级恢复：

```text
转换前
转换完成后
```

如果转换过程中服务异常退出，当前RAW转换阶段可能需要重新执行。

因此必须区分：

* 流程级恢复。
* 批次级恢复。
* 第三方工具内部恢复。

第一版只要求前两种，不承诺第三方转换工具内部从50%继续。

## 3.5 数据所有权决定能否删除文件

不能仅根据路径或导入模式猜测文件是否可以删除。

必须明确保存：

```text
EXTERNAL_FILE
MANAGED_UPLOAD
```

含义：

```text
EXTERNAL_FILE：
用户原本就拥有的文件，Viewer只能读取，不能删除。

MANAGED_UPLOAD：
Viewer通过服务器上传接口创建和管理的文件，未完成任务过期后可以删除。
```

## 3.6 未完成数据不能对正常用户可见

数据集是否可见不能由“目录是否存在”决定，而必须由发布状态决定：

```text
IMPORTING
READY
FAILED
```

只有`READY`数据集可以出现在正常数据集列表中。

## 3.7 数据库与文件系统不是同一个事务

PostgreSQL提交成功，不代表文件写入成功；文件写入成功，也不代表数据库状态更新成功。

因此必须设计：

* 幂等写入。
* 资源清单。
* 状态机。
* 崩溃恢复。
* 定期一致性核对。

不能假设数据库与文件可以一次性原子提交。

## 3.8 Git同步代码，环境配置决定行为

同一套代码同时包含：

* 本地路径导入。
* 服务器上传导入。

两端通过各自不进入Git的`back/.env`进行区分。

本地：

```env
VIEWER_DEPLOYMENT_MODE=local
IMPORT_LOCAL_PATH_ENABLED=true
IMPORT_SERVER_UPLOAD_ENABLED=false
```

服务器：

```env
VIEWER_DEPLOYMENT_MODE=server
IMPORT_LOCAL_PATH_ENABLED=false
IMPORT_SERVER_UPLOAD_ENABLED=true
```

前端不能通过域名或`localhost`自行判断，必须请求后端能力接口。

---

# 4. 核心架构决策

## 4.1 使用一套代码，不创建本地分支和服务器分支

禁止创建：

```text
main-local
main-server
```

禁止复制两套导入程序。

正确结构：

```text
本地路径入口 ─┐
              ├─ ImportJobExecutor
服务器上传入口 ┘
                     ↓
                 现有导入能力
                     ↓
             PostgreSQL + 派生数据
```

## 4.2 两种入口，共用执行器

本地入口负责：

* 验证本地路径。
* 声明文件属于`EXTERNAL_FILE`。
* 创建统一导入任务。

服务器入口负责：

* 创建Viewer管理的数据集目录。
* 分块上传。
* 校验上传完整性。
* 声明文件属于`MANAGED_UPLOAD`。
* 创建或启动统一导入任务。

进入解析阶段后，两种模式必须共用同一个执行器。

## 4.3 服务器上传目录

服务器上传文件直接进入：

```text
/root/shuju-viewer/shuju/<新数据集目录>/
```

推荐形式：

```text
shuju/
├── existing-dataset/
├── upload_20260714_a71d4c/
│   ├── .viewer-import-manifest.json
│   ├── sample.raw.uploading
│   ├── sample.raw
│   ├── identification.json
│   └── reference.fasta
└── .viewer-derived/
    └── import-jobs/
        └── <job_id>/
            ├── checkpoint.json
            ├── converted/
            ├── partial-indexes/
            └── partial-derived/
```

数据集原文件进入数据集目录。

导入过程的中间文件进入：

```text
shuju/.viewer-derived/import-jobs/<job_id>/
```

## 4.4 不移动大型原始文件完成发布

服务器上传完成后，原始文件已经位于最终数据集目录。

导入完成时不应再次移动几十GB文件，而应通过以下状态完成发布：

```text
Dataset.status = READY
ImportJob.status = COMPLETED
manifest.dataset_status = READY
```

---

# 5. 实施前置门禁

以下内容完成前禁止修改业务代码。

## 5.1 备份

服务器执行：

```bash
cd /root/shuju-viewer/back
cp .env .env.before-import-job
```

备份启动脚本和Nginx配置：

```bash
cp /root/shuju-viewer/start-all.sh /root/shuju-viewer/start-all.sh.before-import-job
cp /root/shuju-viewer/update.sh /root/shuju-viewer/update.sh.before-import-job
cp /etc/nginx/conf.d/viewer.conf /etc/nginx/conf.d/viewer.conf.before-import-job
```

实施数据库结构变更前执行数据库备份。

## 5.2 Git安全检查

本地和服务器都检查：

```bash
git ls-files back/.env
git ls-files shuju
git ls-files logs
```

这些命令不应输出真实配置或数据文件。

`.gitignore`至少应覆盖：

```gitignore
back/.env
.env
shuju/
logs/
back/.venv/
front/node_modules/
```

如果`back/.env`已经被跟踪，必须先停止跟踪，再开始本次改造。

## 5.3 测试数据根目录隔离

所有删除、过期和恢复测试必须使用单独的数据根目录，例如：

```text
E:\viewer\server-test-shuju\
```

禁止直接对服务器现有22.5GB正式数据执行破坏性测试。

---

# 6. 实施阶段总览

严格按以下顺序执行：

```text
P0 真实现状调查
P1 第一性原理与对抗性设计审查
P2 运行环境能力判断
P3 ImportJob数据模型和状态机
P4 现有本地导入接入任务系统
P5 检查点、暂停和恢复
P6 服务器分块上传
P7 24小时过期清理
P8 前端双模式界面
P9 Worker与服务器启动更新
P10 全链路测试和灰度发布
P11 运行观察与一致性核对
```

不得跳过P4直接实现服务器上传。

---

# 7. P0：真实现状调查

## 7.1 目标

确认当前导入系统的真实调用链、数据库写入点和文件生命周期。

本阶段只调查，不修改代码。

## 7.2 必须调查的问题

### 导入入口

查明：

* 当前本地导入页面和组件。
* 当前导入API。
* 当前请求参数。
* 本地文件路径如何传入后端。
* TopPIC、PrSM、DIA-NN、RAW、mzML分别经过哪些模块。

### 数据库生命周期

查明：

* Dataset记录在什么时候创建。
* Run、Spectrum、Precursor、Chromatogram什么时候写入。
* 是否按批次提交。
* 是否存在唯一约束。
* 删除Dataset时是否级联删除相关记录。
* 未完成数据当前是否会出现在列表中。

### 文件生命周期

查明：

* RAW转换结果保存位置。
* mzML索引和色谱派生文件保存位置。
* `.viewer-derived`中各目录的创建者。
* 删除数据集时哪些文件会被删除。
* 哪些路径来自用户输入。

### 服务运行

查明：

* `start-backend.sh`内容。
* `start-all.sh`内容。
* `update.sh`内容。
* 后端进程PID和重启方式。
* 是否存在多个Uvicorn进程。
* 数据库结构目前如何更新。
* `docs/universal_schema.sql`是初始化脚本还是增量脚本。

## 7.3 输出物

必须输出调查报告，包括：

1. 当前调用链。
2. 数据表清单。
3. 文件写入清单。
4. 删除影响范围。
5. 当前事务边界。
6. 当前测试基线。
7. 不能确定的事项。
8. 建议修改文件列表。

## 7.4 退出条件

只有在能够回答以下问题后才进入P1：

> 如果当前导入在50%时进程退出，数据库和磁盘分别留下什么？

---

# 8. P1：第一性原理与对抗性设计审查

本阶段仍然不写实现代码。

## 8.1 审查对象

需要形成正式设计记录，至少包括：

* 导入状态机。
* 文件所有权模型。
* 数据集发布模型。
* 检查点格式。
* 幂等策略。
* Worker领取任务规则。
* 24小时计算规则。
* 清理安全规则。
* 磁盘空间策略。
* 权限和上传安全策略。

## 8.2 必须回答的反对问题

### 问题一：服务在数据库提交后、检查点更新前崩溃怎么办？

设计必须保证恢复后不会重复插入。

可采用：

* 数据唯一约束。
* Upsert。
* 批次完成记录。
* 检查点重新执行时幂等。

### 问题二：用户点击继续时，清理程序正准备删除怎么办？

必须通过数据库原子状态转换解决：

```text
PAUSED
    ↓
CLEANING
```

只有成功取得`CLEANING`状态的清理程序才能删除。

恢复操作只能对仍为`PAUSED`的任务生效。

### 问题三：Worker已经死亡，但任务仍显示RUNNING怎么办？

需要Worker租约：

```text
worker_id
worker_heartbeat_at
worker_lease_expires_at
```

租约超时后任务进入：

```text
FAILED_RETRYABLE
```

不能永久停留在`RUNNING`。

### 问题四：有人上传恶意路径怎么办？

禁止用户指定服务器绝对路径。

物理目录名由服务器生成。

必须防止：

* `../`目录穿越。
* 绝对路径。
* 符号链接逃逸。
* 同名覆盖。
* 文件名控制字符。
* 删除`shuju/`根目录。
* 删除`.viewer-derived/`根目录。

### 问题五：有人反复上传大文件导致服务器磁盘满怎么办？

服务器上传接口上线前必须具备：

* 身份或管理权限限制。
* 最大文件大小。
* 最大任务大小。
* 最大并发上传数。
* 最大并发导入数。
* 上传前磁盘空间检查。
* 保留磁盘安全水位。
* 过期清理。
* 孤儿目录核对。

如果当前Viewer没有用户认证，服务器上传必须至少受管理员令牌、反向代理访问控制或受限网络保护。公开匿名上传属于发布阻断问题。

### 问题六：运行超过24小时的大任务会不会被删？

不会。

24小时倒计时只对以下状态生效：

```text
UPLOAD_PAUSED
PAUSED
FAILED_RETRYABLE
```

正常上传、正常运行和正常完成阶段不应因持续时间超过24小时而过期。

## 8.3 退出条件

必须形成一份明确的设计决定记录。

所有删除行为必须能够回答：

> 为什么这个目录属于当前任务，为什么允许删除，删除前检查了什么？

无法回答时不得进入实现。

---

# 9. P2：运行环境能力判断

## 9.1 配置项

新增配置：

```env
VIEWER_DEPLOYMENT_MODE=local
IMPORT_LOCAL_PATH_ENABLED=true
IMPORT_SERVER_UPLOAD_ENABLED=false
IMPORT_CHECKPOINT_RETENTION_HOURS=24
IMPORT_JOB_DERIVED_SUBDIR=.viewer-derived/import-jobs
IMPORT_MAX_CONCURRENT_JOBS=1
IMPORT_MIN_FREE_DISK_GB=20
```

服务器配置：

```env
VIEWER_DEPLOYMENT_MODE=server
IMPORT_LOCAL_PATH_ENABLED=false
IMPORT_SERVER_UPLOAD_ENABLED=true
IMPORT_CHECKPOINT_RETENTION_HOURS=24
IMPORT_JOB_DERIVED_SUBDIR=.viewer-derived/import-jobs
IMPORT_MAX_CONCURRENT_JOBS=1
IMPORT_MIN_FREE_DISK_GB=20
```

实际数值需要结合服务器磁盘容量确认。

## 9.2 Git规则

提交：

```text
back/.env.example
```

不提交：

```text
back/.env
```

`update.sh`不得执行：

```bash
cp back/.env.example back/.env
git clean -fdx
```

## 9.3 能力接口

新增：

```http
GET /api/v1/import-jobs/capabilities
```

本地返回：

```json
{
  "deployment_mode": "local",
  "local_path_import_enabled": true,
  "server_upload_import_enabled": false,
  "checkpoint_retention_hours": 24
}
```

服务器返回：

```json
{
  "deployment_mode": "server",
  "local_path_import_enabled": false,
  "server_upload_import_enabled": true,
  "checkpoint_retention_hours": 24
}
```

前端只能根据该接口决定显示内容。

## 9.4 后端强制校验

前端隐藏按钮不等于安全。

本地路径API在服务器关闭时必须返回拒绝。

服务器上传API在本地关闭时必须返回拒绝。

---

# 10. P3：ImportJob数据模型和状态机

## 10.1 数据模型

新增`import_jobs`。

建议字段：

```text
id
dataset_id
mode
status
source_type
source_ownership
source_root
dataset_directory
current_stage
upload_bytes_completed
upload_bytes_total
import_items_completed
import_items_total
progress_message
checkpoint_json
pause_requested
last_activity_at
expires_at
worker_id
worker_heartbeat_at
worker_lease_expires_at
error_code
error_message
created_at
started_at
paused_at
completed_at
updated_at
```

## 10.2 模式

```text
LOCAL_PATH
SERVER_UPLOAD
```

## 10.3 所有权

```text
EXTERNAL_FILE
MANAGED_UPLOAD
```

## 10.4 状态

```text
CREATED
UPLOADING
UPLOAD_PAUSED
READY
QUEUED
RUNNING
PAUSE_REQUESTED
PAUSED
FAILED_RETRYABLE
COMPLETING
COMPLETED
CLEANING
EXPIRED
CANCELLED
```

## 10.5 数据集状态

新增或确认：

```text
IMPORTING
READY
FAILED
```

普通数据集列表默认只返回：

```text
READY
```

## 10.6 资源台账

强烈建议新增`import_job_resources`，不要让清理程序靠猜测路径工作。

字段建议：

```text
id
job_id
resource_type
path
ownership
delete_on_expire
publish_state
created_at
deleted_at
```

资源类型可以包括：

```text
MANAGED_SOURCE_FILE
MANAGED_DATASET_DIRECTORY
PARTIAL_DERIVED_DIRECTORY
CONVERTED_FILE
DATABASE_DATASET
DATABASE_BATCH
```

清理程序只删除台账中：

```text
delete_on_expire=true
```

且经过路径安全验证的资源。

---

# 11. P4：现有本地导入接入任务系统

## 11.1 目标

保证用户现有操作方式不变，但后端内部改为通过`ImportJob`执行。

## 11.2 实施原则

保留：

* 当前本地文件路径输入方式。
* 当前支持的文件类型。
* 当前导入结果。
* 当前数据集识别规则。

新增：

* 创建`LOCAL_PATH`任务。
* 标记`EXTERNAL_FILE`。
* 显示进度。
* 保存阶段状态。
* 失败后可诊断。

## 11.3 禁止事项

不得：

* 重写TopPIC、PrSM、DIA-NN等现有Adapter。
* 同时修改不相关可视化模块。
* 为了接任务系统改变现有数据语义。
* 删除旧入口后再重新实现。
* 允许清理程序删除本地源文件。

## 11.4 验收

必须证明：

1. 改造前后的本地导入结果一致。
2. 已完成数据集数量一致。
3. 谱图、蛋白、肽段、match数量一致。
4. 原始文件未被移动或删除。
5. 未完成数据集不出现在普通列表中。

---

# 12. P5：检查点、暂停和恢复

## 12.1 阶段划分

建议阶段：

```text
validate_source
hash_source
raw_conversion
inspect_mzml
create_dataset
parse_run_metadata
parse_spectra
parse_precursors
parse_chromatograms
import_identifications
build_indexes
build_chromatograms
build_derived_data
finalize_dataset
```

实际阶段必须以P0调查结果为准。

## 12.2 检查点

示例：

```json
{
  "version": 1,
  "stage": "parse_spectra",
  "run_index": 0,
  "next_spectrum_index": 12000,
  "completed_spectra": 12000,
  "completed_ms1": 4000,
  "completed_ms2": 8000,
  "last_native_id": "controllerType=0 controllerNumber=1 scan=12000"
}
```

检查点必须带版本号，防止未来代码升级后无法解释旧检查点。

## 12.3 安全批次

谱图等大规模数据建议每500至2000条作为一个批次。

每个批次：

1. 写数据库。
2. 提交事务。
3. 更新批次完成状态。
4. 保存检查点。
5. 更新进度。
6. 更新Worker心跳。
7. 检查`pause_requested`。

批次大小应通过测试确定，不应写死为未经验证的值。

## 12.4 暂停语义

用户点击暂停：

```text
RUNNING
    ↓
PAUSE_REQUESTED
    ↓
完成当前安全批次
    ↓
PAUSED
```

前端提示：

> 已提交暂停请求，系统将在完成当前安全批次后保存进度并暂停。

## 12.5 恢复语义

恢复时：

1. 校验任务仍为可恢复状态。
2. 校验源文件仍存在。
3. 校验文件大小、修改时间或哈希未发生变化。
4. 读取检查点版本。
5. 从最后一个已确认批次之后继续。
6. 对可能重复的最后一个批次执行幂等写入。

## 12.6 RAW转换

RAW转换期间收到暂停：

* 不强制终止转换进程。
* 当前转换结束后暂停。
* 异常退出后重新执行当前转换阶段。
* 前端明确说明该限制。

---

# 13. P6：服务器分块上传

## 13.1 创建流程

```text
创建SERVER_UPLOAD任务
    ↓
服务器生成数据集目录
    ↓
写入所有权manifest
    ↓
登记文件
    ↓
分块上传
    ↓
完整性检查
    ↓
状态变为READY
    ↓
用户启动导入或自动排队
```

## 13.2 物理文件名

用户原始文件名仅用于显示。

服务器物理目录名和必要的物理文件名必须经过安全处理，避免同名覆盖和路径攻击。

## 13.3 上传文件状态

上传中：

```text
sample.raw.uploading
```

上传完成并校验后原子重命名：

```text
sample.raw.uploading
    ↓
sample.raw
```

## 13.4 分块接口

建议接口：

```http
POST /api/v1/import-jobs/server
POST /api/v1/import-jobs/{job_id}/files
PUT  /api/v1/import-jobs/{job_id}/files/{file_id}/chunks/{chunk_index}
GET  /api/v1/import-jobs/{job_id}/files/{file_id}/upload-status
POST /api/v1/import-jobs/{job_id}/files/{file_id}/complete
POST /api/v1/import-jobs/{job_id}/start
```

## 13.5 完整性

至少校验：

* 文件总大小。
* 分块数量。
* 分块范围。
* 最终文件大小。
* 可选SHA-256。

对于超大文件，可以允许哈希作为后台校验阶段，但未校验完成前不得开始导入。

## 13.6 上传中断

浏览器关闭或网络中断后：

* 已完成分块保留。
* 前端重新进入页面后查询上传状态。
* 从缺失分块继续。
* 不从头上传完整文件。

## 13.7 上传权限

服务器上传接口必须限制访问。

如果暂时没有完整用户系统，最低要求是：

* 管理员令牌。
* Nginx访问控制。
* 或仅允许受信网络。

匿名公网大文件上传不得上线。

---

# 14. P7：24小时过期清理

## 14.1 倒计时开始条件

只对以下状态设置：

```text
UPLOAD_PAUSED
PAUSED
FAILED_RETRYABLE
```

进入状态时：

```text
expires_at = 当前服务器时间 + 24小时
```

恢复时：

```text
expires_at = NULL
```

## 14.2 不应过期的状态

```text
UPLOADING且持续收到分块
QUEUED且任务正常等待
RUNNING且Worker租约有效
COMPLETING
COMPLETED
```

## 14.3 本地模式清理

当：

```text
source_ownership=EXTERNAL_FILE
```

删除：

* 未完成数据库数据。
* 未发布派生数据。
* 检查点。
* 批次记录。
* Viewer产生的临时转换结果。

禁止删除：

* 用户原始RAW。
* 用户原始mzML。
* JSON、Parquet、FASTA。
* 用户选择的目录。
* 现有外部数据目录。

## 14.4 服务器模式清理

当：

```text
source_ownership=MANAGED_UPLOAD
```

删除：

* 未完成数据库数据。
* 未发布派生数据。
* 检查点和批次记录。
* `.uploading`文件。
* 已上传原始文件。
* 当前任务创建的数据集目录。

## 14.5 删除安全条件

删除数据集目录前必须同时满足：

1. 任务状态成功转换为`CLEANING`。
2. `source_ownership=MANAGED_UPLOAD`。
3. 数据集不是`READY`。
4. 目录位于解析后的`DATA_ROOT`内部。
5. 目录不是`DATA_ROOT`本身。
6. 目录不是`.viewer-derived`。
7. 目录存在Viewer所有权manifest。
8. manifest中的`job_id`与数据库一致。
9. 资源台账声明该目录允许过期删除。
10. 目录不是符号链接逃逸路径。

任意条件不满足时停止自动删除并记录人工处理告警。

## 14.6 清理失败

文件被占用或数据库删除失败时：

* 不直接标记`EXPIRED`。
* 保留`CLEANING`或进入`CLEANUP_FAILED`。
* 记录失败资源。
* 后续重试。
* 不重复删除已确认完成的资源。

---

# 15. P8：前端双模式界面

## 15.1 页面判断

页面加载时请求：

```http
GET /api/v1/import-jobs/capabilities
```

根据能力开关显示：

```text
LocalPathImportPanel
ServerUploadImportPanel
```

不得通过域名判断运行环境。

## 15.2 本地提示

> 本地路径导入
> 系统会直接读取你选择的本地文件或目录。导入过程中可以暂停，并在24小时内继续。超过24小时未继续，系统会删除本次导入产生的未完成数据库记录、检查点和派生数据，但不会删除你的RAW、mzML、JSON、Parquet、FASTA等原始文件。

## 15.3 服务器提示

> 服务器上传导入
> 文件会先上传到服务器的Viewer数据目录，再由服务器执行解析和入库。上传和导入过程均支持暂停与恢复。超过24小时未继续，系统会删除本次未完成数据库记录、派生数据，以及本次上传到服务器的全部原始文件。

## 15.4 任务卡片

至少显示：

```text
任务名称
模式
文件名称
上传阶段
导入阶段
上传进度
导入进度
当前处理数量
最后检查点时间
暂停时间
过期时间
距离清理剩余时间
错误原因
```

操作：

```text
暂停
继续
取消并清理
重试当前阶段
查看错误
```

## 15.5 页面刷新

任务状态必须来自后端。

刷新页面后应能恢复显示：

* 已上传分块。
* 当前导入阶段。
* 暂停状态。
* 24小时倒计时。
* 可恢复错误。

不能只将任务状态保存在React内存或浏览器临时状态中。

---

# 16. P9：Worker与服务器启动更新

## 16.1 Worker

长时间导入不应挂在FastAPI请求生命周期中。

新增独立Import Worker。

第一版建议：

* 使用PostgreSQL任务表。
* 单Worker。
* 最大并发导入为1。
* 通过数据库原子更新领取任务。
* 持续更新租约和心跳。

暂时不强制引入Redis或Celery，除非P0证明现有架构已经使用相关组件。

## 16.2 启动脚本

新增：

```text
/root/shuju-viewer/start-import-worker.sh
```

日志：

```text
/root/shuju-viewer/logs/import-worker.log
```

更新`start-all.sh`：

```text
启动PostgreSQL
启动FastAPI
启动Import Worker
启动Nginx
执行服务健康检查
```

必须防止重复启动多个Worker。

## 16.3 update.sh

更新流程：

```text
1.检查back/.env存在
2.拉取代码
3.uv sync
4.执行数据库增量升级
5.安装前端依赖
6.构建front/dist
7.停止旧后端
8.停止旧Worker
9.启动后端
10.启动Worker
11.检查Nginx
12.执行健康检查
```

禁止：

* 删除`shuju/`。
* 删除`logs/`。
* 覆盖`back/.env`。
* 使用`git clean -fdx`。
* 使用初始化SQL直接覆盖生产数据库。
* 未备份就执行破坏性数据库操作。

## 16.4 Nginx

分块上传可以配置例如：

```nginx
client_max_body_size 64m;
proxy_request_buffering off;
proxy_read_timeout 3600s;
proxy_send_timeout 3600s;
```

单个分块必须小于Nginx限制。

不得采用单请求上传几十GB文件。

---

# 17. P10：测试与灰度发布

## 17.1 本地兼容测试

必须覆盖：

1. 原有TopPIC导入。
2. 原有PrSM导入。
3. 原有DIA-NN导入。
4. 原有RAW导入。
5. 原有mzML-only导入。
6. 改造前后数据库数量一致。
7. 暂停后可继续。
8. 服务重启后可恢复。
9. 过期后原始文件仍存在。
10. 未完成数据集不出现在列表。

## 17.2 服务器上传测试

必须覆盖：

1. 分块上传。
2. 中断后续传。
3. 同名文件。
4. 大文件。
5. 错误分块。
6. 最终大小不一致。
7. 哈希不一致。
8. 上传后正常导入。
9. 导入暂停恢复。
10. 24小时过期清理。
11. 服务器上传原文件被删除。
12. 已完成数据集不被删除。

## 17.3 崩溃测试

在以下位置主动终止进程：

* 分块写入中。
* 文件重命名前。
* 数据库批次提交前。
* 数据库提交后、检查点更新前。
* 检查点更新后。
* 派生文件写入中。
* 最终发布前。
* 清理数据库后、删除目录前。

重启后必须能够：

* 恢复。
* 重试。
* 或安全清理。

不得出现重复记录、半发布数据集或误删其他数据。

## 17.4 路径攻击测试

至少测试：

```text
../
../../shuju
/root
.viewer-derived
符号链接
超长文件名
控制字符
同名覆盖
```

## 17.5 磁盘测试

测试：

* 空间不足时拒绝新上传。
* 上传过程中空间低于安全水位。
* 派生数据生成时空间不足。
* 清理后空间是否释放。
* 孤儿目录是否能被发现。

## 17.6 灰度发布

第一阶段只开放给管理员。

限制：

```text
单个Import Worker
同时一个导入任务
限制单任务总大小
限制上传权限
```

稳定运行后再考虑并发和普通用户开放。

---

# 18. 对抗性审查结论

## 18.1 最大的错误假设

最危险的假设是：

> 任务状态写进数据库以后，数据库、原始文件和派生文件就一定保持一致。

实际上以下操作可能分别成功或失败：

```text
数据库写入
检查点写入
原始文件写入
派生文件写入
状态更新
Worker心跳
目录删除
```

所以必须把系统设计成能够处理部分成功，而不是试图假装所有操作是一个事务。

## 18.2 必须采用的防御

1. ImportJob显式状态机。
2. 文件所有权显式记录。
3. ImportJob资源台账。
4. 数据集原子发布状态。
5. 数据唯一约束和幂等批次。
6. Worker租约。
7. 清理状态锁。
8. 路径边界验证。
9. 定期一致性核对。
10. 磁盘空间门禁。
11. 上传权限限制。
12. 检查点版本化。

## 18.3 发布阻断条件

出现以下任意情况不得上线：

* 上传接口没有访问控制。
* 服务器能够根据用户输入删除路径。
* 清理程序通过目录名猜测所有权。
* 本地源文件可能被删除。
* 未完成数据集会出现在普通列表。
* 后端请求负责执行完整长时间导入。
* 没有Worker心跳。
* 没有磁盘空间检查。
* 没有恢复崩溃测试。
* `back/.env`仍被Git跟踪。
* `update.sh`可能清理`shuju/`。
* 前端只通过域名判断模式。

---

# 19. 三个月后最可能出现的问题

## 19.1 最可能出现的现象

三个月后最可能出现的问题不是某一个按钮失效，而是：

> `shuju/`和`.viewer-derived/`中逐渐积累未被数据库正确识别的孤儿目录、未完成上传文件、重复转换结果和部分派生数据，最终造成磁盘空间持续增长，导入失败，甚至影响PostgreSQL、Nginx和Viewer正常运行。

表面症状可能包括：

* 磁盘突然满。
* 上传到一半失败。
* Worker无法写检查点。
* PostgreSQL无法继续写入。
* 某些任务显示已删除，但目录仍存在。
* 某些目录被删除，但数据库任务仍显示可恢复。
* 同一个RAW生成多个转换结果。
* `.viewer-derived/import-jobs/`持续增长。
* 页面长期存在`RUNNING`任务。

## 19.2 根本原因

根本原因是：

```text
数据库任务状态
文件系统资源
Worker实际执行状态
```

三者发生漂移。

24小时清理只能处理数据库认为已经过期的任务，无法自动发现：

* 数据库写入前就创建的目录。
* Worker崩溃后未登记的文件。
* 手动操作产生的文件。
* 旧版本代码创建但新版本不认识的目录。
* 清理过程中只删除了一半的资源。

## 19.3 必须提前修正

本次第一版就应加入以下机制，而不是三个月后补救。

### 修正一：资源台账

每个由任务创建的资源都登记到`import_job_resources`。

清理程序根据台账操作，不扫描目录名猜测。

### 修正二：所有权manifest

每个Viewer创建的数据集目录保存：

```text
.viewer-import-manifest.json
```

至少记录：

```text
job_id
managed_by_viewer
source_ownership
dataset_status
created_at
files
```

### 修正三：一致性核对命令

新增只读核对命令，例如：

```bash
uv run python -m app.import_jobs.reconcile --check
```

输出：

* 数据库有任务但目录不存在。
* 目录存在但数据库无任务。
* READY数据集缺少文件。
* EXPIRED任务仍有资源。
* RUNNING任务租约已过期。
* 未登记的`.uploading`文件。
* 超过保留时间的partial目录。

必须先提供`--check`只读模式，再考虑人工确认后的修复模式。

### 修正四：磁盘门禁

创建任务和开始导入前检查：

```text
当前可用空间
预计上传大小
预计转换膨胀
预计派生数据大小
安全保留空间
```

不能只检查原始文件大小。

RAW转mzML和派生索引可能额外占用大量空间。

### 修正五：容量与并发限制

第一版：

```text
最大并发上传数受限
最大并发导入数=1
单任务最大总大小受限
低于安全磁盘水位时禁止新任务
```

### 修正六：运行监控

至少记录并可查看：

```text
当前磁盘剩余空间
活跃任务数
暂停任务数
过期任务数
清理失败任务数
Worker最后心跳
孤儿资源数量
```

## 19.4 第二高风险

当前Worker使用`nohup`且没有systemd，第二高风险是Worker异常退出后无人发现。

第一版至少需要：

* PID检查。
* 启动脚本防重复。
* Worker心跳。
* 健康检查接口。
* `start-all.sh`自动拉起。
* 日志轮转。

中期应考虑将后端和Worker迁移到systemd、Supervisor或容器编排管理，避免依赖单纯`nohup`。

---

# 20. 强制约束清单

后续任何AI实施时都必须遵守：

1. 只有一个代码仓库和一个`main`分支。
2. 本地和服务器通过各自`.env`区分。
3. 真实`.env`不进入Git。
4. 前端通过后端能力接口判断模式。
5. 保留现有本地导入方式。
6. 服务器上传进入`DATA_ROOT`下的新数据集目录。
7. 上传中间状态使用`.uploading`或明确的partial状态。
8. 本地源文件永远不能被自动清理。
9. 服务器文件只有明确为`MANAGED_UPLOAD`才能删除。
10. 删除前必须验证路径边界、manifest和资源台账。
11. 未完成数据集不能出现在普通列表。
12. 暂停必须采用协作式安全检查点。
13. RAW转换阶段不承诺内部断点续跑。
14. 导入批次必须幂等。
15. 长时间导入不能绑定FastAPI请求生命周期。
16. Worker必须有心跳和租约。
17. 24小时倒计时只针对暂停或可恢复失败。
18. 正常运行超过24小时不能被清理。
19. 上传接口必须有访问控制和容量限制。
20. `update.sh`不得覆盖`.env`或删除`shuju/`。
21. 前端修改后服务器必须重新构建`front/dist/`。
22. 数据库结构升级必须是增量且可回滚。
23. 未确认现有迁移机制前，不得擅自引入或假设Alembic。
24. 每个阶段必须独立测试并形成提交。
25. 删除和过期测试只能在隔离数据根目录执行。

---

# 21. 推荐提交顺序

建议每个阶段独立提交：

```text
chore: document import job architecture and safety constraints

feat: add deployment import capabilities

feat: add import job state model

refactor: route local imports through import jobs

feat: add resumable import checkpoints

feat: add managed server upload sessions

feat: add import expiration and safe cleanup

feat: add dual-mode import user interface

chore: add import worker startup and deployment checks

test: add import interruption and cleanup coverage
```

每次提交都应保持测试可运行，不要在一个提交中同时重构全部导入模块、数据库、前端和部署脚本。

---

# 22. 最终完成标准

只有满足以下条件，改造才算完成：

1. 本地原有导入结果没有回归。
2. 本地导入可以暂停和恢复。
3. 本地过期清理不会删除原始文件。
4. 服务器可以分块上传大文件。
5. 上传中断后可以续传。
6. 服务器导入可以暂停和恢复。
7. 服务器过期后删除当前任务上传的数据。
8. 已完成服务器数据集不会被清理。
9. 未完成数据集不会对正常用户可见。
10. 服务重启后任务能够恢复或明确进入可恢复状态。
11. Worker死亡不会导致任务永久RUNNING。
12. 恶意路径不能逃逸`DATA_ROOT`。
13. 磁盘不足时能够提前拒绝任务。
14. 匿名用户不能无限上传文件。
15. 前端在本地和服务器显示不同入口与文案。
16. 服务器`git pull`不会覆盖`.env`和`shuju/`。
17. `update.sh`能够完成依赖同步、前端构建、服务和Worker重启。
18. 一致性核对工具能够发现孤儿任务和孤儿目录。
19. 对抗性崩溃测试全部通过。
20. 至少完成一次服务器灰度导入和过期清理演练。
