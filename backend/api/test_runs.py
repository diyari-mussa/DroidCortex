"""
DroidCortex — API Routes: Test Runs.
"""

from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import joinedload

from backend.models.database import (
    TestRun,
    DeviceTestRun,
    TestStep,
    TestRunStatus,
    get_session,
)
from backend.models.schemas import (
    TestRunCreate,
    TestRunOut,
    TestRunSummary,
    DeviceTestRunOut,
    TestStepOut,
)
from backend.engine.orchestrator import orchestrator

router = APIRouter(prefix="/api/test-runs", tags=["test-runs"])


@router.post("", response_model=dict)
async def create_test_run(body: TestRunCreate):
    """Start a new test run."""
    try:
        steps = [s.model_dump() for s in body.steps] if body.steps else []
        ai_config = body.ai_config.model_dump() if body.ai_config else {}

        run_id = orchestrator.start_test_run(
            apk_id=body.apk_id,
            mode=body.mode.value,
            target_devices=body.target_devices or None,
            steps=steps,
            ai_config=ai_config,
            name=body.name,
        )
        return {"id": run_id, "status": "started"}
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        raise HTTPException(500, str(exc))


@router.get("", response_model=list[TestRunSummary])
async def list_test_runs(
    limit: int = 50,
    offset: int = 0,
    status: Optional[str] = None,
):
    """List all test runs with summary info."""
    session = get_session()
    try:
        query = session.query(TestRun).order_by(TestRun.created_at.desc())
        if status:
            query = query.filter(TestRun.status == status)
        runs = query.offset(offset).limit(limit).all()

        return [
            TestRunSummary(
                id=r.id,
                name=r.name,
                mode=r.mode.value,
                status=r.status.value,
                total_devices=r.total_devices,
                completed_devices=r.completed_devices,
                created_at=r.created_at,
                completed_at=r.completed_at,
            )
            for r in runs
        ]
    finally:
        session.close()


@router.get("/{run_id}", response_model=TestRunOut)
async def get_test_run(run_id: int):
    """Get full details for a test run including device results."""
    session = get_session()
    try:
        run = (
            session.query(TestRun)
            .options(
                joinedload(TestRun.device_test_runs).joinedload(
                    DeviceTestRun.steps
                )
            )
            .filter_by(id=run_id)
            .first()
        )
        if not run:
            raise HTTPException(404, f"Test run {run_id} not found")

        return TestRunOut(
            id=run.id,
            name=run.name,
            apk_id=run.apk_id,
            mode=run.mode.value,
            status=run.status.value,
            config=run.config,
            target_devices=run.target_devices,
            created_at=run.created_at,
            completed_at=run.completed_at,
            device_test_runs=[
                DeviceTestRunOut(
                    id=dtr.id,
                    device_serial=dtr.device_serial,
                    status=dtr.status.value,
                    started_at=dtr.started_at,
                    completed_at=dtr.completed_at,
                    error_message=dtr.error_message,
                    summary=dtr.summary,
                    steps=[
                        TestStepOut(
                            id=s.id,
                            step_number=s.step_number,
                            action=s.action,
                            params=s.params,
                            expected=s.expected,
                            actual=s.actual,
                            status=s.status.value,
                            screenshot_path=s.screenshot_path,
                            log_snippet=s.log_snippet,
                            duration_ms=s.duration_ms,
                            ai_reasoning=s.ai_reasoning,
                            started_at=s.started_at,
                            completed_at=s.completed_at,
                        )
                        for s in sorted(dtr.steps, key=lambda x: x.step_number)
                    ],
                )
                for dtr in run.device_test_runs
            ],
        )
    finally:
        session.close()


@router.get("/{run_id}/steps")
async def get_test_run_steps(run_id: int, device_serial: Optional[str] = None):
    """Get step-by-step results for a test run, optionally filtered by device."""
    session = get_session()
    try:
        query = (
            session.query(TestStep)
            .join(DeviceTestRun)
            .filter(DeviceTestRun.test_run_id == run_id)
        )
        if device_serial:
            query = query.filter(DeviceTestRun.device_serial == device_serial)
        query = query.order_by(TestStep.step_number)

        steps = query.all()
        return [
            TestStepOut(
                id=s.id,
                step_number=s.step_number,
                action=s.action,
                params=s.params,
                expected=s.expected,
                actual=s.actual,
                status=s.status.value,
                screenshot_path=s.screenshot_path,
                log_snippet=s.log_snippet,
                duration_ms=s.duration_ms,
                ai_reasoning=s.ai_reasoning,
                started_at=s.started_at,
                completed_at=s.completed_at,
            )
            for s in steps
        ]
    finally:
        session.close()


@router.post("/{run_id}/abort")
async def abort_test_run(run_id: int):
    """Abort a running test."""
    success = orchestrator.abort_test_run(run_id)
    if success:
        return {"status": "abort_requested", "run_id": run_id}
    raise HTTPException(400, "Test run is not active or already completed")
