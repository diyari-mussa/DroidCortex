"""
DroidCortex — SQLAlchemy database models.
"""

from __future__ import annotations

import enum
import datetime
from typing import Optional, List

from sqlalchemy import (
    String,
    Integer,
    Float,
    Text,
    Enum,
    ForeignKey,
    DateTime,
    JSON,
    create_engine,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
    Session,
    sessionmaker,
)

from backend.config import settings, ensure_data_dirs


# ── Enums ──────────────────────────────────────────────────────


class DeviceStatus(str, enum.Enum):
    ONLINE = "online"
    IDLE = "idle"
    BUSY = "busy"
    OFFLINE = "offline"
    ERROR = "error"


class DeviceType(str, enum.Enum):
    PHYSICAL = "physical"
    EMULATOR = "emulator"


class TestRunStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    ABORTED = "aborted"


class TestMode(str, enum.Enum):
    RULES = "rules"
    AI = "ai"


class StepStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    ERROR = "error"


# ── Base ───────────────────────────────────────────────────────


class Base(DeclarativeBase):
    pass


# ── Models ─────────────────────────────────────────────────────


class Device(Base):
    """A registered Android device or emulator."""

    __tablename__ = "devices"

    serial: Mapped[str] = mapped_column(String(128), primary_key=True)
    name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    model: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    api_level: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    device_type: Mapped[DeviceType] = mapped_column(
        Enum(DeviceType), default=DeviceType.PHYSICAL
    )
    status: Mapped[DeviceStatus] = mapped_column(
        Enum(DeviceStatus), default=DeviceStatus.OFFLINE
    )
    last_seen: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime, nullable=True
    )
    properties: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # Relationships
    device_test_runs: Mapped[List["DeviceTestRun"]] = relationship(
        back_populates="device"
    )

    def __repr__(self) -> str:
        return f"<Device {self.serial} ({self.model}) [{self.status.value}]>"


class APK(Base):
    """An uploaded APK file."""

    __tablename__ = "apks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    filename: Mapped[str] = mapped_column(String(256))
    file_path: Mapped[str] = mapped_column(String(512))
    package_name: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    main_activity: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    version_name: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    version_code: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    min_sdk: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    target_sdk: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    file_size: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    uploaded_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow
    )

    # Relationships
    test_runs: Mapped[List["TestRun"]] = relationship(back_populates="apk")

    def __repr__(self) -> str:
        return f"<APK {self.package_name} ({self.filename})>"


class TestRun(Base):
    """A test run targeting one or more devices."""

    __tablename__ = "test_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    apk_id: Mapped[int] = mapped_column(ForeignKey("apks.id"))
    mode: Mapped[TestMode] = mapped_column(Enum(TestMode))
    status: Mapped[TestRunStatus] = mapped_column(
        Enum(TestRunStatus), default=TestRunStatus.PENDING
    )
    config: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    target_devices: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow
    )
    completed_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime, nullable=True
    )

    # Relationships
    apk: Mapped["APK"] = relationship(back_populates="test_runs")
    device_test_runs: Mapped[List["DeviceTestRun"]] = relationship(
        back_populates="test_run", cascade="all, delete-orphan"
    )

    @property
    def total_devices(self) -> int:
        return len(self.device_test_runs)

    @property
    def completed_devices(self) -> int:
        return sum(
            1
            for dtr in self.device_test_runs
            if dtr.status
            in (TestRunStatus.COMPLETED, TestRunStatus.FAILED, TestRunStatus.ABORTED)
        )

    def __repr__(self) -> str:
        return f"<TestRun {self.id} [{self.mode.value}] {self.status.value}>"


class DeviceTestRun(Base):
    """A test run executing on a specific device."""

    __tablename__ = "device_test_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    test_run_id: Mapped[int] = mapped_column(ForeignKey("test_runs.id"))
    device_serial: Mapped[str] = mapped_column(ForeignKey("devices.serial"))
    status: Mapped[TestRunStatus] = mapped_column(
        Enum(TestRunStatus), default=TestRunStatus.PENDING
    )
    started_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime, nullable=True
    )
    completed_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime, nullable=True
    )
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    summary: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # Relationships
    test_run: Mapped["TestRun"] = relationship(back_populates="device_test_runs")
    device: Mapped["Device"] = relationship(back_populates="device_test_runs")
    steps: Mapped[List["TestStep"]] = relationship(
        back_populates="device_test_run", cascade="all, delete-orphan",
        order_by="TestStep.step_number",
    )

    @property
    def passed_steps(self) -> int:
        return sum(1 for s in self.steps if s.status == StepStatus.PASSED)

    @property
    def failed_steps(self) -> int:
        return sum(1 for s in self.steps if s.status == StepStatus.FAILED)

    def __repr__(self) -> str:
        return f"<DeviceTestRun {self.id} device={self.device_serial} [{self.status.value}]>"


class TestStep(Base):
    """A single test step within a device test run."""

    __tablename__ = "test_steps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_test_run_id: Mapped[int] = mapped_column(
        ForeignKey("device_test_runs.id")
    )
    step_number: Mapped[int] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(64))
    params: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    expected: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    actual: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[StepStatus] = mapped_column(
        Enum(StepStatus), default=StepStatus.PENDING
    )
    screenshot_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    log_snippet: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    ai_reasoning: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime, nullable=True
    )
    completed_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime, nullable=True
    )

    # Relationships
    device_test_run: Mapped["DeviceTestRun"] = relationship(back_populates="steps")

    def __repr__(self) -> str:
        return (
            f"<TestStep {self.step_number} [{self.action}] {self.status.value}>"
        )


# ── Database engine & session ──────────────────────────────────

def get_engine():
    ensure_data_dirs()
    return create_engine(settings.database_url, echo=False)


def init_db() -> None:
    """Create all tables."""
    engine = get_engine()
    Base.metadata.create_all(engine)


def get_session_factory():
    engine = get_engine()
    return sessionmaker(bind=engine)


SessionFactory = None


def get_session() -> Session:
    global SessionFactory
    if SessionFactory is None:
        SessionFactory = get_session_factory()
    return SessionFactory()
