"""Application configuration, read from environment variables.

Values are read lazily via a small Config object rather than module-level
constants so that tests can construct isolated configurations (e.g. pointing
at a temporary database and storage directory) without mutating process-wide
environment state more than necessary.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


class ConfigError(RuntimeError):
    """Raised when required configuration is missing."""


@dataclass(frozen=True)
class Config:
    secret_key: str
    database_url: str
    score_storage_dir: str
    max_upload_mb: int
    port: int
    claude_model: str
    app_env: str
    frontend_dist_dir: str | None

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


def load_config(env: dict | None = None) -> Config:
    """Build a Config from the given environment mapping (defaults to os.environ).

    Raises ConfigError if a required variable is missing.
    """
    source = env if env is not None else os.environ

    secret_key = source.get("SECRET_KEY")
    if not secret_key:
        raise ConfigError(
            "SECRET_KEY is required (used to sign session cookies). "
            "Set it in your .env file."
        )

    database_url = source.get("DATABASE_URL", "sqlite:///nota.db")
    score_storage_dir = source.get("SCORE_STORAGE_DIR", "./data/scores")

    try:
        max_upload_mb = int(source.get("MAX_UPLOAD_MB", "10"))
    except ValueError as exc:
        raise ConfigError("MAX_UPLOAD_MB must be an integer") from exc

    try:
        port = int(source.get("PORT", "5001"))
    except ValueError as exc:
        raise ConfigError("PORT must be an integer") from exc

    claude_model = source.get("CLAUDE_MODEL", "claude-sonnet-4-6")

    app_env = source.get("APP_ENV", "development")

    # Unset (the default) leaves the app in dev mode, where Vite serves the
    # frontend and proxies /api to this process. Set it to make this process
    # also serve the built SPA directly, e.g. for a single-instance deploy.
    frontend_dist_dir = source.get("FRONTEND_DIST_DIR") or None

    return Config(
        secret_key=secret_key,
        database_url=database_url,
        score_storage_dir=score_storage_dir,
        max_upload_mb=max_upload_mb,
        port=port,
        claude_model=claude_model,
        app_env=app_env,
        frontend_dist_dir=frontend_dist_dir,
    )
