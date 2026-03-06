"""
DroidCortex — API Routes: Configuration.
"""

from __future__ import annotations

from fastapi import APIRouter

from backend.config import settings
from backend.models.schemas import AppConfigOut, AppConfigUpdate

router = APIRouter(prefix="/api/config", tags=["config"])


@router.get("", response_model=AppConfigOut)
async def get_config():
    """Get current application configuration."""
    return AppConfigOut(
        max_parallel_devices=settings.max_parallel_devices,
        default_ai_provider=settings.default_ai_provider,
        default_ai_model=settings.default_ai_model,
        device_poll_interval=settings.device_poll_interval,
        test_step_timeout=settings.test_step_timeout,
        ai_max_steps=settings.ai_max_steps,
    )


@router.patch("", response_model=AppConfigOut)
async def update_config(body: AppConfigUpdate):
    """Update application configuration (runtime only, doesn't persist to .env)."""
    if body.max_parallel_devices is not None:
        settings.max_parallel_devices = body.max_parallel_devices
    if body.default_ai_provider is not None:
        settings.default_ai_provider = body.default_ai_provider
    if body.default_ai_model is not None:
        settings.default_ai_model = body.default_ai_model
    if body.device_poll_interval is not None:
        settings.device_poll_interval = body.device_poll_interval
    if body.test_step_timeout is not None:
        settings.test_step_timeout = body.test_step_timeout
    if body.ai_max_steps is not None:
        settings.ai_max_steps = body.ai_max_steps

    return AppConfigOut(
        max_parallel_devices=settings.max_parallel_devices,
        default_ai_provider=settings.default_ai_provider,
        default_ai_model=settings.default_ai_model,
        device_poll_interval=settings.device_poll_interval,
        test_step_timeout=settings.test_step_timeout,
        ai_max_steps=settings.ai_max_steps,
    )
