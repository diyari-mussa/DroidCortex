"""
DroidCortex — Rule-Based Test Executor.
Reads a test script (list of steps) and executes each step sequentially
against a device via ADB, recording pass/fail results.
"""

from __future__ import annotations

import datetime
import time
import re
from typing import Any, Optional, Callable

import structlog

from backend.models.database import (
    TestStep,
    StepStatus,
    DeviceTestRun,
    TestRunStatus,
    get_session,
)
from backend.services.adb_service import ADBService, adb_service

logger = structlog.get_logger(__name__)


class StepResult:
    """Result of executing a single test step."""

    def __init__(
        self,
        step_number: int,
        action: str,
        status: StepStatus,
        actual: str = "",
        screenshot_path: str | None = None,
        log_snippet: str = "",
        duration_ms: int = 0,
    ):
        self.step_number = step_number
        self.action = action
        self.status = status
        self.actual = actual
        self.screenshot_path = screenshot_path
        self.log_snippet = log_snippet
        self.duration_ms = duration_ms


class RuleExecutor:
    """
    Executes a list of test steps on a device.

    Each step is a dict with:
      - action: str (the action to perform)
      - params: dict (action-specific parameters)
      - expected: str | None (expected result for pass/fail evaluation)
      - timeout: int (per-step timeout in seconds)
    """

    # Map action names to handler methods
    ACTION_HANDLERS = {
        "install": "_action_install",
        "launch": "_action_launch",
        "check_running": "_action_check_running",
        "assert_running": "_action_check_running",
        "force_stop": "_action_force_stop",
        "clear_data": "_action_clear_data",
        "uninstall": "_action_uninstall",
        "tap": "_action_tap",
        "input_text": "_action_input_text",
        "swipe": "_action_swipe",
        "press_key": "_action_press_key",
        "press_back": "_action_press_back",
        "press_home": "_action_press_home",
        "send_broadcast": "_action_send_broadcast",
        "send_intent": "_action_send_intent",
        "wait": "_action_wait",
        "screenshot": "_action_screenshot",
        "assert_text_visible": "_action_assert_text_visible",
        "shell": "_action_shell",
        "custom_shell": "_action_shell",
        "logcat": "_action_logcat",
        "assert_activity": "_action_assert_activity",
    }

    def __init__(
        self,
        adb: ADBService | None = None,
        on_step_complete: Callable | None = None,
    ):
        self.adb = adb or adb_service
        self.on_step_complete = on_step_complete

    def execute(
        self,
        serial: str,
        package: str,
        steps: list[dict[str, Any]],
        device_test_run_id: int,
        apk_path: str | None = None,
        main_activity: str | None = None,
    ) -> list[StepResult]:
        """
        Execute all steps on the given device.
        Returns list of StepResult objects.
        """
        results: list[StepResult] = []
        context = {
            "serial": serial,
            "package": package,
            "apk_path": apk_path,
            "main_activity": main_activity,
        }

        logger.info(
            "rule_execution_start",
            serial=serial,
            package=package,
            total_steps=len(steps),
        )

        for i, step_def in enumerate(steps, start=1):
            action = step_def.get("action", "unknown")
            params = step_def.get("params", {})
            expected = step_def.get("expected")
            timeout = step_def.get("timeout", 30)

            logger.info(
                "step_start",
                step=i,
                action=action,
                serial=serial,
            )

            # Record step start in DB
            self._db_step_start(device_test_run_id, i, action, params, expected)

            start_time = time.time()
            try:
                result = self._execute_step(
                    action, params, expected, timeout, context
                )
                result.step_number = i
            except Exception as exc:
                logger.error("step_exception", step=i, action=action, error=str(exc))
                result = StepResult(
                    step_number=i,
                    action=action,
                    status=StepStatus.ERROR,
                    actual=f"Exception: {exc}",
                )

            elapsed_ms = int((time.time() - start_time) * 1000)
            result.duration_ms = elapsed_ms

            # Take a screenshot after each step for evidence
            if action not in ("screenshot", "wait"):
                try:
                    ss = self.adb.take_screenshot(serial)
                    result.screenshot_path = ss
                except Exception:
                    pass

            # Grab recent logcat
            try:
                result.log_snippet = self.adb.get_logcat(serial, lines=20)
            except Exception:
                pass

            # Record step result in DB
            self._db_step_complete(device_test_run_id, i, result)

            results.append(result)

            logger.info(
                "step_complete",
                step=i,
                action=action,
                status=result.status.value,
                duration_ms=elapsed_ms,
            )

            # Notify callback (for WebSocket events)
            if self.on_step_complete:
                try:
                    self.on_step_complete(device_test_run_id, i, result)
                except Exception:
                    pass

            # If a step fails or errors, stop execution (fail-fast)
            if result.status in (StepStatus.FAILED, StepStatus.ERROR):
                # Mark remaining steps as skipped
                for j in range(i + 1, len(steps) + 1):
                    skip_action = steps[j - 1].get("action", "unknown")
                    skip_result = StepResult(
                        step_number=j,
                        action=skip_action,
                        status=StepStatus.SKIPPED,
                        actual="Skipped due to previous failure",
                    )
                    results.append(skip_result)
                    self._db_step_start(
                        device_test_run_id, j, skip_action,
                        steps[j - 1].get("params", {}),
                        steps[j - 1].get("expected"),
                    )
                    self._db_step_complete(device_test_run_id, j, skip_result)
                break

        logger.info(
            "rule_execution_complete",
            serial=serial,
            total=len(results),
            passed=sum(1 for r in results if r.status == StepStatus.PASSED),
            failed=sum(1 for r in results if r.status == StepStatus.FAILED),
        )

        return results

    # ── Step Dispatch ──────────────────────────────────────

    def _execute_step(
        self,
        action: str,
        params: dict,
        expected: str | None,
        timeout: int,
        context: dict,
    ) -> StepResult:
        """Dispatch to the appropriate action handler."""
        handler_name = self.ACTION_HANDLERS.get(action)
        if handler_name is None:
            return StepResult(
                step_number=0,
                action=action,
                status=StepStatus.ERROR,
                actual=f"Unknown action: {action}",
            )

        handler = getattr(self, handler_name)
        return handler(params=params, expected=expected, timeout=timeout, ctx=context)

    # ── Action Handlers ────────────────────────────────────

    def _action_install(self, params: dict, expected: str | None, timeout: int, ctx: dict) -> StepResult:
        apk_path = params.get("apk_path") or ctx.get("apk_path")
        if not apk_path:
            return StepResult(0, "install", StepStatus.ERROR, actual="No APK path provided")

        result = self.adb.install_apk(ctx["serial"], apk_path)
        status = StepStatus.PASSED if result.success else StepStatus.FAILED
        return StepResult(0, "install", status, actual=result.output or result.error)

    def _action_launch(self, params: dict, expected: str | None, timeout: int, ctx: dict) -> StepResult:
        package = params.get("package") or ctx["package"]
        activity = params.get("activity") or ctx.get("main_activity")
        result = self.adb.launch_app(ctx["serial"], package, activity)

        # Brief wait for app to start
        time.sleep(2)

        # Verify it's running
        running = self.adb.is_app_running(ctx["serial"], package)
        if running:
            return StepResult(0, "launch", StepStatus.PASSED, actual="App launched and running")
        else:
            return StepResult(
                0, "launch", StepStatus.FAILED,
                actual=f"App not running after launch. ADB output: {result.output or result.error}",
            )

    def _action_check_running(self, params: dict, expected: str | None, timeout: int, ctx: dict) -> StepResult:
        package = params.get("package") or ctx["package"]
        running = self.adb.is_app_running(ctx["serial"], package)
        expect_running = (expected or "true").lower() in ("true", "yes", "running")

        if running == expect_running:
            return StepResult(
                0, "check_running", StepStatus.PASSED,
                actual=f"running={running} (expected={expect_running})",
            )
        else:
            return StepResult(
                0, "check_running", StepStatus.FAILED,
                actual=f"running={running} (expected={expect_running})",
            )

    def _action_force_stop(self, params: dict, expected: str | None, timeout: int, ctx: dict) -> StepResult:
        package = params.get("package") or ctx["package"]
        result = self.adb.force_stop(ctx["serial"], package)
        return StepResult(
            0, "force_stop",
            StepStatus.PASSED if result.success else StepStatus.FAILED,
            actual=result.output or result.error,
        )

    def _action_clear_data(self, params: dict, expected: str | None, timeout: int, ctx: dict) -> StepResult:
        package = params.get("package") or ctx["package"]
        result = self.adb.clear_data(ctx["serial"], package)
        return StepResult(
            0, "clear_data",
            StepStatus.PASSED if result.success else StepStatus.FAILED,
            actual=result.output or result.error,
        )

    def _action_uninstall(self, params: dict, expected: str | None, timeout: int, ctx: dict) -> StepResult:
        package = params.get("package") or ctx["package"]
        result = self.adb.uninstall_apk(ctx["serial"], package)
        return StepResult(
            0, "uninstall",
            StepStatus.PASSED if result.success else StepStatus.FAILED,
            actual=result.output or result.error,
        )

    def _action_tap(self, params: dict, expected: str | None, timeout: int, ctx: dict) -> StepResult:
        x = params.get("x", 0)
        y = params.get("y", 0)
        result = self.adb.input_tap(ctx["serial"], x, y)
        time.sleep(params.get("wait_after", 1))
        return StepResult(
            0, "tap",
            StepStatus.PASSED if result.success else StepStatus.FAILED,
            actual=f"Tapped ({x}, {y})",
        )

    def _action_input_text(self, params: dict, expected: str | None, timeout: int, ctx: dict) -> StepResult:
        text = params.get("text", "")
        result = self.adb.input_text(ctx["serial"], text)
        return StepResult(
            0, "input_text",
            StepStatus.PASSED if result.success else StepStatus.FAILED,
            actual=f"Entered text: {text}",
        )

    def _action_swipe(self, params: dict, expected: str | None, timeout: int, ctx: dict) -> StepResult:
        result = self.adb.input_swipe(
            ctx["serial"],
            params.get("x1", 0), params.get("y1", 0),
            params.get("x2", 0), params.get("y2", 0),
            params.get("duration_ms", 300),
        )
        time.sleep(params.get("wait_after", 0.5))
        return StepResult(
            0, "swipe",
            StepStatus.PASSED if result.success else StepStatus.FAILED,
            actual="Swipe executed",
        )

    def _action_press_key(self, params: dict, expected: str | None, timeout: int, ctx: dict) -> StepResult:
        keycode = params.get("keycode", params.get("key", 4))
        result = self.adb.press_key(ctx["serial"], keycode)
        return StepResult(
            0, "press_key",
            StepStatus.PASSED if result.success else StepStatus.FAILED,
            actual=f"Pressed key {keycode}",
        )

    def _action_press_back(self, params: dict, expected: str | None, timeout: int, ctx: dict) -> StepResult:
        result = self.adb.press_key(ctx["serial"], 4)
        time.sleep(0.5)
        return StepResult(0, "press_back", StepStatus.PASSED if result.success else StepStatus.FAILED, actual="Back pressed")

    def _action_press_home(self, params: dict, expected: str | None, timeout: int, ctx: dict) -> StepResult:
        result = self.adb.press_key(ctx["serial"], 3)
        time.sleep(0.5)
        return StepResult(0, "press_home", StepStatus.PASSED if result.success else StepStatus.FAILED, actual="Home pressed")

    def _action_send_broadcast(self, params: dict, expected: str | None, timeout: int, ctx: dict) -> StepResult:
        action_name = params.get("action", "")
        extras = params.get("extras", {})
        pkg = params.get("package") or ctx.get("package")
        result = self.adb.send_broadcast(ctx["serial"], action_name, extras, pkg)
        passed = result.success
        if expected and expected.lower() not in result.output.lower():
            passed = False
        return StepResult(
            0, "send_broadcast",
            StepStatus.PASSED if passed else StepStatus.FAILED,
            actual=result.output or result.error,
        )

    def _action_send_intent(self, params: dict, expected: str | None, timeout: int, ctx: dict) -> StepResult:
        action_name = params.get("action", "android.intent.action.VIEW")
        data_uri = params.get("data_uri") or params.get("uri")
        extras = params.get("extras", {})
        result = self.adb.send_intent(ctx["serial"], action_name, data_uri, extras)
        return StepResult(
            0, "send_intent",
            StepStatus.PASSED if result.success else StepStatus.FAILED,
            actual=result.output or result.error,
        )

    def _action_wait(self, params: dict, expected: str | None, timeout: int, ctx: dict) -> StepResult:
        seconds = params.get("seconds", params.get("duration", 2))
        time.sleep(seconds)
        return StepResult(0, "wait", StepStatus.PASSED, actual=f"Waited {seconds}s")

    def _action_screenshot(self, params: dict, expected: str | None, timeout: int, ctx: dict) -> StepResult:
        path = self.adb.take_screenshot(ctx["serial"])
        if path:
            return StepResult(0, "screenshot", StepStatus.PASSED, actual=f"Saved: {path}", screenshot_path=path)
        return StepResult(0, "screenshot", StepStatus.FAILED, actual="Screenshot failed")

    def _action_assert_text_visible(self, params: dict, expected: str | None, timeout: int, ctx: dict) -> StepResult:
        """Check if text is visible on screen using UI hierarchy XML."""
        target_text = params.get("text", expected or "")
        xml = self.adb.dump_ui_hierarchy(ctx["serial"])
        if xml and target_text.lower() in xml.lower():
            return StepResult(
                0, "assert_text_visible", StepStatus.PASSED,
                actual=f"Text '{target_text}' found on screen",
            )
        return StepResult(
            0, "assert_text_visible", StepStatus.FAILED,
            actual=f"Text '{target_text}' NOT found on screen",
        )

    def _action_shell(self, params: dict, expected: str | None, timeout: int, ctx: dict) -> StepResult:
        command = params.get("command", "")
        result = self.adb.shell(ctx["serial"], command, timeout=timeout)
        passed = result.success
        if expected and expected.lower() not in result.output.lower():
            passed = False
        return StepResult(
            0, "shell",
            StepStatus.PASSED if passed else StepStatus.FAILED,
            actual=result.output or result.error,
        )

    def _action_logcat(self, params: dict, expected: str | None, timeout: int, ctx: dict) -> StepResult:
        tag = params.get("tag")
        lines = params.get("lines", 50)
        output = self.adb.get_logcat(ctx["serial"], tag=tag, lines=lines)

        passed = True
        if expected and expected.lower() not in output.lower():
            passed = False
        return StepResult(
            0, "logcat",
            StepStatus.PASSED if passed else StepStatus.FAILED,
            actual=output[:2000],  # Truncate for DB storage
            log_snippet=output[:2000],
        )

    def _action_assert_activity(self, params: dict, expected: str | None, timeout: int, ctx: dict) -> StepResult:
        """Assert the currently focused activity matches expected."""
        current = self.adb.get_current_activity(ctx["serial"])
        expected_activity = params.get("activity", expected or "")
        if current and expected_activity.lower() in current.lower():
            return StepResult(
                0, "assert_activity", StepStatus.PASSED,
                actual=f"Current activity: {current}",
            )
        return StepResult(
            0, "assert_activity", StepStatus.FAILED,
            actual=f"Current activity: {current}, expected: {expected_activity}",
        )

    # ── DB Helpers ─────────────────────────────────────────

    def _db_step_start(
        self, device_test_run_id: int, step_number: int,
        action: str, params: dict, expected: str | None,
    ) -> None:
        try:
            session = get_session()
            step = TestStep(
                device_test_run_id=device_test_run_id,
                step_number=step_number,
                action=action,
                params=params,
                expected=expected,
                status=StepStatus.RUNNING,
                started_at=datetime.datetime.utcnow(),
            )
            session.add(step)
            session.commit()
            session.close()
        except Exception as exc:
            logger.error("db_step_start_error", error=str(exc))

    def _db_step_complete(
        self, device_test_run_id: int, step_number: int, result: StepResult,
    ) -> None:
        try:
            session = get_session()
            step = (
                session.query(TestStep)
                .filter_by(
                    device_test_run_id=device_test_run_id,
                    step_number=step_number,
                )
                .first()
            )
            if step:
                step.status = result.status
                step.actual = result.actual
                step.screenshot_path = result.screenshot_path
                step.log_snippet = result.log_snippet
                step.duration_ms = result.duration_ms
                step.completed_at = datetime.datetime.utcnow()
                session.commit()
            session.close()
        except Exception as exc:
            logger.error("db_step_complete_error", error=str(exc))
