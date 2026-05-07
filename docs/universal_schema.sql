-- Universal Viewer database schema
-- Target database: PostgreSQL
-- Usage:
--   psql -h localhost -U postgres -d "Universal_Viewer" -f "docs/universal_schema.sql"

CREATE TABLE IF NOT EXISTS datasets (
    dataset_id BIGSERIAL PRIMARY KEY,
    dataset_name VARCHAR(255) NOT NULL,
    slug VARCHAR(160) NOT NULL UNIQUE,
    analysis_mode VARCHAR(20) NOT NULL,
    source_software VARCHAR(100) NOT NULL,
    source_root TEXT NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'IMPORTED',
    description TEXT NULL,
    capabilities JSONB NOT NULL DEFAULT '{}'::jsonb,
    extra_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    source_zip_sha256 CHAR(64) NULL,

    CONSTRAINT ck_datasets_analysis_mode
        CHECK (analysis_mode IN ('BOTTOM_UP', 'TOP_DOWN')),

    CONSTRAINT ck_datasets_status
        CHECK (status IN ('IMPORTED', 'PARSING', 'READY', 'ERROR'))
);

COMMENT ON TABLE datasets IS '数据集表：一批导入数据的总入口，用于区分不同项目、实验包或导入批次。';
COMMENT ON COLUMN datasets.dataset_id IS '数据集唯一内部 ID。';
COMMENT ON COLUMN datasets.dataset_name IS '数据集展示名称，例如 MZ20160222DS_histone48_html。';
COMMENT ON COLUMN datasets.slug IS '数据集唯一短标识，用于 URL 和程序查询。';
COMMENT ON COLUMN datasets.analysis_mode IS '默认分析模式：BOTTOM_UP 或 TOP_DOWN。';
COMMENT ON COLUMN datasets.source_software IS '来源软件，例如 TopPIC_TopFD、MaxQuant、FragPipe。';
COMMENT ON COLUMN datasets.source_root IS '数据集根目录路径。';
COMMENT ON COLUMN datasets.status IS '数据集处理状态：IMPORTED、PARSING、READY、ERROR。';
COMMENT ON COLUMN datasets.description IS '数据集说明。';
COMMENT ON COLUMN datasets.capabilities IS '能力声明，例如是否有 MS1、MS2、PrSM、谱图文件。';
COMMENT ON COLUMN datasets.extra_metadata IS '额外元数据。';
COMMENT ON COLUMN datasets.created_at IS '数据集创建或导入时间。';
COMMENT ON COLUMN datasets.source_zip_sha256 IS '导入源 ZIP 的 SHA-256（hex）；删库后为空占用，可再次导入同一文件。';


CREATE UNIQUE INDEX IF NOT EXISTS uq_datasets_source_zip_sha256
    ON datasets (source_zip_sha256)
    WHERE source_zip_sha256 IS NOT NULL;


CREATE TABLE IF NOT EXISTS runs (
    run_id BIGSERIAL PRIMARY KEY,
    dataset_id BIGINT NOT NULL REFERENCES datasets(dataset_id) ON DELETE CASCADE,
    file_path TEXT NOT NULL,
    file_name VARCHAR(255) NOT NULL,
    analysis_mode VARCHAR(20) NOT NULL,
    software VARCHAR(100) NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'IMPORTED',
    instrument_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    sample_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT ck_runs_analysis_mode
        CHECK (analysis_mode IN ('BOTTOM_UP', 'TOP_DOWN')),

    CONSTRAINT ck_runs_status
        CHECK (status IN ('IMPORTED', 'PARSING', 'READY', 'ERROR'))
);

COMMENT ON TABLE runs IS '实验文件表：记录一个数据集下的原始文件、标准化文件或一次上机运行。';
COMMENT ON COLUMN runs.run_id IS '实验运行唯一内部 ID。';
COMMENT ON COLUMN runs.dataset_id IS '所属数据集 ID。';
COMMENT ON COLUMN runs.file_path IS '原始质谱文件或标准化文件在服务器上的物理路径。';
COMMENT ON COLUMN runs.file_name IS '原始文件名或目录名，方便前端展示。';
COMMENT ON COLUMN runs.analysis_mode IS '分析模式：BOTTOM_UP 或 TOP_DOWN。';
COMMENT ON COLUMN runs.software IS '来源软件，用于区分不同软件的专属字段。';
COMMENT ON COLUMN runs.status IS '当前处理状态：IMPORTED、PARSING、READY、ERROR。';
COMMENT ON COLUMN runs.instrument_metadata IS '质谱仪信息、采集参数等。';
COMMENT ON COLUMN runs.sample_metadata IS '样本信息，例如样本名、分组、重复编号。';
COMMENT ON COLUMN runs.created_at IS '记录创建或数据导入时间。';


CREATE TABLE IF NOT EXISTS proteins (
    protein_id BIGSERIAL PRIMARY KEY,
    dataset_id BIGINT NOT NULL REFERENCES datasets(dataset_id) ON DELETE CASCADE,
    accession VARCHAR(255) NOT NULL,
    gene_name VARCHAR(255) NULL,
    description TEXT NULL,
    base_sequence TEXT NULL,
    is_decoy BOOLEAN NOT NULL DEFAULT FALSE,
    extra_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,

    CONSTRAINT uq_proteins_dataset_accession_decoy
        UNIQUE (dataset_id, accession, is_decoy)
);

COMMENT ON TABLE proteins IS '基础蛋白表：Bottom-up 和 Top-down 共用的蛋白生物学根节点。';
COMMENT ON COLUMN proteins.protein_id IS '蛋白唯一内部 ID。';
COMMENT ON COLUMN proteins.dataset_id IS '所属数据集 ID。';
COMMENT ON COLUMN proteins.accession IS '公共数据库唯一编号，例如 UniProt Accession。';
COMMENT ON COLUMN proteins.gene_name IS '蛋白对应的基因名称。';
COMMENT ON COLUMN proteins.description IS '蛋白质详细功能描述或全称。';
COMMENT ON COLUMN proteins.base_sequence IS '完整、未修饰的理论氨基酸序列。';
COMMENT ON COLUMN proteins.is_decoy IS '是否为反向或随机诱饵蛋白。';
COMMENT ON COLUMN proteins.extra_metadata IS '参考数据库或来源软件带来的扩展属性。';


CREATE TABLE IF NOT EXISTS peptides (
    peptide_id BIGSERIAL PRIMARY KEY,
    dataset_id BIGINT NOT NULL REFERENCES datasets(dataset_id) ON DELETE CASCADE,
    sequence VARCHAR(1000) NOT NULL,
    theoretical_mass DOUBLE PRECISION NULL,
    length INTEGER NULL,
    missed_cleavages SMALLINT NULL,
    extra_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,

    CONSTRAINT uq_peptides_dataset_sequence
        UNIQUE (dataset_id, sequence)
);

COMMENT ON TABLE peptides IS '肽段表：Bottom-up 专用实体，记录不含修饰的纯氨基酸肽段。';
COMMENT ON COLUMN peptides.peptide_id IS '肽段唯一内部 ID。';
COMMENT ON COLUMN peptides.dataset_id IS '所属数据集 ID。';
COMMENT ON COLUMN peptides.sequence IS '纯氨基酸序列，不包含修饰。';
COMMENT ON COLUMN peptides.theoretical_mass IS '理论单同位素质量。';
COMMENT ON COLUMN peptides.length IS '肽段序列长度。';
COMMENT ON COLUMN peptides.missed_cleavages IS '酶切过程中的漏切位点数量。';
COMMENT ON COLUMN peptides.extra_metadata IS '肽段相关扩展属性。';


CREATE TABLE IF NOT EXISTS proteoforms (
    proteoform_id BIGSERIAL PRIMARY KEY,
    dataset_id BIGINT NOT NULL REFERENCES datasets(dataset_id) ON DELETE CASCADE,
    modifications JSONB NOT NULL DEFAULT '[]'::jsonb,
    start_res INTEGER NULL,
    end_res INTEGER NULL,
    theoretical_mass DOUBLE PRECISION NULL,
    extra_metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

COMMENT ON TABLE proteoforms IS '蛋白形态表：Top-down 专用实体，记录 PTMs、截短和质量变化的蛋白形态。';
COMMENT ON COLUMN proteoforms.proteoform_id IS '蛋白形态唯一内部 ID。';
COMMENT ON COLUMN proteoforms.dataset_id IS '所属数据集 ID。';
COMMENT ON COLUMN proteoforms.modifications IS 'PTMs 信息，包括修饰名称、位置、质量偏移等。';
COMMENT ON COLUMN proteoforms.start_res IS '该形态在基础蛋白序列中的 N 端起始位置。';
COMMENT ON COLUMN proteoforms.end_res IS '该形态在基础蛋白序列中的 C 端结束位置。';
COMMENT ON COLUMN proteoforms.theoretical_mass IS '蛋白形态理论精确质量。';
COMMENT ON COLUMN proteoforms.extra_metadata IS '其他形态衍生属性。';


CREATE TABLE IF NOT EXISTS identification_matches (
    match_id BIGSERIAL PRIMARY KEY,
    dataset_id BIGINT NOT NULL REFERENCES datasets(dataset_id) ON DELETE CASCADE,
    run_id BIGINT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    scan_number INTEGER NOT NULL,
    spectrum_native_id VARCHAR(255) NULL,
    retention_time DOUBLE PRECISION NULL,
    ms_level SMALLINT NOT NULL DEFAULT 2,
    entity_type VARCHAR(30) NOT NULL,
    entity_id BIGINT NOT NULL,
    modified_sequence TEXT NULL,
    experimental_mass DOUBLE PRECISION NULL,
    precursor_mz DOUBLE PRECISION NULL,
    precursor_charge SMALLINT NULL,
    intensity DOUBLE PRECISION NULL,
    score DOUBLE PRECISION NULL,
    e_value DOUBLE PRECISION NULL,
    q_value DOUBLE PRECISION NULL,
    pep DOUBLE PRECISION NULL,
    is_decoy_match BOOLEAN NOT NULL DEFAULT FALSE,
    search_engine VARCHAR(100) NULL,
    detail_path TEXT NULL,
    detail_cache JSONB NULL,
    extra_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,

    CONSTRAINT ck_identification_matches_entity_type
        CHECK (entity_type IN ('PEPTIDE', 'PROTEOFORM'))
);

COMMENT ON TABLE identification_matches IS '统一匹配表：核心适配层，统一替代 PSM 和 PrSM。';
COMMENT ON COLUMN identification_matches.match_id IS '匹配记录唯一内部 ID。';
COMMENT ON COLUMN identification_matches.dataset_id IS '所属数据集 ID。';
COMMENT ON COLUMN identification_matches.run_id IS '所属实验运行 ID，用于定位原始文件。';
COMMENT ON COLUMN identification_matches.scan_number IS '原始文件中的扫描号，与 run_id 共同定位谱图。';
COMMENT ON COLUMN identification_matches.spectrum_native_id IS '来源文件中的原生谱图 ID，作为 scan_number 的补充。';
COMMENT ON COLUMN identification_matches.retention_time IS '保留时间，建议全库统一单位。';
COMMENT ON COLUMN identification_matches.ms_level IS '质谱级别，通常鉴定结果为 MS2。';
COMMENT ON COLUMN identification_matches.entity_type IS '匹配实体类型：PEPTIDE 或 PROTEOFORM。';
COMMENT ON COLUMN identification_matches.entity_id IS '多态实体 ID，根据 entity_type 指向 peptides 或 proteoforms。';
COMMENT ON COLUMN identification_matches.modified_sequence IS '带修饰标记的序列字符串，主要供前端展示。';
COMMENT ON COLUMN identification_matches.experimental_mass IS '质谱仪实际测得的母离子质量。';
COMMENT ON COLUMN identification_matches.precursor_mz IS '母离子的质荷比。';
COMMENT ON COLUMN identification_matches.precursor_charge IS '母离子电荷数。';
COMMENT ON COLUMN identification_matches.intensity IS '特征峰丰度或绝对强度。';
COMMENT ON COLUMN identification_matches.score IS '搜索引擎给出的主打分。';
COMMENT ON COLUMN identification_matches.e_value IS 'Top-down 常用显著性指标。';
COMMENT ON COLUMN identification_matches.q_value IS '假阳性率或 q-value。';
COMMENT ON COLUMN identification_matches.pep IS '后验错误概率。';
COMMENT ON COLUMN identification_matches.is_decoy_match IS '此次匹配是否命中反库序列。';
COMMENT ON COLUMN identification_matches.search_engine IS '执行此次搜索的算法引擎，例如 MaxQuant、TopPIC。';
COMMENT ON COLUMN identification_matches.detail_path IS '详情文件路径，用于快速入库后的按需读取。';
COMMENT ON COLUMN identification_matches.detail_cache IS '按需解析后的详情缓存。';
COMMENT ON COLUMN identification_matches.extra_metadata IS '搜索软件特有的杂项打分和特征。';


CREATE TABLE IF NOT EXISTS protein_relation_mapping (
    mapping_id BIGSERIAL PRIMARY KEY,
    dataset_id BIGINT NOT NULL REFERENCES datasets(dataset_id) ON DELETE CASCADE,
    protein_id BIGINT NOT NULL REFERENCES proteins(protein_id) ON DELETE CASCADE,
    entity_type VARCHAR(30) NOT NULL,
    entity_id BIGINT NOT NULL,
    start_position INTEGER NULL,
    end_position INTEGER NULL,
    is_unique BOOLEAN NOT NULL DEFAULT FALSE,
    extra_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,

    CONSTRAINT ck_protein_relation_mapping_entity_type
        CHECK (entity_type IN ('PEPTIDE', 'PROTEOFORM'))
);

COMMENT ON TABLE protein_relation_mapping IS '统一关系映射表：处理 protein 到 peptide 或 proteoform 的多对多归属关系。';
COMMENT ON COLUMN protein_relation_mapping.mapping_id IS '映射关系唯一内部 ID。';
COMMENT ON COLUMN protein_relation_mapping.dataset_id IS '所属数据集 ID。';
COMMENT ON COLUMN protein_relation_mapping.protein_id IS '归属的基础蛋白 ID。';
COMMENT ON COLUMN protein_relation_mapping.entity_type IS '下属实体类型：PEPTIDE 或 PROTEOFORM。';
COMMENT ON COLUMN protein_relation_mapping.entity_id IS '多态实体 ID，根据 entity_type 指向 peptides 或 proteoforms。';
COMMENT ON COLUMN protein_relation_mapping.start_position IS '实体在父级基础蛋白序列中的起始位置。';
COMMENT ON COLUMN protein_relation_mapping.end_position IS '实体在父级基础蛋白序列中的结束位置。';
COMMENT ON COLUMN protein_relation_mapping.is_unique IS '该肽段或蛋白形态是否为该基础蛋白独有。';
COMMENT ON COLUMN protein_relation_mapping.extra_metadata IS '映射关系扩展字段。';


CREATE INDEX IF NOT EXISTS ix_runs_dataset_id ON runs(dataset_id);
CREATE INDEX IF NOT EXISTS ix_runs_analysis_mode ON runs(analysis_mode);
CREATE INDEX IF NOT EXISTS ix_runs_status ON runs(status);

CREATE INDEX IF NOT EXISTS ix_proteins_dataset_id ON proteins(dataset_id);
CREATE INDEX IF NOT EXISTS ix_peptides_dataset_id ON peptides(dataset_id);
CREATE INDEX IF NOT EXISTS ix_proteoforms_dataset_id ON proteoforms(dataset_id);

CREATE INDEX IF NOT EXISTS ix_identification_matches_dataset_run_scan
    ON identification_matches(dataset_id, run_id, scan_number);

CREATE INDEX IF NOT EXISTS ix_identification_matches_entity
    ON identification_matches(dataset_id, entity_type, entity_id);

CREATE INDEX IF NOT EXISTS ix_identification_matches_q_value
    ON identification_matches(q_value);

CREATE INDEX IF NOT EXISTS ix_identification_matches_e_value
    ON identification_matches(e_value);

CREATE INDEX IF NOT EXISTS ix_identification_matches_search_engine
    ON identification_matches(search_engine);

CREATE INDEX IF NOT EXISTS ix_protein_relation_mapping_dataset_id
    ON protein_relation_mapping(dataset_id);

CREATE INDEX IF NOT EXISTS ix_protein_relation_mapping_protein_id
    ON protein_relation_mapping(protein_id);

CREATE INDEX IF NOT EXISTS ix_protein_relation_mapping_entity
    ON protein_relation_mapping(dataset_id, entity_type, entity_id);

CREATE INDEX IF NOT EXISTS ix_protein_relation_mapping_is_unique
    ON protein_relation_mapping(is_unique);


CREATE TABLE IF NOT EXISTS import_jobs (
    job_id UUID PRIMARY KEY,
    status VARCHAR(20) NOT NULL,
    stage VARCHAR(40) NULL,
    stage_label TEXT NULL,
    stage_detail TEXT NULL,
    message TEXT NULL,
    error TEXT NULL,
    progress DOUBLE PRECISION NOT NULL DEFAULT 0,
    dataset_slug VARCHAR(160) NULL,
    dataset_name VARCHAR(255) NULL,
    description TEXT NULL,
    source_zip_name TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT ck_import_jobs_status
        CHECK (status IN ('queued', 'running', 'success', 'failed'))
);

COMMENT ON TABLE import_jobs IS '导入任务表：记录前端 ZIP 上传后台任务的状态、阶段、进度、关联的 dataset slug 与失败原因；支持 uvicorn 重启后继续轮询。';
COMMENT ON COLUMN import_jobs.job_id IS '任务 UUID（前端轮询凭据）。';
COMMENT ON COLUMN import_jobs.status IS '任务状态：queued / running / success / failed。';
COMMENT ON COLUMN import_jobs.stage IS '当前阶段代码：queued / extract / init / proteins / matches / finalize / success / failed。';
COMMENT ON COLUMN import_jobs.stage_label IS '阶段中文标签，前端直接展示。';
COMMENT ON COLUMN import_jobs.stage_detail IS '阶段细节，例如 "1234/4567 PrSM details"。';
COMMENT ON COLUMN import_jobs.progress IS '0..100 的真实进度百分比。';
COMMENT ON COLUMN import_jobs.dataset_slug IS '成功后绑定的数据集 slug，便于跳转。';
COMMENT ON COLUMN import_jobs.dataset_name IS '导入时填写的数据集展示名称。';
COMMENT ON COLUMN import_jobs.description IS '导入时填写的可选描述。';
COMMENT ON COLUMN import_jobs.source_zip_name IS '上传的 zip 原始文件名。';
COMMENT ON COLUMN import_jobs.created_at IS '任务创建时间。';
COMMENT ON COLUMN import_jobs.updated_at IS '任务最近一次更新时间，用于 TTL 清理。';

CREATE INDEX IF NOT EXISTS ix_import_jobs_status_updated_at
    ON import_jobs(status, updated_at DESC);

CREATE INDEX IF NOT EXISTS ix_import_jobs_dataset_slug
    ON import_jobs(dataset_slug);
