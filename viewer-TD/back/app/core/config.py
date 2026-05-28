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
    api_cors_origins: str = Field(default="http://localhost:6100")
    log_level: str = Field(default="INFO")
    spectrum_cache_size: int = Field(default=256)
    #: When True, ``POST /imports/pick-folder`` opens a native folder dialog on the API host (local desktop).
    import_native_folder_picker: bool = Field(default=True)
    #: Restrict the folder picker to requests from loopback (recommended when the picker is enabled).
    import_picker_loopback_only: bool = Field(default=True)
    pfmb_bridge_exe: Path = Field(
        default=BACKEND_ROOT.parent / "PFMB" / "pfmb_bridge.exe",
    )
    #: When False (default), delete ``results.pfmb`` after egress + assemble; viewer uses JSON only.
    pfmb_keep_binary_after_adapt: bool = Field(default=False)

    @property
    def project_root(self) -> Path:
        return BACKEND_ROOT.parent

    @property
    def frontend_dist(self) -> Path:
        return (self.project_root / "front" / "dist").resolve()

    @property
    def serve_frontend(self) -> bool:
        dist = self.frontend_dist
        return dist.is_dir() and (dist / "index.html").is_file()

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
