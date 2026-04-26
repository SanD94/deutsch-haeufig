"""Runtime configuration for deutsch-haufig.

Values are read from environment variables with sensible defaults so the
PoC works zero-config on a fresh checkout.
"""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Process-wide settings."""

    model_config = SettingsConfigDict(
        env_prefix="DEUTSCH_HAUFIG_",
        env_file=".env",
        extra="ignore",
    )

    database_url: str = f"sqlite:///{PROJECT_ROOT / 'app.db'}"
    data_dir: Path = PROJECT_ROOT / "data"
    dwds_cache_dir: Path = PROJECT_ROOT / "data" / "dwds_cache"


settings = Settings()
