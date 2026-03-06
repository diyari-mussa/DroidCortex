"""
DroidCortex — Test Orchestrator.
Coordinates the full test pipeline:
  1. For each target device → acquire from pool
  2. Install APK, verify install
  3. Launch app, verify it's running
  4. Execute test (rule-based or AI mode)
  5. Collect results, release device
  6. Move to next device
  7. Report overall results

Supports parallel execution across multiple devices.
"""

from __future__ import annotations

import datetime
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable, Optional

import yaml
import structlog

from backend.config import settings
from backend.models.database import (
    APK,
    TestRun,
    DeviceTestRun,
    TestRunStatus,
    TestMode,
    StepStatus,
    get_session,
)
from backend.services.adb_service import ADBService, adb_service
from backend.services.device_manager import DevicePoolManager, device_manager
from backend.engine.rule_executor import RuleExecutor
from backend.engine.ai_executor import AIExecutor

logger = structlog.get_logger(__name__)


class Orchestrator:
    """
    Top-level test orchestrator.

    Usage:
        orch = Orchestrator()
        test_run_id = orch.start_test_run(config)
    """

    def __init__(
        self,
        adb: ADBService | None = None,
        pool: DevicePoolManager | None = None,
        on_event: Callable | None = None,
    ):
        self.adb = adb or adb_service
        self.pool = pool or device_manager
        self.on_event = on_event  # Callback for real-time WebSocket events
        self._active_runs: dict[int, threading.Event] = {}  # run_id → cancel event

    # ── Public API ─────────────────────────────────────────

    def start_test_run(
        self,
        apk_id: int,
        mode: str,
        target_devices: list[str] | None = None,
        steps: list[dict] | None = None,
        ai_config: dict | None = None,
        name: str | None = None,
    ) -> int:
        """
        Start a new test run. Returns the test_run_id.

        Args:
            apk_id: Database ID of the uploaded APK
            mode: "rules" or "ai"
            target_devices: List of device serials, or None/"all" for all idle devices
            steps: List of step defs (for rules mode)
            ai_config: AI config dict (for ai mode): {provider, model, goal, max_steps}
            name: Optional test run name
        """
        session = get_session()
        try:
            # Fetch APK info
            apk = session.get(APK, apk_id)
            if not apk:
                raise ValueError(f"APK with id={apk_id} not found")

            # Determine target devices
            if not target_devices:
                target_devices = self.pool.get_idle_devices()
                if not target_devices:
                    raise ValueError("No idle devices available")

            # Create TestRun record
            test_mode = TestMode.AI if mode == "ai" else TestMode.RULES
            config_data = {
                "steps": steps or [],
                "ai_config": ai_config or {},
            }

            test_run = TestRun(
                name=name or f"Test {apk.package_name or apk.filename}",
                apk_id=apk_id,
                mode=test_mode,
                status=TestRunStatus.PENDING,
                config=config_data,
                target_devices=target_devices,
                created_at=datetime.datetime.utcnow(),
            )
            session.add(test_run)
            session.flush()  # Get the ID

            # Create DeviceTestRun records for each target device
            for serial in target_devices:
                dtr = DeviceTestRun(
                    test_run_id=test_run.id,
                    device_serial=serial,
                    status=TestRunStatus.PENDING,
                )
                session.add(dtr)

            session.commit()
            test_run_id = test_run.id

            logger.info(
                "test_run_created",
                run_id=test_run_id,
                mode=mode,
                devices=target_devices,
                apk=apk.package_name,
            )

            # Start execution in background
            cancel_event = threading.Event()
            self._active_runs[test_run_id] = cancel_event

            thread = threading.Thread(
                target=self._run_test_pipeline,
                args=(test_run_id, cancel_event),
                daemon=True,
                name=f"TestRun-{test_run_id}",
            )
            thread.start()

            return test_run_id

        except Exception as exc:
            session.rollback()
            logger.error("start_test_run_error", error=str(exc))
            raise
        finally:
            session.close()

    def abort_test_run(self, test_run_id: int) -> bool:
        """Abort a running test."""
        cancel_event = self._active_runs.get(test_run_id)
        if cancel_event:
            cancel_event.set()
            logger.info("test_run_abort_requested", run_id=test_run_id)
            return True
        return False

    def get_test_run_status(self, test_run_id: int) -> dict | None:
        """Get the current status of a test run."""
        session = get_session()
        try:
            run = session.get(TestRun, test_run_id)
            if not run:
                return None
            return {
                "id": run.id,
                "name": run.name,
                "mode": run.mode.value,
                "status": run.status.value,
                "total_devices": run.total_devices,
                "completed_devices": run.completed_devices,
                "created_at": run.created_at.isoformat() if run.created_at else None,
                "completed_at": run.completed_at.isoformat() if run.completed_at else None,
            }
        finally:
            session.close()

    # ── Test Pipeline (runs in background thread) ──────────

    def _run_test_pipeline(self, test_run_id: int, cancel_event: threading.Event) -> None:
        """Main test pipeline — runs across all target devices."""
        logger.info("pipeline_start", run_id=test_run_id)

        session = get_session()
        try:
            test_run = session.get(TestRun, test_run_id)
            if not test_run:
                return

            # Update status to RUNNING
            test_run.status = TestRunStatus.RUNNING
            session.commit()
            self._emit("test:run_started", {"run_id": test_run_id})

            # Get all DeviceTestRun records
            device_runs = (
                session.query(DeviceTestRun)
                .filter_by(test_run_id=test_run_id)
                .all()
            )

            # Fetch APK info
            apk = session.get(APK, test_run.apk_id)
            apk_path = apk.file_path
            package = apk.package_name
            main_activity = apk.main_activity

            # If package_name is missing (aapt2 wasn't available during upload),
            # try to extract it via `adb shell` after install, or from filename
            if not package:
                # Try to extract package from APK using aapt dump on device
                # For now, we'll extract it after install in _run_on_device
                logger.warning("apk_package_unknown", apk_id=apk.id, file=apk.filename)
                package = ""  # Will be resolved after install

            mode = test_run.mode
            config = test_run.config or {}
            steps = config.get("steps", [])
            ai_config = config.get("ai_config", {})

            session.close()
            session = None

            # Execute on devices with controlled parallelism
            max_workers = min(settings.max_parallel_devices, len(device_runs))

            with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="Device") as pool:
                futures = {}
                for dtr in device_runs:
                    if cancel_event.is_set():
                        break
                    future = pool.submit(
                        self._run_on_device,
                        dtr.id,
                        dtr.device_serial,
                        apk_path,
                        package,
                        main_activity,
                        mode,
                        steps,
                        ai_config,
                        cancel_event,
                    )
                    futures[future] = dtr.device_serial

                # Wait for all to complete
                for future in as_completed(futures):
                    serial = futures[future]
                    try:
                        future.result()
                    except Exception as exc:
                        logger.error(
                            "device_run_error",
                            serial=serial,
                            run_id=test_run_id,
                            error=str(exc),
                        )

            # Finalize test run
            session = get_session()
            test_run = session.get(TestRun, test_run_id)
            if cancel_event.is_set():
                test_run.status = TestRunStatus.ABORTED
            else:
                # Check if any device run failed
                device_runs = (
                    session.query(DeviceTestRun)
                    .filter_by(test_run_id=test_run_id)
                    .all()
                )
                any_failed = any(
                    dtr.status == TestRunStatus.FAILED for dtr in device_runs
                )
                test_run.status = (
                    TestRunStatus.FAILED if any_failed else TestRunStatus.COMPLETED
                )

            test_run.completed_at = datetime.datetime.utcnow()
            session.commit()

            logger.info(
                "pipeline_complete",
                run_id=test_run_id,
                status=test_run.status.value,
            )

            self._emit(
                "test:run_completed",
                {
                    "run_id": test_run_id,
                    "status": test_run.status.value,
                },
            )

        except Exception as exc:
            logger.error("pipeline_error", run_id=test_run_id, error=str(exc))
            if session:
                try:
                    test_run = session.get(TestRun, test_run_id)
                    if test_run:
                        test_run.status = TestRunStatus.FAILED
                        test_run.completed_at = datetime.datetime.utcnow()
                        session.commit()
                except Exception:
                    pass
        finally:
            if session:
                session.close()
            self._active_runs.pop(test_run_id, None)

    def _run_on_device(
        self,
        device_test_run_id: int,
        serial: str,
        apk_path: str,
        package: str,
        main_activity: str | None,
        mode: TestMode,
        steps: list[dict],
        ai_config: dict,
        cancel_event: threading.Event,
    ) -> None:
        """Execute the full test cycle on a single device."""
        logger.info(
            "device_run_start",
            dtr_id=device_test_run_id,
            serial=serial,
        )

        session = get_session()
        try:
            # ── Step 1: Acquire device ─────────────────────
            acquired = self.pool.acquire_device(serial)
            if not acquired:
                # Wait up to 60s for the device to become available
                for _ in range(12):
                    if cancel_event.is_set():
                        self._mark_dtr_status(session, device_test_run_id, TestRunStatus.ABORTED)
                        return
                    time.sleep(5)
                    acquired = self.pool.acquire_device(serial)
                    if acquired:
                        break

                if not acquired:
                    self._mark_dtr_status(
                        session, device_test_run_id, TestRunStatus.FAILED,
                        error="Could not acquire device — busy or offline",
                    )
                    return

            # ── Step 2: Update DTR status to RUNNING ───────
            dtr = session.get(DeviceTestRun, device_test_run_id)
            dtr.status = TestRunStatus.RUNNING
            dtr.started_at = datetime.datetime.utcnow()
            session.commit()

            self._emit("test:device_started", {
                "device_test_run_id": device_test_run_id,
                "serial": serial,
            })

            # ── Step 3: Install APK ────────────────────────
            if cancel_event.is_set():
                self._finalize_dtr(session, device_test_run_id, serial, TestRunStatus.ABORTED)
                return

            # Snapshot packages BEFORE install so we can diff afterwards
            pre_install_pkgs: set[str] = set()
            if not package:
                pre_result = self.adb.shell(serial, "pm list packages -3")
                if pre_result.success:
                    pre_install_pkgs = {
                        line.replace("package:", "").strip()
                        for line in pre_result.output.strip().split("\n")
                        if line.strip().startswith("package:")
                    }

            logger.info("installing_apk", serial=serial, apk=apk_path)
            install_result = self.adb.install_apk(serial, apk_path)
            if not install_result.success:
                self._finalize_dtr(
                    session, device_test_run_id, serial, TestRunStatus.FAILED,
                    error=f"APK install failed: {install_result.error}",
                )
                return

            self._emit("test:step_completed", {
                "device_test_run_id": device_test_run_id,
                "serial": serial,
                "phase": "install",
                "status": "passed",
            })

            # ── Step 3b: Resolve package name if unknown ───
            if not package:
                logger.info("resolving_package_name", serial=serial)

                # Method 1 (most reliable): diff package list before/after install
                post_result = self.adb.shell(serial, "pm list packages -3")
                if post_result.success:
                    post_install_pkgs = {
                        line.replace("package:", "").strip()
                        for line in post_result.output.strip().split("\n")
                        if line.strip().startswith("package:")
                    }
                    new_pkgs = post_install_pkgs - pre_install_pkgs
                    if len(new_pkgs) == 1:
                        package = new_pkgs.pop()
                    elif len(new_pkgs) > 1:
                        # Multiple new packages (unlikely) — pick best match
                        apk_stem = Path(apk_path).stem.lower()
                        for pkg in new_pkgs:
                            if pkg.lower() in apk_stem:
                                package = pkg
                                break
                        if not package:
                            package = sorted(new_pkgs)[0]

                # Method 2: match installed packages against APK filename
                if not package and post_result.success:
                    apk_stem = Path(apk_path).stem.lower()
                    all_pkgs = [
                        line.replace("package:", "").strip()
                        for line in post_result.output.strip().split("\n")
                        if line.strip().startswith("package:")
                    ]
                    for pkg in all_pkgs:
                        # Check if the full package name appears in the filename
                        # e.g. "me.ocv.partyup" in "me.ocv.partyup_10900_2"
                        if pkg.lower() in apk_stem:
                            package = pkg
                            break

                # Method 3: Extract from APK filename heuristic
                if not package:
                    import re
                    name = Path(apk_path).stem
                    # me.ocv.partyup_10900_2 → me.ocv.partyup
                    # Match dotted segments that look like a Java package
                    match = re.match(
                        r'([a-zA-Z][a-zA-Z0-9]*(?:\.[a-zA-Z][a-zA-Z0-9]*){1,})', name
                    )
                    if match:
                        package = match.group(1)

                if not package:
                    self._finalize_dtr(
                        session, device_test_run_id, serial, TestRunStatus.FAILED,
                        error="Could not determine package name from APK",
                    )
                    return

                logger.info("package_resolved", serial=serial, package=package)

            # ── Step 4: Launch app and verify it's running ─
            if cancel_event.is_set():
                self._finalize_dtr(session, device_test_run_id, serial, TestRunStatus.ABORTED)
                return

            logger.info("launching_app", serial=serial, package=package)
            self.adb.launch_app(serial, package, main_activity)
            time.sleep(3)  # Give app time to start

            if not self.adb.is_app_running(serial, package):
                self._finalize_dtr(
                    session, device_test_run_id, serial, TestRunStatus.FAILED,
                    error="App failed to start — not running after launch",
                )
                return

            self._emit("test:step_completed", {
                "device_test_run_id": device_test_run_id,
                "serial": serial,
                "phase": "launch",
                "status": "passed",
                "message": "App launched and running",
            })

            # ── Step 5: Execute tests ──────────────────────
            if cancel_event.is_set():
                self._finalize_dtr(session, device_test_run_id, serial, TestRunStatus.ABORTED)
                return

            if mode == TestMode.RULES:
                self._run_rules_mode(
                    serial, package, device_test_run_id, steps, apk_path, main_activity
                )
            else:
                self._run_ai_mode(
                    serial, package, device_test_run_id, ai_config, apk_path, main_activity
                )

            # ── Step 6: Determine final status ─────────────
            session = get_session()  # Re-open session
            dtr = session.get(DeviceTestRun, device_test_run_id)
            steps_result = dtr.steps

            any_failed = any(
                s.status in (StepStatus.FAILED, StepStatus.ERROR)
                for s in steps_result
            )

            final_status = TestRunStatus.FAILED if any_failed else TestRunStatus.COMPLETED

            dtr.status = final_status
            dtr.completed_at = datetime.datetime.utcnow()
            dtr.summary = {
                "total_steps": len(steps_result),
                "passed": sum(1 for s in steps_result if s.status == StepStatus.PASSED),
                "failed": sum(1 for s in steps_result if s.status == StepStatus.FAILED),
                "skipped": sum(1 for s in steps_result if s.status == StepStatus.SKIPPED),
                "errors": sum(1 for s in steps_result if s.status == StepStatus.ERROR),
            }
            session.commit()

            logger.info(
                "device_run_complete",
                serial=serial,
                dtr_id=device_test_run_id,
                status=final_status.value,
                summary=dtr.summary,
            )

            self._emit("test:device_completed", {
                "device_test_run_id": device_test_run_id,
                "serial": serial,
                "status": final_status.value,
                "summary": dtr.summary,
            })

        except Exception as exc:
            logger.error(
                "device_run_error",
                serial=serial,
                dtr_id=device_test_run_id,
                error=str(exc),
            )
            try:
                session = get_session()
                self._mark_dtr_status(
                    session, device_test_run_id, TestRunStatus.FAILED,
                    error=str(exc),
                )
            except Exception:
                pass
        finally:
            # Always release the device
            self.pool.release_device(serial)
            try:
                # Force stop the app for clean state
                self.adb.force_stop(serial, package)
            except Exception:
                pass
            try:
                session.close()
            except Exception:
                pass

    # ── Mode Runners ───────────────────────────────────────

    def _run_rules_mode(
        self,
        serial: str,
        package: str,
        device_test_run_id: int,
        steps: list[dict],
        apk_path: str | None,
        main_activity: str | None,
    ) -> None:
        """Run rule-based test execution."""
        executor = RuleExecutor(
            adb=self.adb,
            on_step_complete=self._make_step_callback(serial),
        )
        executor.execute(
            serial=serial,
            package=package,
            steps=steps,
            device_test_run_id=device_test_run_id,
            apk_path=apk_path,
            main_activity=main_activity,
        )

    def _run_ai_mode(
        self,
        serial: str,
        package: str,
        device_test_run_id: int,
        ai_config: dict,
        apk_path: str | None,
        main_activity: str | None,
    ) -> None:
        """Run AI agent test execution."""
        executor = AIExecutor(
            adb=self.adb,
            on_step_complete=self._make_step_callback(serial),
            on_agent_thought=self._make_thought_callback(serial),
        )
        executor.execute(
            serial=serial,
            package=package,
            device_test_run_id=device_test_run_id,
            goal=ai_config.get("goal", "Explore the app and verify it works correctly"),
            max_steps=ai_config.get("max_steps", settings.ai_max_steps),
            provider=ai_config.get("provider"),
            model=ai_config.get("model"),
            apk_path=apk_path,
            main_activity=main_activity,
        )

    # ── Callbacks & Events ─────────────────────────────────

    def _make_step_callback(self, serial: str) -> Callable:
        def callback(dtr_id, step_num, result):
            self._emit("test:step_completed", {
                "device_test_run_id": dtr_id,
                "serial": serial,
                "step": step_num,
                "action": result.action if hasattr(result, "action") else result.get("action"),
                "status": result.status.value if hasattr(result, "status") else result.get("status"),
            })
        return callback

    def _make_thought_callback(self, serial: str) -> Callable:
        def callback(dtr_id, step_num, thought):
            self._emit("ai:agent_thought", {
                "device_test_run_id": dtr_id,
                "serial": serial,
                "step": step_num,
                "thought": thought,
            })
        return callback

    def _emit(self, event_name: str, data: dict) -> None:
        """Emit a real-time event (WebSocket)."""
        if self.on_event:
            try:
                self.on_event(event_name, data)
            except Exception as exc:
                logger.warning("event_emit_error", evt=event_name, error=str(exc))

    # ── DB Helpers ─────────────────────────────────────────

    def _mark_dtr_status(
        self,
        session,
        dtr_id: int,
        status: TestRunStatus,
        error: str | None = None,
    ) -> None:
        dtr = session.get(DeviceTestRun, dtr_id)
        if dtr:
            dtr.status = status
            dtr.error_message = error
            dtr.completed_at = datetime.datetime.utcnow()
            session.commit()

    def _finalize_dtr(
        self,
        session,
        dtr_id: int,
        serial: str,
        status: TestRunStatus,
        error: str | None = None,
    ) -> None:
        self._mark_dtr_status(session, dtr_id, status, error)
        self.pool.release_device(serial)
        self._emit("test:device_completed", {
            "device_test_run_id": dtr_id,
            "serial": serial,
            "status": status.value,
            "error": error,
        })

    # ── Test Script Loading ────────────────────────────────

    @staticmethod
    def load_test_script(file_path: str) -> dict:
        """Load a YAML or JSON test script file."""
        path = Path(file_path)
        content = path.read_text(encoding="utf-8")

        if path.suffix in (".yml", ".yaml"):
            return yaml.safe_load(content)
        elif path.suffix == ".json":
            return json.loads(content)
        else:
            # Try YAML first, fallback to JSON
            try:
                return yaml.safe_load(content)
            except Exception:
                return json.loads(content)


# ── Module-level singleton ─────────────────────────────────────
orchestrator = Orchestrator()
