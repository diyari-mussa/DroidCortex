"""
DroidCortex — Pydantic schemas for API request/response validation.
"""

from __future__ import annotations

import datetime
from typing import Optional, List, Any
from enum import Enum

from pydantic import BaseModel, Field


# ── Enums mirrored from DB ─────────────────────────────────────


class DeviceStatusSchema(str, Enum):
    ONLINE = "online"
    IDLE = "idle"
    BUSY = "busy"
    OFFLINE = "offline"
    ERROR = "error"


class TestModeSchema(str, Enum):
    RULES = "rules"
    AI = "ai"


class TestRunStatusSchema(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    ABORTED = "aborted"


class StepStatusSchema(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    ERROR = "error"


# ── Device ─────────────────────────────────────────────────────


class DeviceOut(BaseModel):
    serial: str
    name: Optional[str] = None
    model: Optional[str] = None
    api_level: Optional[int] = None
    device_type: str = "physical"
    status: DeviceStatusSchema
    last_seen: Optional[datetime.datetime] = None

    model_config = {"from_attributes": True}


class CommandRequest(BaseModel):
    command: str = Field(..., description="Command type or ADB shell command to execute")
    args: Optional[dict] = Field(None, description="Optional arguments for the command")


class CommandResponse(BaseModel):
    success: bool
    output: str
    error: Optional[str] = None


# ── APK ────────────────────────────────────────────────────────


class APKOut(BaseModel):
    id: int
    filename: str
    package_name: Optional[str] = None
    main_activity: Optional[str] = None
    version_name: Optional[str] = None
    version_code: Optional[int] = None
    min_sdk: Optional[int] = None
    target_sdk: Optional[int] = None
    file_size: Optional[int] = None
    uploaded_at: datetime.datetime

    model_config = {"from_attributes": True}


# ── Test Run ───────────────────────────────────────────────────


class TestStepDef(BaseModel):
    """A single step definition in a rule-based test script."""

    action: str
    params: dict[str, Any] = Field(default_factory=dict)
    expected: Optional[str] = None
    timeout: int = 30


class AIConfig(BaseModel):
    """Configuration for AI agent mode."""

    provider: Optional[str] = None
    model: Optional[str] = None
    goal: str = "Explore the app and verify it works correctly"
    max_steps: int = 50


class TestRunCreate(BaseModel):
    """Request body to create a new test run."""

    name: Optional[str] = None
    apk_id: int
    mode: TestModeSchema
    target_devices: List[str] = Field(
        default_factory=list,
        description='List of device serials, or empty for "all idle devices"',
    )
    steps: List[TestStepDef] = Field(
        default_factory=list, description="Steps for rule-based mode"
    )
    ai_config: Optional[AIConfig] = None


class TestStepOut(BaseModel):
    id: int
    step_number: int
    action: str
    params: Optional[dict] = None
    expected: Optional[str] = None
    actual: Optional[str] = None
    status: StepStatusSchema
    screenshot_path: Optional[str] = None
    log_snippet: Optional[str] = None
    duration_ms: Optional[int] = None
    ai_reasoning: Optional[str] = None
    started_at: Optional[datetime.datetime] = None
    completed_at: Optional[datetime.datetime] = None

    model_config = {"from_attributes": True}


class DeviceTestRunOut(BaseModel):
    id: int
    device_serial: str
    status: TestRunStatusSchema
    started_at: Optional[datetime.datetime] = None
    completed_at: Optional[datetime.datetime] = None
    error_message: Optional[str] = None
    summary: Optional[dict] = None
    steps: List[TestStepOut] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class TestRunOut(BaseModel):
    id: int
    name: Optional[str] = None
    apk_id: int
    mode: TestModeSchema
    status: TestRunStatusSchema
    config: Optional[dict] = None
    target_devices: Optional[list] = None
    created_at: datetime.datetime
    completed_at: Optional[datetime.datetime] = None
    device_test_runs: List[DeviceTestRunOut] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class TestRunSummary(BaseModel):
    id: int
    name: Optional[str] = None
    mode: TestModeSchema
    status: TestRunStatusSchema
    total_devices: int = 0
    completed_devices: int = 0
    created_at: datetime.datetime
    completed_at: Optional[datetime.datetime] = None

    model_config = {"from_attributes": True}


# ── Config ─────────────────────────────────────────────────────


class AppConfigOut(BaseModel):
    max_parallel_devices: int
    default_ai_provider: str
    default_ai_model: str
    device_poll_interval: float
    test_step_timeout: int
    ai_max_steps: int


class AppConfigUpdate(BaseModel):
    max_parallel_devices: Optional[int] = None
    default_ai_provider: Optional[str] = None
    default_ai_model: Optional[str] = None
    device_poll_interval: Optional[float] = None
    test_step_timeout: Optional[int] = None
    ai_max_steps: Optional[int] = None
