"""
DroidCortex — Device Pool Manager.
Tracks connected Android devices, manages their lifecycle, and allocates
them to test runs.
"""

from __future__ import annotations

import asyncio
import datetime
import threading
from typing import Optional

import structlog

from backend.config import settings
from backend.models.database import (
    Device,
    DeviceStatus,
    DeviceType,
    get_session,
)
from backend.services.adb_service import ADBService, DeviceInfo, adb_service

logger = structlog.get_logger(__name__)


class DevicePoolManager:
    """
    Maintains an in-memory registry of devices, periodically synced with ADB.
    Provides acquire/release semantics for the orchestrator.
    """

    def __init__(self, adb: ADBService | None = None):
        self.adb = adb or adb_service
        self._lock = threading.Lock()
        self._devices: dict[str, DeviceInfo] = {}
        self._status: dict[str, DeviceStatus] = {}
        self._polling = False
        self._poll_task: asyncio.Task | None = None
        self._event_callbacks: list = []

    # ── Public API ─────────────────────────────────────────

    def get_all_devices(self) -> list[dict]:
        """Return all known devices with status."""
        with self._lock:
            result = []
            for serial, info in self._devices.items():
                status = self._status.get(serial, DeviceStatus.OFFLINE)
                result.append(
                    {
                        "serial": serial,
                        "model": info.model,
                        "api_level": info.api_level,
                        "device_type": "emulator" if info.is_emulator else "physical",
                        "status": status.value,
                        "state": info.state,
                    }
                )
            return result

    def get_device(self, serial: str) -> dict | None:
        """Get a single device's info."""
        with self._lock:
            info = self._devices.get(serial)
            if not info:
                return None
            status = self._status.get(serial, DeviceStatus.OFFLINE)
            return {
                "serial": serial,
                "model": info.model,
                "api_level": info.api_level,
                "device_type": "emulator" if info.is_emulator else "physical",
                "status": status.value,
                "state": info.state,
            }

    def get_idle_devices(self) -> list[str]:
        """Return serials of all idle (available) devices."""
        with self._lock:
            return [
                serial
                for serial, status in self._status.items()
                if status == DeviceStatus.IDLE
            ]

    def acquire_device(self, serial: str) -> bool:
        """Mark a device as busy (acquired for a test run).
        Returns True if successfully acquired, False if not available.
        """
        with self._lock:
            current = self._status.get(serial)
            if current != DeviceStatus.IDLE:
                logger.warning(
                    "acquire_failed",
                    serial=serial,
                    current_status=current.value if current else "unknown",
                )
                return False
            self._status[serial] = DeviceStatus.BUSY
            self._persist_status(serial, DeviceStatus.BUSY)
            logger.info("device_acquired", serial=serial)
            self._notify("device:status_changed", serial, DeviceStatus.BUSY)
            return True

    def release_device(self, serial: str) -> None:
        """Release a device back to idle."""
        with self._lock:
            if serial in self._status:
                # Check if device is still connected before marking idle
                if self._status[serial] != DeviceStatus.OFFLINE:
                    self._status[serial] = DeviceStatus.IDLE
                    self._persist_status(serial, DeviceStatus.IDLE)
                    logger.info("device_released", serial=serial)
                    self._notify("device:status_changed", serial, DeviceStatus.IDLE)

    def mark_error(self, serial: str, reason: str = "") -> None:
        """Mark a device as errored."""
        with self._lock:
            self._status[serial] = DeviceStatus.ERROR
            self._persist_status(serial, DeviceStatus.ERROR)
            logger.error("device_error", serial=serial, reason=reason)
            self._notify("device:status_changed", serial, DeviceStatus.ERROR)

    # ── Polling ────────────────────────────────────────────

    def refresh_devices(self) -> list[dict]:
        """Synchronous one-shot device scan. Returns list of device dicts."""
        raw_devices = self.adb.list_devices()

        with self._lock:
            seen_serials = set()

            for info in raw_devices:
                seen_serials.add(info.serial)
                old_status = self._status.get(info.serial)
                self._devices[info.serial] = info

                if info.state != "device":
                    # Device is visible but not usable
                    new_status = DeviceStatus.OFFLINE
                elif old_status == DeviceStatus.BUSY:
                    # Keep busy status — don't overwrite an active acquisition
                    new_status = DeviceStatus.BUSY
                elif old_status == DeviceStatus.ERROR:
                    # Reset error on reconnect
                    new_status = DeviceStatus.IDLE
                else:
                    new_status = DeviceStatus.IDLE

                if old_status != new_status:
                    self._status[info.serial] = new_status
                    self._persist_device(info, new_status)
                    self._notify("device:status_changed", info.serial, new_status)
                else:
                    self._status[info.serial] = new_status

            # Mark disappeared devices as offline
            for serial in list(self._status.keys()):
                if serial not in seen_serials:
                    if self._status[serial] != DeviceStatus.OFFLINE:
                        self._status[serial] = DeviceStatus.OFFLINE
                        self._persist_status(serial, DeviceStatus.OFFLINE)
                        self._notify(
                            "device:status_changed", serial, DeviceStatus.OFFLINE
                        )

        return self.get_all_devices()

    async def start_polling(self) -> None:
        """Start periodic device scanning in the background."""
        if self._polling:
            return
        self._polling = True
        logger.info("device_polling_started", interval=settings.device_poll_interval)
        self._poll_task = asyncio.create_task(self._poll_loop())

    async def stop_polling(self) -> None:
        """Stop the background polling task."""
        self._polling = False
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
        logger.info("device_polling_stopped")

    async def _poll_loop(self) -> None:
        """Internal polling loop."""
        while self._polling:
            try:
                # Run blocking ADB call in executor so we don't block the event loop
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, self.refresh_devices)
            except Exception as exc:
                logger.error("poll_error", error=str(exc))
            await asyncio.sleep(settings.device_poll_interval)

    # ── Event Callbacks ────────────────────────────────────

    def on_event(self, callback) -> None:
        """Register a callback for device events.
        callback(event_name: str, serial: str, status: DeviceStatus)
        """
        self._event_callbacks.append(callback)

    def _notify(self, event: str, serial: str, status: DeviceStatus) -> None:
        for cb in self._event_callbacks:
            try:
                cb(event, serial, status)
            except Exception as exc:
                logger.error("event_callback_error", error=str(exc))

    # ── DB Persistence ─────────────────────────────────────

    def _persist_device(self, info: DeviceInfo, status: DeviceStatus) -> None:
        """Upsert device record in DB."""
        try:
            session = get_session()
            device = session.get(Device, info.serial)
            if device is None:
                device = Device(
                    serial=info.serial,
                    model=info.model,
                    api_level=info.api_level,
                    device_type=(
                        DeviceType.EMULATOR if info.is_emulator else DeviceType.PHYSICAL
                    ),
                    status=status,
                    last_seen=datetime.datetime.utcnow(),
                    properties=info.properties,
                )
                session.add(device)
            else:
                device.model = info.model or device.model
                device.api_level = info.api_level or device.api_level
                device.status = status
                device.last_seen = datetime.datetime.utcnow()
                device.properties = info.properties
            session.commit()
        except Exception as exc:
            logger.error("db_persist_error", error=str(exc))
        finally:
            session.close()

    def _persist_status(self, serial: str, status: DeviceStatus) -> None:
        """Update only the status field in DB."""
        try:
            session = get_session()
            device = session.get(Device, serial)
            if device:
                device.status = status
                device.last_seen = datetime.datetime.utcnow()
                session.commit()
        except Exception as exc:
            logger.error("db_status_error", error=str(exc))
        finally:
            session.close()

    # ── Load from DB ───────────────────────────────────────

    def load_from_db(self) -> None:
        """Load previously known devices from the database on startup."""
        try:
            session = get_session()
            db_devices = session.query(Device).all()
            with self._lock:
                for d in db_devices:
                    self._status[d.serial] = DeviceStatus.OFFLINE  # will be corrected on first poll
            session.close()
            logger.info("loaded_devices_from_db", count=len(db_devices))
        except Exception as exc:
            logger.error("load_db_error", error=str(exc))


# ── Module-level singleton ─────────────────────────────────────
device_manager = DevicePoolManager()
