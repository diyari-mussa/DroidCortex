"""
DroidCortex — WebSocket event layer using python-socketio.
Provides real-time communication between backend and dashboard.
"""

from __future__ import annotations

import socketio
import structlog

from backend.config import settings

logger = structlog.get_logger(__name__)

# Create Socket.IO server (async mode for FastAPI)
sio = socketio.AsyncServer(
    async_mode="asgi",
    cors_allowed_origins=[settings.frontend_url, "http://localhost:5173", "http://localhost:3000"],
    logger=False,
    engineio_logger=False,
)


@sio.event
async def connect(sid, environ):
    logger.info("ws_client_connected", sid=sid)
    await sio.emit("server:hello", {"message": "Connected to DroidCortex"}, to=sid)


@sio.event
async def disconnect(sid):
    logger.info("ws_client_disconnected", sid=sid)


@sio.on("client:request_devices")
async def handle_request_devices(sid):
    """Client requests current device list."""
    from backend.services.device_manager import device_manager

    devices = device_manager.get_all_devices()
    await sio.emit("device:list", {"devices": devices}, to=sid)


@sio.on("client:send_command")
async def handle_send_command(sid, data):
    """Client sends an ADB command to a device."""
    from backend.services.adb_service import adb_service

    serial = data.get("serial")
    command = data.get("command")
    if not serial or not command:
        await sio.emit("command:error", {"error": "Missing serial or command"}, to=sid)
        return

    result = adb_service.shell(serial, command)
    await sio.emit(
        "command:result",
        {
            "serial": serial,
            "command": command,
            "success": result.success,
            "output": result.output,
            "error": result.error,
        },
        to=sid,
    )


# ── Broadcast helpers (called from orchestrator/workers) ───────


def emit_sync(event_name: str, data: dict) -> None:
    """Emit a Socket.IO event from synchronous code (e.g., worker threads).
    Uses asyncio.run_coroutine_threadsafe for thread-safe async calls.
    """
    try:
        import asyncio

        loop = None
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            pass

        if loop and loop.is_running():
            # We're in an async context — schedule it
            asyncio.ensure_future(sio.emit(event_name, data))
        else:
            # We're in a sync worker thread — find the main event loop
            # and schedule the coroutine there
            try:
                # Try to get the main event loop
                import threading
                main_loop = getattr(emit_sync, '_main_loop', None)
                if main_loop and main_loop.is_running():
                    asyncio.run_coroutine_threadsafe(sio.emit(event_name, data), main_loop)
                else:
                    # Fallback: create a new event loop just for this call
                    asyncio.run(sio.emit(event_name, data))
            except Exception:
                # Last resort fallback
                asyncio.run(sio.emit(event_name, data))
    except Exception as exc:
        logger.warning("ws_emit_error", evt=event_name, error=str(exc))


def setup_orchestrator_events() -> None:
    """Wire the orchestrator to emit Socket.IO events."""
    from backend.engine.orchestrator import orchestrator

    orchestrator.on_event = emit_sync
    logger.info("orchestrator_events_wired")
