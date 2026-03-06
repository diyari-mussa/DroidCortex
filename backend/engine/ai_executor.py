"""
DroidCortex — AI Agent Executor.
Uses an LLM to autonomously explore and test an Android app.
Captures device state (UI hierarchy, screenshots, logs), sends to LLM,
executes the decided action, and loops until goal is met or limits reached.
"""

from __future__ import annotations

import datetime
import time
from typing import Any, Callable, Optional

import structlog

from backend.config import settings
from backend.models.database import (
    TestStep,
    StepStatus,
    get_session,
)
from backend.services.adb_service import ADBService, adb_service
from backend.services.llm_service import (
    LLMProvider,
    SYSTEM_PROMPT,
    get_llm_provider,
)

logger = structlog.get_logger(__name__)


class AIExecutor:
    """
    AI Agent testing loop:
    1. Capture device state (UI XML, screenshot, logcat, current activity)
    2. Send state + history to LLM
    3. Parse LLM's decided action
    4. Execute the action via ADB
    5. Record the result
    6. Repeat until: goal met (done action), max steps, or crash
    """

    def __init__(
        self,
        adb: ADBService | None = None,
        llm: LLMProvider | None = None,
        on_step_complete: Callable | None = None,
        on_agent_thought: Callable | None = None,
    ):
        self.adb = adb or adb_service
        self.llm = llm
        self.on_step_complete = on_step_complete
        self.on_agent_thought = on_agent_thought

    def execute(
        self,
        serial: str,
        package: str,
        device_test_run_id: int,
        goal: str = "Explore the app and verify it works correctly",
        max_steps: int | None = None,
        provider: str | None = None,
        model: str | None = None,
        apk_path: str | None = None,
        main_activity: str | None = None,
    ) -> list[dict]:
        """
        Run the AI agent testing loop.

        Returns a list of step result dicts:
        [{"step": 1, "action": "tap", "params": {...}, "reasoning": "...", "status": "passed"}, ...]
        """
        max_steps = max_steps or settings.ai_max_steps

        # Initialize LLM provider if not set
        if self.llm is None:
            self.llm = get_llm_provider(provider=provider, model=model)

        logger.info(
            "ai_execution_start",
            serial=serial,
            package=package,
            goal=goal,
            max_steps=max_steps,
        )

        # Build the goal-specific system prompt
        system_prompt = SYSTEM_PROMPT + f"\n\nTESTING GOAL: {goal}\nPACKAGE: {package}\n"

        messages: list[dict[str, Any]] = []
        action_history: list[dict] = []
        results: list[dict] = []
        repeated_states: list[str] = []

        for step_num in range(1, max_steps + 1):
            logger.info("ai_step_start", step=step_num, serial=serial)

            # ── 1. Capture device state ────────────────────
            state = self._capture_state(serial, package)

            # ── 2. Check for crash / app not running ───────
            if not state["is_running"]:
                logger.warning("ai_app_crashed", step=step_num, serial=serial)
                result = {
                    "step": step_num,
                    "action": "done",
                    "params": {"verdict": "fail", "summary": "App crashed or stopped running"},
                    "reasoning": "App is no longer running — likely crashed",
                    "status": "failed",
                    "confidence": 1.0,
                }
                self._record_step(device_test_run_id, step_num, result)
                results.append(result)
                break

            # ── 3. Build the user message with state ───────
            user_msg = self._build_state_message(state, action_history, step_num, max_steps)
            messages.append({"role": "user", "content": user_msg})

            # ── 4. Detect loop (same UI state repeated) ────
            state_fingerprint = (state.get("current_activity", "") + "|" +
                                 str(hash(state.get("ui_xml", "")[:500])))
            repeated_states.append(state_fingerprint)
            if len(repeated_states) > 3:
                last_3 = repeated_states[-3:]
                if len(set(last_3)) == 1:
                    # Inject a hint to try something different
                    messages.append({
                        "role": "user",
                        "content": "WARNING: You appear to be stuck — the screen has not changed for 3 steps. Try a completely different action or press_back() to navigate elsewhere."
                    })

            # ── 5. Call LLM ────────────────────────────────
            start_time = time.time()
            try:
                if state.get("screenshot_b64"):
                    # Build vision message
                    vision_messages = self._build_vision_messages(messages, state["screenshot_b64"])
                    llm_response = self.llm.chat_with_vision(
                        vision_messages, system_prompt=system_prompt
                    )
                else:
                    llm_response = self.llm.chat(
                        messages, system_prompt=system_prompt
                    )
            except Exception as exc:
                logger.error("ai_llm_error", step=step_num, error=str(exc))
                result = {
                    "step": step_num,
                    "action": "error",
                    "params": {},
                    "reasoning": f"LLM error: {exc}",
                    "status": "error",
                    "confidence": 0.0,
                }
                self._record_step(device_test_run_id, step_num, result)
                results.append(result)
                # Skip this step but continue
                messages.append({"role": "assistant", "content": '{"reasoning": "Error occurred", "action": "wait", "params": {"seconds": 2}}'})
                continue

            llm_time_ms = int((time.time() - start_time) * 1000)

            action = llm_response.get("action", "wait")
            params = llm_response.get("params", {})
            reasoning = llm_response.get("reasoning", "")
            confidence = llm_response.get("confidence", 0.5)

            logger.info(
                "ai_decision",
                step=step_num,
                action=action,
                reasoning=reasoning[:100],
                confidence=confidence,
            )

            # Emit agent thought event
            if self.on_agent_thought:
                try:
                    self.on_agent_thought(device_test_run_id, step_num, {
                        "action": action,
                        "params": params,
                        "reasoning": reasoning,
                        "confidence": confidence,
                    })
                except Exception:
                    pass

            # Add LLM response to message history
            messages.append({"role": "assistant", "content": str(llm_response)})

            # ── 6. Check for "done" action ─────────────────
            if action == "done":
                verdict = params.get("verdict", "pass")
                summary = params.get("summary", "Testing complete")
                result = {
                    "step": step_num,
                    "action": "done",
                    "params": params,
                    "reasoning": reasoning,
                    "status": "passed" if verdict == "pass" else "failed",
                    "confidence": confidence,
                    "llm_time_ms": llm_time_ms,
                }
                self._record_step(device_test_run_id, step_num, result)
                results.append(result)
                logger.info("ai_done", verdict=verdict, summary=summary)
                break

            # ── 7. Execute the action ──────────────────────
            exec_start = time.time()
            action_result = self._execute_action(serial, package, action, params)
            exec_time_ms = int((time.time() - exec_start) * 1000)

            result = {
                "step": step_num,
                "action": action,
                "params": params,
                "reasoning": reasoning,
                "status": "passed" if action_result["success"] else "failed",
                "actual": action_result.get("output", ""),
                "confidence": confidence,
                "llm_time_ms": llm_time_ms,
                "exec_time_ms": exec_time_ms,
            }

            # Take screenshot after action
            ss = self.adb.take_screenshot(serial)
            if ss:
                result["screenshot_path"] = ss

            self._record_step(device_test_run_id, step_num, result)
            results.append(result)

            # Track action history for context
            action_history.append({
                "step": step_num,
                "action": action,
                "params": params,
                "result": action_result.get("output", "")[:200],
                "success": action_result["success"],
            })

            # Notify step completion
            if self.on_step_complete:
                try:
                    self.on_step_complete(device_test_run_id, step_num, result)
                except Exception:
                    pass

            # Keep message history manageable (last 20 exchanges)
            if len(messages) > 40:
                # Keep system context + last 20 messages
                messages = messages[-20:]

        logger.info(
            "ai_execution_complete",
            serial=serial,
            total_steps=len(results),
            passed=sum(1 for r in results if r["status"] == "passed"),
            failed=sum(1 for r in results if r["status"] == "failed"),
        )

        return results

    # ── State Capture ──────────────────────────────────────

    def _capture_state(self, serial: str, package: str) -> dict:
        """Capture the current device state for the AI agent."""
        state = {
            "is_running": self.adb.is_app_running(serial, package),
            "current_activity": self.adb.get_current_activity(serial),
            "ui_xml": self.adb.dump_ui_hierarchy(serial) or "",
            "logcat": self.adb.get_logcat(serial, lines=30),
            "screenshot_b64": None,
        }

        # Try to get screenshot as base64 for vision models
        try:
            state["screenshot_b64"] = self.adb.take_screenshot_base64(serial)
        except Exception:
            pass

        return state

    def _build_state_message(
        self, state: dict, action_history: list, step_num: int, max_steps: int
    ) -> str:
        """Build a text message describing the current device state."""
        parts = [
            f"Step {step_num}/{max_steps}",
            f"App running: {state['is_running']}",
            f"Current activity: {state.get('current_activity', 'unknown')}",
        ]

        if state.get("ui_xml"):
            # Truncate XML if too long
            xml = state["ui_xml"]
            if len(xml) > 8000:
                xml = xml[:8000] + "\n... (truncated)"
            parts.append(f"\n--- UI HIERARCHY ---\n{xml}\n--- END UI ---")

        if state.get("logcat"):
            log = state["logcat"]
            if len(log) > 2000:
                log = log[-2000:]
            parts.append(f"\n--- RECENT LOGS ---\n{log}\n--- END LOGS ---")

        if action_history:
            recent = action_history[-5:]  # Last 5 actions
            history_str = "\n".join(
                f"  Step {h['step']}: {h['action']}({h.get('params', {})}) → {'✓' if h['success'] else '✗'} {h['result'][:100]}"
                for h in recent
            )
            parts.append(f"\n--- RECENT ACTIONS ---\n{history_str}\n--- END ACTIONS ---")

        return "\n".join(parts)

    def _build_vision_messages(
        self, text_messages: list[dict], screenshot_b64: str
    ) -> list[dict]:
        """Build messages with vision content for the last user message."""
        vision_messages = text_messages[:-1].copy()

        # Replace the last user message with a vision-capable format
        last_msg = text_messages[-1]
        vision_messages.append({
            "role": "user",
            "content": [
                {"type": "text", "text": last_msg["content"]},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/png;base64,{screenshot_b64}",
                        "detail": "low",
                    },
                },
            ],
        })

        return vision_messages

    # ── Action Execution ───────────────────────────────────

    def _execute_action(
        self, serial: str, package: str, action: str, params: dict
    ) -> dict:
        """Execute an AI-decided action via ADB."""
        try:
            if action == "tap":
                r = self.adb.input_tap(serial, params.get("x", 0), params.get("y", 0))
                time.sleep(1)
                return {"success": r.success, "output": r.output or r.error}

            elif action == "input_text":
                r = self.adb.input_text(serial, params.get("text", ""))
                return {"success": r.success, "output": r.output or r.error}

            elif action == "swipe":
                r = self.adb.input_swipe(
                    serial,
                    params.get("x1", 0), params.get("y1", 0),
                    params.get("x2", 0), params.get("y2", 0),
                    params.get("duration_ms", 300),
                )
                time.sleep(0.5)
                return {"success": r.success, "output": r.output or r.error}

            elif action == "press_back":
                r = self.adb.press_key(serial, 4)
                time.sleep(0.5)
                return {"success": r.success, "output": "Back pressed"}

            elif action == "press_home":
                r = self.adb.press_key(serial, 3)
                time.sleep(0.5)
                return {"success": r.success, "output": "Home pressed"}

            elif action == "press_key":
                r = self.adb.press_key(serial, params.get("keycode", 66))
                time.sleep(0.3)
                return {"success": r.success, "output": f"Key {params.get('keycode')} pressed"}

            elif action == "wait":
                secs = params.get("seconds", 2)
                time.sleep(secs)
                return {"success": True, "output": f"Waited {secs}s"}

            elif action == "assert_text_visible":
                text = params.get("text", "")
                xml = self.adb.dump_ui_hierarchy(serial) or ""
                found = text.lower() in xml.lower()
                return {
                    "success": found,
                    "output": f"Text '{text}' {'found' if found else 'NOT found'} on screen",
                }

            elif action == "send_broadcast":
                r = self.adb.send_broadcast(
                    serial,
                    params.get("action", ""),
                    params.get("extras", {}),
                    package,
                )
                return {"success": r.success, "output": r.output or r.error}

            elif action == "shell":
                r = self.adb.shell(serial, params.get("command", "echo ok"))
                return {"success": r.success, "output": r.output or r.error}

            elif action == "screenshot":
                path = self.adb.take_screenshot(serial)
                return {"success": path is not None, "output": f"Screenshot: {path}"}

            else:
                return {"success": False, "output": f"Unknown action: {action}"}

        except Exception as exc:
            logger.error("ai_action_error", action=action, error=str(exc))
            return {"success": False, "output": f"Error: {exc}"}

    # ── DB Recording ───────────────────────────────────────

    def _record_step(self, device_test_run_id: int, step_num: int, result: dict) -> None:
        """Record an AI agent step in the database."""
        status_map = {
            "passed": StepStatus.PASSED,
            "failed": StepStatus.FAILED,
            "error": StepStatus.ERROR,
            "skipped": StepStatus.SKIPPED,
        }

        try:
            session = get_session()
            step = TestStep(
                device_test_run_id=device_test_run_id,
                step_number=step_num,
                action=result.get("action", "unknown"),
                params=result.get("params"),
                expected=None,
                actual=result.get("actual", result.get("reasoning", "")),
                status=status_map.get(result.get("status", "error"), StepStatus.ERROR),
                screenshot_path=result.get("screenshot_path"),
                log_snippet=None,
                duration_ms=result.get("exec_time_ms", 0) + result.get("llm_time_ms", 0),
                ai_reasoning=result.get("reasoning"),
                started_at=datetime.datetime.utcnow(),
                completed_at=datetime.datetime.utcnow(),
            )
            session.add(step)
            session.commit()
            session.close()
        except Exception as exc:
            logger.error("ai_db_error", error=str(exc))
