"""Application settings loaded from .env / environment variables."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


BACKEND_ROOT = Path(__file__).resolve().parents[2]
_ALLOWED_VIEWER_ENVIRONMENTS = {"development", "test", "production"}
_REQUIRED_TEST_ENVIRONMENT_VARIABLES = ("DATABASE_URL", "DATA_ROOT")


def _viewer_environment() -> str:
    value = os.environ.get("VIEWER_ENV", "development").strip().lower()
    if value not in _ALLOWED_VIEWER_ENVIRONMENTS:
        allowed = ", ".join(sorted(_ALLOWED_VIEWER_ENVIRONMENTS))
        raise RuntimeError(f"VIEWER_ENV must be one of: {allowed}")
    return value


def _resolved_test_data_root(path: Path) -> Path:
    try:
        resolved = path.expanduser().resolve(strict=True)
    except OSError as exc:
        raise RuntimeError(f"Test DATA_ROOT must be an existing directory: {path}") from exc
    if not resolved.is_dir():
        raise RuntimeError(f"Test DATA_ROOT must be a directory: {resolved}")

    temp_root = Path(tempfile.gettempdir()).resolve(strict=True)
    try:
        resolved.relative_to(temp_root)
    except ValueError as exc:
        raise RuntimeError(f"Test DATA_ROOT must be inside the system temporary directory: {temp_root}") from exc
    if resolved == temp_root:
        raise RuntimeError("Test DATA_ROOT must be an isolated directory, not the system temporary root itself")
    return resolved


def _validate_test_database_url(database_url: str) -> None:
    url = make_url(database_url)
    database_name = (url.database or "").strip()
    if database_name.casefold() == "universal_viewer":
        raise RuntimeError("VIEWER_ENV=test refuses to use the Universal_Viewer database")

    if url.get_backend_name() != "sqlite":
        return
    if not database_name or database_name == ":memory:":
        raise RuntimeError("VIEWER_ENV=test requires a file-based SQLite database")

    database_path = Path(database_name).expanduser()
    if not database_path.is_absolute():
        raise RuntimeError("Test SQLite DATABASE_URL must use an absolute path")
    database_parent = database_path.parent.resolve(strict=True)
    temp_root = Path(tempfile.gettempdir()).resolve(strict=True)
    try:
        database_parent.relative_to(temp_root)
    except ValueError as exc:
        raise RuntimeError(f"Test SQLite database must be inside the system temporary directory: {temp_root}") from exc


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_ROOT / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    database_url: str = Field(
        default="postgresql+psycopg://postgres:postgres@localhost:5432/histone_viewer"
    )
    data_root: Path = Field(default=BACKEND_ROOT.parent / "shuju")
    #: When True, :func:`resolve_ingest_root` results must lie under :attr:`resolved_data_root`.
    import_path_must_be_under_data_root: bool = Field(default=False)
    api_cors_origins: str = Field(default="http://localhost:5173")
    log_level: str = Field(default="INFO")
    spectrum_cache_size: int = Field(default=256)
    #: When True, ``POST /imports/pick-folder`` opens a native folder dialog on the API host (local desktop).
    import_native_folder_picker: bool = Field(default=True)
    #: Restrict the folder picker to requests from loopback (recommended when the picker is enabled).
    import_picker_loopback_only: bool = Field(default=True)
    #: Managed browser uploads are stored only below DATA_ROOT/<import_upload_dir_name>.
    import_upload_enabled: bool = Field(default=True)
    import_upload_dir_name: str = Field(default=".viewer-uploads")
    import_upload_disk_reserve_bytes: int = Field(default=5_368_709_120, ge=0)
    import_upload_max_file_bytes: int = Field(default=0, ge=0)
    import_upload_max_total_bytes: int = Field(default=0, ge=0)
    import_upload_max_files: int = Field(default=5000, ge=1)
    import_upload_chunk_bytes: int = Field(default=8_388_608, ge=1)
    #: Enable the controlled unknown-format Agent Case workflow.
    agent_import_enabled: bool = Field(default=True)
    moonshot_api_key: str | None = Field(default=None)
    moonshot_base_url: str = Field(default="https://api.moonshot.cn/v1")
    moonshot_request_timeout_seconds: int = Field(default=60, ge=1)
    agent_read_model: str = Field(default="kimi-k3")
    agent_read_max_output_tokens: int = Field(default=4096, ge=256)
    deepseek_api_key: str | None = Field(default=None)
    deepseek_base_url: str = Field(default="https://api.deepseek.com")
    deepseek_request_timeout_seconds: int = Field(default=120, ge=1)
    agent_implementation_model: str = Field(default="deepseek-v4-pro")
    agent_implementation_max_output_tokens: int = Field(default=8192, ge=256)
    #: Optional project-level FASTA used when a Bottom-Up import does not include a dataset FASTA.
    bu_default_fasta_path: Path | None = Field(default=None)
    #: Allow lazy UniProt FASTA fetches for Bottom-Up protein coverage. Keep disabled for offline deployments.
    bu_uniprot_enabled: bool = Field(default=False)
    #: Project-local root for generated Bottom-Up Fragment Match sidecars.
    bu_fragment_match_root: Path = Field(default=BACKEND_ROOT.parent / "BU- Fragment Match")
    #: Packaged PFMB bridge executable (v1 ingest today; optional ``pfmb_v2_bridge_exe`` when available).
    pfmb_bridge_exe: Path = Field(
        default=BACKEND_ROOT.parent / "Hela_DIA_v2_PFMB_delivery_20260629" / "pfmb_bridge.exe"
    )
    #: Comma-separated roots scanned for pre-built PFMB v2 sidecars (Hela-style full RT expansion).
    pfmb_v2_reference_roots: str = Field(
        default=str(BACKEND_ROOT.parent / "Hela_DIA_v2_PFMB_delivery_20260629")
    )
    #: Optional bridge with ``full_rt`` ingest; when unset, v2 sidecars come from references.
    pfmb_v2_bridge_exe: Path | None = Field(default=None)
    #: Disable only through env override; generation falls back automatically on numba cache failures.
    pfmb_bridge_disable_jit: bool = Field(default=False)
    #: Optional ThermoRawFileParser executable. Only checked when an import contains Thermo .raw files.
    thermo_raw_file_parser_exe: Path | None = Field(default=None)
    #: Per-file RAW conversion timeout.
    raw_conversion_timeout_seconds: int = Field(default=3600)
    #: Optional output dir for converted mzML. Relative paths are resolved under the selected ingest root.
    raw_conversion_output_dir: Path | None = Field(default=None)
    #: Force reconversion even when a same-stem mzML already exists.
    raw_conversion_force: bool = Field(default=False)
    #: Optional Python executable for the isolated ZP conversion environment.
    zp_worker_python: Path | None = Field(default=None)
    #: Optional PYTHONPATH entries for the isolated ZP worker, comma-separated.
    zp_worker_pythonpath: str = Field(default="")
    #: Local path containing the Viewer-managed ZP binary layer package.
    zp_engine_path: Path = Field(default=BACKEND_ROOT / "vendor" / "zp_engine")
    #: Operator-pinned binary-layer commit or release label.
    zp_binary_layer_commit: str | None = Field(default=None)
    #: Enable ZP schema bootstrap and management/debug APIs. Disable only for legacy/offline fallback.
    zp_management_enabled: bool = Field(default=True)
    #: Make ZP artifact generation part of the normal import path. Disable only for emergency fallback.
    zp_import_conversion_enabled: bool = Field(default=True)
    #: Optional storage root for committed .zp artifacts. Relative paths resolve under DATA_ROOT.
    zp_output_root: Path | None = Field(default=None)
    #: Optional temporary root for ZP conversion jobs. Relative paths resolve under ZP_OUTPUT_ROOT.
    zp_temp_root: Path | None = Field(default=None)
    #: Additional source roots allowed for ZP conversion, comma-separated. DATA_ROOT is always allowed.
    zp_allowed_source_roots: str = Field(default="")
    zp_default_format_version: int = Field(default=3, ge=1, le=3)
    zp_conversion_timeout_seconds: int = Field(default=7200, ge=1)
    zp_conversion_worker_threads: int = Field(default=6, ge=1, le=32)
    zp_conversion_max_concurrent_jobs: int = Field(default=1, ge=1)
    zp_v3_array_compression: str = Field(default="zstd")

    @property
    def pfmb_v2_reference_root_list(self) -> list[Path]:
        roots: list[Path] = []
        for part in self.pfmb_v2_reference_roots.split(","):
            text = part.strip()
            if not text:
                continue
            path = Path(text)
            if not path.is_absolute():
                path = (BACKEND_ROOT / path).resolve()
            roots.append(path)
        return roots

    def resolved_pfmb_bridge_exe(self) -> Path:
        if self.pfmb_v2_bridge_exe is not None:
            path = self.pfmb_v2_bridge_exe
            if not path.is_absolute():
                path = (BACKEND_ROOT / path).resolve()
            return path
        path = self.pfmb_bridge_exe
        if not path.is_absolute():
            path = (BACKEND_ROOT / path).resolve()
        return path

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.api_cors_origins.split(",") if origin.strip()]

    @property
    def resolved_data_root(self) -> Path:
        root = self.data_root
        if not root.is_absolute():
            root = (BACKEND_ROOT / root).resolve()
        return root

    @property
    def resolved_zp_output_root(self) -> Path:
        root = self.zp_output_root or (self.resolved_data_root / ".viewer-zp")
        if not root.is_absolute():
            root = (self.resolved_data_root / root).resolve()
        return root

    @property
    def resolved_zp_temp_root(self) -> Path:
        root = self.zp_temp_root or (self.resolved_zp_output_root / ".tmp")
        if not root.is_absolute():
            root = (self.resolved_zp_output_root / root).resolve()
        return root

    @property
    def zp_allowed_source_root_list(self) -> list[Path]:
        roots = [self.resolved_data_root]
        for part in self.zp_allowed_source_roots.split(","):
            text = part.strip()
            if not text:
                continue
            path = Path(text)
            if not path.is_absolute():
                path = (self.resolved_data_root / path).resolve()
            roots.append(path)
        return roots

    @property
    def zp_worker_pythonpath_list(self) -> list[str]:
        return [part.strip() for part in self.zp_worker_pythonpath.split(",") if part.strip()]

    def resolved_zp_engine_path(self) -> Path:
        path = self.zp_engine_path
        if not path.is_absolute():
            path = (BACKEND_ROOT / path).resolve()
        return path

    def resolved_zp_worker_python(self) -> Path | None:
        path = self.zp_worker_python
        if path is None:
            return Path(sys.executable)
        if not path.is_absolute():
            path = (BACKEND_ROOT / path).resolve()
        return path

    def resolved_zp_thermo_converter(self) -> Path | None:
        return self.thermo_raw_file_parser_exe


def load_settings() -> Settings:
    """Load application settings, failing closed for explicitly isolated tests."""
    if _viewer_environment() != "test":
        return Settings(_env_file=BACKEND_ROOT / ".env")

    missing = [
        name
        for name in _REQUIRED_TEST_ENVIRONMENT_VARIABLES
        if not os.environ.get(name, "").strip()
    ]
    if missing:
        raise RuntimeError(f"VIEWER_ENV=test requires explicit environment variables: {', '.join(missing)}")

    loaded = Settings(_env_file=None)
    _validate_test_database_url(loaded.database_url)
    loaded.data_root = _resolved_test_data_root(loaded.data_root)
    return loaded


settings = load_settings()
