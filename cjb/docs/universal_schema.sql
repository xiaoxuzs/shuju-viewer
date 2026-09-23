--
-- PostgreSQL database dump
--

-- Dumped from database version 18.3
-- Dumped by pg_dump version 18.3
-- PG 18-only psql guard lines were removed so this schema remains usable on the project's PostgreSQL 14+ baseline.

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: public; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA IF NOT EXISTS public;


--
-- Name: SCHEMA public; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON SCHEMA public IS 'standard public schema';


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: datasets; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.datasets (
    dataset_id bigint NOT NULL,
    dataset_name character varying(255) NOT NULL,
    slug character varying(160) NOT NULL,
    analysis_mode character varying(20) NOT NULL,
    source_software character varying(100) NOT NULL,
    source_root text NOT NULL,
    status character varying(20) DEFAULT 'IMPORTED'::character varying NOT NULL,
    description text,
    capabilities jsonb DEFAULT '{}'::jsonb NOT NULL,
    extra_metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    source_dataset_fingerprint character(32),
    source_import_kind character varying(40) DEFAULT 'LEGACY'::character varying NOT NULL,
    CONSTRAINT ck_datasets_analysis_mode CHECK (((analysis_mode)::text = ANY ((ARRAY['BOTTOM_UP'::character varying, 'TOP_DOWN'::character varying])::text[]))),
    CONSTRAINT ck_datasets_status CHECK (((status)::text = ANY ((ARRAY['IMPORTED'::character varying, 'PARSING'::character varying, 'READY'::character varying, 'ERROR'::character varying])::text[])))
);


--
-- Name: TABLE datasets; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.datasets IS '数据集表：一批导入数据的总入口，用于区分不同项目、实验包或导入批次。';


--
-- Name: COLUMN datasets.dataset_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.datasets.dataset_id IS '数据集唯一内部 ID。';


--
-- Name: COLUMN datasets.dataset_name; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.datasets.dataset_name IS '数据集展示名称，例如 MZ20160222DS_histone48_html。';


--
-- Name: COLUMN datasets.slug; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.datasets.slug IS '数据集唯一短标识，用于 URL 和程序查询。';


--
-- Name: COLUMN datasets.analysis_mode; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.datasets.analysis_mode IS '默认分析模式：BOTTOM_UP 或 TOP_DOWN。';


--
-- Name: COLUMN datasets.source_software; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.datasets.source_software IS '来源软件，例如 TopPIC_TopFD、MaxQuant、FragPipe。';


--
-- Name: COLUMN datasets.source_root; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.datasets.source_root IS '数据集根目录路径。';


--
-- Name: COLUMN datasets.status; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.datasets.status IS '数据集处理状态：IMPORTED、PARSING、READY、ERROR。';


--
-- Name: COLUMN datasets.description; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.datasets.description IS '数据集说明。';


--
-- Name: COLUMN datasets.capabilities; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.datasets.capabilities IS '能力声明，例如是否有 MS1、MS2、PrSM、谱图文件。';


--
-- Name: COLUMN datasets.extra_metadata; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.datasets.extra_metadata IS '额外元数据。';


--
-- Name: COLUMN datasets.created_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.datasets.created_at IS '数据集创建或导入时间。';


--
-- Name: COLUMN datasets.source_dataset_fingerprint; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.datasets.source_dataset_fingerprint IS '数据集源目录元数据 manifest 的 MD5（32 位小写 hex），不是文件内容哈希。';


--
-- Name: COLUMN datasets.source_import_kind; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.datasets.source_import_kind IS '用户选择的数据解释类型；与 source_dataset_fingerprint 共同构成重复识别键。';


--
-- Name: datasets_dataset_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.datasets_dataset_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: datasets_dataset_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.datasets_dataset_id_seq OWNED BY public.datasets.dataset_id;


--
-- Name: identification_matches; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.identification_matches (
    match_id bigint NOT NULL,
    dataset_id bigint NOT NULL,
    run_id bigint NOT NULL,
    scan_number integer NOT NULL,
    spectrum_native_id character varying(255),
    retention_time double precision,
    ms_level smallint DEFAULT 2 NOT NULL,
    entity_type character varying(30) NOT NULL,
    entity_id bigint NOT NULL,
    modified_sequence text,
    experimental_mass double precision,
    precursor_mz double precision,
    precursor_charge smallint,
    intensity double precision,
    score double precision,
    e_value double precision,
    q_value double precision,
    pep double precision,
    is_decoy_match boolean DEFAULT false NOT NULL,
    search_engine character varying(100),
    detail_path text,
    detail_cache jsonb,
    extra_metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    CONSTRAINT ck_identification_matches_entity_type CHECK (((entity_type)::text = ANY ((ARRAY['PEPTIDE'::character varying, 'PROTEOFORM'::character varying])::text[])))
);


--
-- Name: TABLE identification_matches; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.identification_matches IS '统一匹配表：核心适配层，统一替代 PSM 和 PrSM。';


--
-- Name: COLUMN identification_matches.match_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.identification_matches.match_id IS '匹配记录唯一内部 ID。';


--
-- Name: COLUMN identification_matches.dataset_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.identification_matches.dataset_id IS '所属数据集 ID。';


--
-- Name: COLUMN identification_matches.run_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.identification_matches.run_id IS '所属实验运行 ID，用于定位原始文件。';


--
-- Name: COLUMN identification_matches.scan_number; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.identification_matches.scan_number IS '原始文件中的扫描号，与 run_id 共同定位谱图。';


--
-- Name: COLUMN identification_matches.spectrum_native_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.identification_matches.spectrum_native_id IS '来源文件中的原生谱图 ID，作为 scan_number 的补充。';


--
-- Name: COLUMN identification_matches.retention_time; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.identification_matches.retention_time IS '保留时间，建议全库统一单位。';


--
-- Name: COLUMN identification_matches.ms_level; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.identification_matches.ms_level IS '质谱级别，通常鉴定结果为 MS2。';


--
-- Name: COLUMN identification_matches.entity_type; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.identification_matches.entity_type IS '匹配实体类型：PEPTIDE 或 PROTEOFORM。';


--
-- Name: COLUMN identification_matches.entity_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.identification_matches.entity_id IS '多态实体 ID，根据 entity_type 指向 peptides 或 proteoforms。';


--
-- Name: COLUMN identification_matches.modified_sequence; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.identification_matches.modified_sequence IS '带修饰标记的序列字符串，主要供前端展示。';


--
-- Name: COLUMN identification_matches.experimental_mass; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.identification_matches.experimental_mass IS '质谱仪实际测得的母离子质量。';


--
-- Name: COLUMN identification_matches.precursor_mz; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.identification_matches.precursor_mz IS '母离子的质荷比。';


--
-- Name: COLUMN identification_matches.precursor_charge; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.identification_matches.precursor_charge IS '母离子电荷数。';


--
-- Name: COLUMN identification_matches.intensity; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.identification_matches.intensity IS '特征峰丰度或绝对强度。';


--
-- Name: COLUMN identification_matches.score; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.identification_matches.score IS '搜索引擎给出的主打分。';


--
-- Name: COLUMN identification_matches.e_value; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.identification_matches.e_value IS 'Top-down 常用显著性指标。';


--
-- Name: COLUMN identification_matches.q_value; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.identification_matches.q_value IS '假阳性率或 q-value。';


--
-- Name: COLUMN identification_matches.pep; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.identification_matches.pep IS '后验错误概率。';


--
-- Name: COLUMN identification_matches.is_decoy_match; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.identification_matches.is_decoy_match IS '此次匹配是否命中反库序列。';


--
-- Name: COLUMN identification_matches.search_engine; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.identification_matches.search_engine IS '执行此次搜索的算法引擎，例如 MaxQuant、TopPIC。';


--
-- Name: COLUMN identification_matches.detail_path; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.identification_matches.detail_path IS '详情文件路径，用于快速入库后的按需读取。';


--
-- Name: COLUMN identification_matches.detail_cache; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.identification_matches.detail_cache IS '按需解析后的详情缓存。';


--
-- Name: COLUMN identification_matches.extra_metadata; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.identification_matches.extra_metadata IS '搜索软件特有的杂项打分和特征。';


--
-- Name: identification_matches_match_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.identification_matches_match_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: identification_matches_match_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.identification_matches_match_id_seq OWNED BY public.identification_matches.match_id;


--
-- Name: import_jobs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.import_jobs (
    job_id uuid NOT NULL,
    status character varying(20) NOT NULL,
    stage character varying(40),
    stage_label text,
    stage_detail text,
    message text,
    error text,
    progress double precision DEFAULT 0 NOT NULL,
    dataset_slug character varying(160),
    dataset_name character varying(255),
    description text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    source_path text,
    import_type character varying(40),
    CONSTRAINT ck_import_jobs_status CHECK (((status)::text = ANY ((ARRAY['queued'::character varying, 'running'::character varying, 'success'::character varying, 'failed'::character varying])::text[])))
);


--
-- Name: peptides; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.peptides (
    peptide_id bigint NOT NULL,
    dataset_id bigint NOT NULL,
    sequence character varying(1000) NOT NULL,
    theoretical_mass double precision,
    length integer,
    missed_cleavages smallint,
    extra_metadata jsonb DEFAULT '{}'::jsonb NOT NULL
);


--
-- Name: TABLE peptides; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.peptides IS '肽段表：Bottom-up 专用实体，记录不含修饰的纯氨基酸肽段。';


--
-- Name: COLUMN peptides.peptide_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.peptides.peptide_id IS '肽段唯一内部 ID。';


--
-- Name: COLUMN peptides.dataset_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.peptides.dataset_id IS '所属数据集 ID。';


--
-- Name: COLUMN peptides.sequence; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.peptides.sequence IS '纯氨基酸序列，不包含修饰。';


--
-- Name: COLUMN peptides.theoretical_mass; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.peptides.theoretical_mass IS '理论单同位素质量。';


--
-- Name: COLUMN peptides.length; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.peptides.length IS '肽段序列长度。';


--
-- Name: COLUMN peptides.missed_cleavages; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.peptides.missed_cleavages IS '酶切过程中的漏切位点数量。';


--
-- Name: COLUMN peptides.extra_metadata; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.peptides.extra_metadata IS '肽段相关扩展属性。';


--
-- Name: peptides_peptide_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.peptides_peptide_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: peptides_peptide_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.peptides_peptide_id_seq OWNED BY public.peptides.peptide_id;


--
-- Name: protein_relation_mapping; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.protein_relation_mapping (
    mapping_id bigint NOT NULL,
    dataset_id bigint NOT NULL,
    protein_id bigint NOT NULL,
    entity_type character varying(30) NOT NULL,
    entity_id bigint NOT NULL,
    start_position integer,
    end_position integer,
    is_unique boolean DEFAULT false NOT NULL,
    extra_metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    CONSTRAINT ck_protein_relation_mapping_entity_type CHECK (((entity_type)::text = ANY ((ARRAY['PEPTIDE'::character varying, 'PROTEOFORM'::character varying])::text[])))
);


--
-- Name: TABLE protein_relation_mapping; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.protein_relation_mapping IS '统一关系映射表：处理 protein 到 peptide 或 proteoform 的多对多归属关系。';


--
-- Name: COLUMN protein_relation_mapping.mapping_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.protein_relation_mapping.mapping_id IS '映射关系唯一内部 ID。';


--
-- Name: COLUMN protein_relation_mapping.dataset_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.protein_relation_mapping.dataset_id IS '所属数据集 ID。';


--
-- Name: COLUMN protein_relation_mapping.protein_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.protein_relation_mapping.protein_id IS '归属的基础蛋白 ID。';


--
-- Name: COLUMN protein_relation_mapping.entity_type; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.protein_relation_mapping.entity_type IS '下属实体类型：PEPTIDE 或 PROTEOFORM。';


--
-- Name: COLUMN protein_relation_mapping.entity_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.protein_relation_mapping.entity_id IS '多态实体 ID，根据 entity_type 指向 peptides 或 proteoforms。';


--
-- Name: COLUMN protein_relation_mapping.start_position; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.protein_relation_mapping.start_position IS '实体在父级基础蛋白序列中的起始位置。';


--
-- Name: COLUMN protein_relation_mapping.end_position; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.protein_relation_mapping.end_position IS '实体在父级基础蛋白序列中的结束位置。';


--
-- Name: COLUMN protein_relation_mapping.is_unique; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.protein_relation_mapping.is_unique IS '该肽段或蛋白形态是否为该基础蛋白独有。';


--
-- Name: COLUMN protein_relation_mapping.extra_metadata; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.protein_relation_mapping.extra_metadata IS '映射关系扩展字段。';


--
-- Name: protein_relation_mapping_mapping_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.protein_relation_mapping_mapping_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: protein_relation_mapping_mapping_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.protein_relation_mapping_mapping_id_seq OWNED BY public.protein_relation_mapping.mapping_id;


--
-- Name: proteins; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.proteins (
    protein_id bigint NOT NULL,
    dataset_id bigint NOT NULL,
    accession character varying(255) NOT NULL,
    gene_name character varying(255),
    description text,
    base_sequence text,
    is_decoy boolean DEFAULT false NOT NULL,
    extra_metadata jsonb DEFAULT '{}'::jsonb NOT NULL
);


--
-- Name: TABLE proteins; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.proteins IS '基础蛋白表：Bottom-up 和 Top-down 共用的蛋白生物学根节点。';


--
-- Name: COLUMN proteins.protein_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.proteins.protein_id IS '蛋白唯一内部 ID。';


--
-- Name: COLUMN proteins.dataset_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.proteins.dataset_id IS '所属数据集 ID。';


--
-- Name: COLUMN proteins.accession; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.proteins.accession IS '公共数据库唯一编号，例如 UniProt Accession。';


--
-- Name: COLUMN proteins.gene_name; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.proteins.gene_name IS '蛋白对应的基因名称。';


--
-- Name: COLUMN proteins.description; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.proteins.description IS '蛋白质详细功能描述或全称。';


--
-- Name: COLUMN proteins.base_sequence; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.proteins.base_sequence IS '完整、未修饰的理论氨基酸序列。';


--
-- Name: COLUMN proteins.is_decoy; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.proteins.is_decoy IS '是否为反向或随机诱饵蛋白。';


--
-- Name: COLUMN proteins.extra_metadata; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.proteins.extra_metadata IS '参考数据库或来源软件带来的扩展属性。';


--
-- Name: proteins_protein_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.proteins_protein_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: proteins_protein_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.proteins_protein_id_seq OWNED BY public.proteins.protein_id;


--
-- Name: proteoforms; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.proteoforms (
    proteoform_id bigint NOT NULL,
    dataset_id bigint NOT NULL,
    modifications jsonb DEFAULT '[]'::jsonb NOT NULL,
    start_res integer,
    end_res integer,
    theoretical_mass double precision,
    extra_metadata jsonb DEFAULT '{}'::jsonb NOT NULL
);


--
-- Name: TABLE proteoforms; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.proteoforms IS '蛋白形态表：Top-down 专用实体，记录 PTMs、截短和质量变化的蛋白形态。';


--
-- Name: COLUMN proteoforms.proteoform_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.proteoforms.proteoform_id IS '蛋白形态唯一内部 ID。';


--
-- Name: COLUMN proteoforms.dataset_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.proteoforms.dataset_id IS '所属数据集 ID。';


--
-- Name: COLUMN proteoforms.modifications; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.proteoforms.modifications IS 'PTMs 信息，包括修饰名称、位置、质量偏移等。';


--
-- Name: COLUMN proteoforms.start_res; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.proteoforms.start_res IS '该形态在基础蛋白序列中的 N 端起始位置。';


--
-- Name: COLUMN proteoforms.end_res; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.proteoforms.end_res IS '该形态在基础蛋白序列中的 C 端结束位置。';


--
-- Name: COLUMN proteoforms.theoretical_mass; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.proteoforms.theoretical_mass IS '蛋白形态理论精确质量。';


--
-- Name: COLUMN proteoforms.extra_metadata; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.proteoforms.extra_metadata IS '其他形态衍生属性。';


--
-- Name: proteoforms_proteoform_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.proteoforms_proteoform_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: proteoforms_proteoform_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.proteoforms_proteoform_id_seq OWNED BY public.proteoforms.proteoform_id;


--
-- Name: runs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.runs (
    run_id bigint NOT NULL,
    dataset_id bigint NOT NULL,
    file_path text NOT NULL,
    file_name character varying(255) NOT NULL,
    analysis_mode character varying(20) NOT NULL,
    software character varying(100),
    status character varying(20) DEFAULT 'IMPORTED'::character varying NOT NULL,
    instrument_metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    sample_metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    run_metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    CONSTRAINT ck_runs_analysis_mode CHECK (((analysis_mode)::text = ANY ((ARRAY['BOTTOM_UP'::character varying, 'TOP_DOWN'::character varying])::text[]))),
    CONSTRAINT ck_runs_status CHECK (((status)::text = ANY ((ARRAY['IMPORTED'::character varying, 'PARSING'::character varying, 'READY'::character varying, 'ERROR'::character varying])::text[])))
);


--
-- Name: TABLE runs; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.runs IS '实验文件表：记录一个数据集下的原始文件、标准化文件或一次上机运行。';


--
-- Name: COLUMN runs.run_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.runs.run_id IS '实验运行唯一内部 ID。';


--
-- Name: COLUMN runs.dataset_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.runs.dataset_id IS '所属数据集 ID。';


--
-- Name: COLUMN runs.file_path; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.runs.file_path IS '原始质谱文件或标准化文件在服务器上的物理路径。';


--
-- Name: COLUMN runs.file_name; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.runs.file_name IS '原始文件名或目录名，方便前端展示。';


--
-- Name: COLUMN runs.analysis_mode; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.runs.analysis_mode IS '分析模式：BOTTOM_UP 或 TOP_DOWN。';


--
-- Name: COLUMN runs.software; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.runs.software IS '来源软件，用于区分不同软件的专属字段。';


--
-- Name: COLUMN runs.status; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.runs.status IS '当前处理状态：IMPORTED、PARSING、READY、ERROR。';


--
-- Name: COLUMN runs.instrument_metadata; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.runs.instrument_metadata IS '质谱仪信息、采集参数等。';


--
-- Name: COLUMN runs.sample_metadata; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.runs.sample_metadata IS '样本信息，例如样本名、分组、重复编号。';


--
-- Name: COLUMN runs.created_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.runs.created_at IS '记录创建或数据导入时间。';


--
-- Name: runs_run_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.runs_run_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: runs_run_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.runs_run_id_seq OWNED BY public.runs.run_id;


--
-- Name: datasets dataset_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.datasets ALTER COLUMN dataset_id SET DEFAULT nextval('public.datasets_dataset_id_seq'::regclass);


--
-- Name: identification_matches match_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.identification_matches ALTER COLUMN match_id SET DEFAULT nextval('public.identification_matches_match_id_seq'::regclass);


--
-- Name: peptides peptide_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.peptides ALTER COLUMN peptide_id SET DEFAULT nextval('public.peptides_peptide_id_seq'::regclass);


--
-- Name: protein_relation_mapping mapping_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.protein_relation_mapping ALTER COLUMN mapping_id SET DEFAULT nextval('public.protein_relation_mapping_mapping_id_seq'::regclass);


--
-- Name: proteins protein_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.proteins ALTER COLUMN protein_id SET DEFAULT nextval('public.proteins_protein_id_seq'::regclass);


--
-- Name: proteoforms proteoform_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.proteoforms ALTER COLUMN proteoform_id SET DEFAULT nextval('public.proteoforms_proteoform_id_seq'::regclass);


--
-- Name: runs run_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runs ALTER COLUMN run_id SET DEFAULT nextval('public.runs_run_id_seq'::regclass);


--
-- Name: datasets datasets_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.datasets
    ADD CONSTRAINT datasets_pkey PRIMARY KEY (dataset_id);


--
-- Name: datasets datasets_slug_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.datasets
    ADD CONSTRAINT datasets_slug_key UNIQUE (slug);


--
-- Name: identification_matches identification_matches_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.identification_matches
    ADD CONSTRAINT identification_matches_pkey PRIMARY KEY (match_id);


--
-- Name: import_jobs import_jobs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.import_jobs
    ADD CONSTRAINT import_jobs_pkey PRIMARY KEY (job_id);


--
-- Name: peptides peptides_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.peptides
    ADD CONSTRAINT peptides_pkey PRIMARY KEY (peptide_id);


--
-- Name: protein_relation_mapping protein_relation_mapping_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.protein_relation_mapping
    ADD CONSTRAINT protein_relation_mapping_pkey PRIMARY KEY (mapping_id);


--
-- Name: proteins proteins_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.proteins
    ADD CONSTRAINT proteins_pkey PRIMARY KEY (protein_id);


--
-- Name: proteoforms proteoforms_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.proteoforms
    ADD CONSTRAINT proteoforms_pkey PRIMARY KEY (proteoform_id);


--
-- Name: runs runs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runs
    ADD CONSTRAINT runs_pkey PRIMARY KEY (run_id);


--
-- Name: peptides uq_peptides_dataset_sequence; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.peptides
    ADD CONSTRAINT uq_peptides_dataset_sequence UNIQUE (dataset_id, sequence);


--
-- Name: proteins uq_proteins_dataset_accession_decoy; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.proteins
    ADD CONSTRAINT uq_proteins_dataset_accession_decoy UNIQUE (dataset_id, accession, is_decoy);


--
-- Name: idx_im_dataset_q; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_im_dataset_q ON public.identification_matches USING btree (dataset_id, q_value);


--
-- Name: idx_im_dataset_run; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_im_dataset_run ON public.identification_matches USING btree (dataset_id, run_id);


--
-- Name: ix_identification_matches_dataset_run_scan; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_identification_matches_dataset_run_scan ON public.identification_matches USING btree (dataset_id, run_id, scan_number);


--
-- Name: ix_identification_matches_e_value; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_identification_matches_e_value ON public.identification_matches USING btree (e_value);


--
-- Name: ix_identification_matches_entity; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_identification_matches_entity ON public.identification_matches USING btree (dataset_id, entity_type, entity_id);


--
-- Name: ix_identification_matches_q_value; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_identification_matches_q_value ON public.identification_matches USING btree (q_value);


--
-- Name: ix_identification_matches_search_engine; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_identification_matches_search_engine ON public.identification_matches USING btree (search_engine);


--
-- Name: ix_import_jobs_dataset_slug; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_import_jobs_dataset_slug ON public.import_jobs USING btree (dataset_slug);


--
-- Name: ix_import_jobs_status_updated_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_import_jobs_status_updated_at ON public.import_jobs USING btree (status, updated_at DESC);


--
-- Name: ix_peptides_dataset_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_peptides_dataset_id ON public.peptides USING btree (dataset_id);


--
-- Name: ix_protein_relation_mapping_dataset_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_protein_relation_mapping_dataset_id ON public.protein_relation_mapping USING btree (dataset_id);


--
-- Name: ix_protein_relation_mapping_entity; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_protein_relation_mapping_entity ON public.protein_relation_mapping USING btree (dataset_id, entity_type, entity_id);


--
-- Name: ix_protein_relation_mapping_is_unique; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_protein_relation_mapping_is_unique ON public.protein_relation_mapping USING btree (is_unique);


--
-- Name: ix_protein_relation_mapping_protein_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_protein_relation_mapping_protein_id ON public.protein_relation_mapping USING btree (protein_id);


--
-- Name: ix_proteins_dataset_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_proteins_dataset_id ON public.proteins USING btree (dataset_id);


--
-- Name: ix_proteoforms_dataset_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_proteoforms_dataset_id ON public.proteoforms USING btree (dataset_id);


--
-- Name: ix_runs_analysis_mode; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_runs_analysis_mode ON public.runs USING btree (analysis_mode);


--
-- Name: ix_runs_dataset_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_runs_dataset_id ON public.runs USING btree (dataset_id);


--
-- Name: ix_runs_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_runs_status ON public.runs USING btree (status);


--
-- Name: uq_datasets_source_fingerprint_import_kind; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_datasets_source_fingerprint_import_kind ON public.datasets USING btree (source_dataset_fingerprint, source_import_kind) WHERE (source_dataset_fingerprint IS NOT NULL);


--
-- Name: identification_matches identification_matches_dataset_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.identification_matches
    ADD CONSTRAINT identification_matches_dataset_id_fkey FOREIGN KEY (dataset_id) REFERENCES public.datasets(dataset_id) ON DELETE CASCADE;


--
-- Name: identification_matches identification_matches_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.identification_matches
    ADD CONSTRAINT identification_matches_run_id_fkey FOREIGN KEY (run_id) REFERENCES public.runs(run_id) ON DELETE CASCADE;


--
-- Name: peptides peptides_dataset_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.peptides
    ADD CONSTRAINT peptides_dataset_id_fkey FOREIGN KEY (dataset_id) REFERENCES public.datasets(dataset_id) ON DELETE CASCADE;


--
-- Name: protein_relation_mapping protein_relation_mapping_dataset_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.protein_relation_mapping
    ADD CONSTRAINT protein_relation_mapping_dataset_id_fkey FOREIGN KEY (dataset_id) REFERENCES public.datasets(dataset_id) ON DELETE CASCADE;


--
-- Name: protein_relation_mapping protein_relation_mapping_protein_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.protein_relation_mapping
    ADD CONSTRAINT protein_relation_mapping_protein_id_fkey FOREIGN KEY (protein_id) REFERENCES public.proteins(protein_id) ON DELETE CASCADE;


--
-- Name: proteins proteins_dataset_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.proteins
    ADD CONSTRAINT proteins_dataset_id_fkey FOREIGN KEY (dataset_id) REFERENCES public.datasets(dataset_id) ON DELETE CASCADE;


--
-- Name: proteoforms proteoforms_dataset_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.proteoforms
    ADD CONSTRAINT proteoforms_dataset_id_fkey FOREIGN KEY (dataset_id) REFERENCES public.datasets(dataset_id) ON DELETE CASCADE;


--
-- Name: runs runs_dataset_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runs
    ADD CONSTRAINT runs_dataset_id_fkey FOREIGN KEY (dataset_id) REFERENCES public.datasets(dataset_id) ON DELETE CASCADE;


--
-- PostgreSQL database dump complete
--
