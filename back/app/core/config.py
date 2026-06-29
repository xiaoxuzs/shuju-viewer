"""Application settings loaded from .env / environment variables."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_ROOT = Path(__file__).resolve().parents[2]


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


settings = Settings()
