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
    api_cors_origins: str = Field(default="http://localhost:5173")
    log_level: str = Field(default="INFO")
    spectrum_cache_size: int = Field(default=256)

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
