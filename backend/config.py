"""
DroidCortex — Application configuration.
Loads settings from environment variables / .env file.
"""

from __future__ import annotations

import os
from pathlib import Path
from pydantic_settings import BaseSettings
from pydantic import Field

# Project root is two levels up from this file (backend/config.py -> DroidCortex/)
PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Global application settings, populated from .env or env vars."""

    # ── Redis ──────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"

    # ── Database ───────────────────────────────────────────
    database_url: str = Field(
        default=f"sqlite:///{PROJECT_ROOT / 'data' / 'db' / 'droidcortex.db'}"
    )

    # ── ADB ────────────────────────────────────────────────
    adb_path: str = "adb"

    # ── Storage paths ──────────────────────────────────────
    apk_storage_path: str = str(PROJECT_ROOT / "data" / "apks")
    screenshot_storage_path: str = str(PROJECT_ROOT / "data" / "screenshots")

    # ── Concurrency ────────────────────────────────────────
    max_parallel_devices: int = 3

    # ── AI Provider keys ───────────────────────────────────
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    google_api_key: str = ""

    # ── AI defaults ────────────────────────────────────────
    default_ai_provider: str = "openai"        # openai | anthropic | google
    default_ai_model: str = "gpt-4o"

    # ── Server ─────────────────────────────────────────────
    host: str = "0.0.0.0"
    port: int = 8000
    frontend_url: str = "http://localhost:5173"

    # ── Misc ───────────────────────────────────────────────
    device_poll_interval: float = 5.0          # seconds between adb device scans
    test_step_timeout: int = 30                # default per-step timeout (seconds)
    ai_max_steps: int = 50                     # max AI agent steps before stopping

    model_config = {
        "env_file": str(PROJECT_ROOT / ".env"),
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


# Singleton — import this everywhere
settings = Settings()


def ensure_data_dirs() -> None:
    """Create required data directories if they don't exist."""
    for p in (
        settings.apk_storage_path,
        settings.screenshot_storage_path,
        os.path.dirname(settings.database_url.replace("sqlite:///", "")),
    ):
        Path(p).mkdir(parents=True, exist_ok=True)
