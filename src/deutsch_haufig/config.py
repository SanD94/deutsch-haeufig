"""Runtime configuration for deutsch-haufig.

Values are read from environment variables with sensible defaults so the
PoC works zero-config on a fresh checkout.
"""

from __future__ import annotations

import json
import os
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


# ---------------------------------------------------------------------------
# opencode.ai provider config
# ---------------------------------------------------------------------------

OPencodeConfig = dict  # opaque dict from opencode.json


def _read_opencode_config() -> OPencodeConfig | None:
    """Read the LLM provider config from ``opencode.json`` at the project root.

    Returns ``None`` if the file doesn't exist or is unparseable.
    """
    path = PROJECT_ROOT / "opencode.json"
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    return raw


def get_dialogue_provider_config() -> dict | None:
    """Return ``{api_key, base_url, model}`` from opencode.json or ``None``.

    Looks for the first provider entry under ``$.provider.*`` with an
    ``apiKey`` field (which may reference ``{env:...}``).
    """
    cfg = _read_opencode_config()
    if not cfg:
        return None
    providers = cfg.get("provider", {})
    for _provider_name, provider_cfg in providers.items():
        options = provider_cfg.get("options", {})
        api_key_raw = options.get("apiKey", "")
        base_url = options.get("baseURL", "")
        models = provider_cfg.get("models", {})
        if not api_key_raw or not models:
            continue
        # Resolve {env:VAR_NAME} pattern
        api_key = _resolve_env_var(api_key_raw)
        if not api_key:
            continue
        # Pick first model
        model_name = next(iter(models.keys()), "")
        return {
            "api_key": api_key,
            "base_url": base_url,
            "model": model_name,
        }
    return None


def _resolve_env_var(raw: str) -> str:
    """Resolve ``{env:VAR_NAME}`` to the env var value, or return raw."""
    if raw.startswith("{env:") and raw.endswith("}"):
        var_name = raw[5:-1]
        return os.environ.get(var_name, "")
    return raw
