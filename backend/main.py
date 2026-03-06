"""
DroidCortex — Main Application Entry Point.
Creates the FastAPI app with all routes, Socket.IO, and startup/shutdown hooks.

Run with:
    uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import socketio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path

import structlog

from backend.config import settings, ensure_data_dirs

logger = structlog.get_logger(__name__)


# ── Lifespan (startup/shutdown) ────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown logic."""
    # ── STARTUP ────────────────────────────────────────────
    logger.info("droidcortex_starting", host=settings.host, port=settings.port)

    # Ensure data directories exist
    ensure_data_dirs()

    # Initialize database tables
    from backend.models.database import init_db
    init_db()

    # Load known devices from DB
    from backend.services.device_manager import device_manager
    device_manager.load_from_db()

    # Wire orchestrator → Socket.IO events
    from backend.api.websocket import setup_orchestrator_events, emit_sync
    setup_orchestrator_events()

    # Store the main event loop reference for emit_sync to use from worker threads
    import asyncio
    emit_sync._main_loop = asyncio.get_running_loop()

    # Start device polling
    await device_manager.start_polling()

    # Do initial device scan
    device_manager.refresh_devices()

    logger.info("droidcortex_ready")

    yield  # ── APP RUNNING ─────────────────────────────────

    # ── SHUTDOWN ───────────────────────────────────────────
    logger.info("droidcortex_shutting_down")
    await device_manager.stop_polling()
    logger.info("droidcortex_stopped")


# ── Create FastAPI app ─────────────────────────────────────────

app = FastAPI(
    title="DroidCortex",
    description="Android APK Test Orchestration Platform",
    version="0.1.0",
    lifespan=lifespan,
)

# ── CORS ───────────────────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        settings.frontend_url,
        "http://localhost:5173",
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Include API routers ───────────────────────────────────────

from backend.api.devices import router as devices_router
from backend.api.test_runs import router as test_runs_router
from backend.api.apks import router as apks_router
from backend.api.config import router as config_router

app.include_router(devices_router)
app.include_router(test_runs_router)
app.include_router(apks_router)
app.include_router(config_router)


# ── Mount Socket.IO ────────────────────────────────────────────

from backend.api.websocket import sio

socket_app = socketio.ASGIApp(sio, other_asgi_app=app)

# Expose the combined ASGI app for uvicorn
# Use `backend.main:combined_app` or `backend.main:app` (app works since socket.io mounts on same path)
combined_app = socket_app


# ── Serve screenshots as static files ─────────────────────────

screenshots_dir = Path(settings.screenshot_storage_path)
screenshots_dir.mkdir(parents=True, exist_ok=True)
app.mount(
    "/screenshots",
    StaticFiles(directory=str(screenshots_dir)),
    name="screenshots",
)


# ── Health check ───────────────────────────────────────────────

@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "service": "DroidCortex",
        "version": "0.1.0",
    }


# ── Root redirect ─────────────────────────────────────────────

@app.get("/")
async def root():
    return {
        "service": "DroidCortex API",
        "docs": "/docs",
        "health": "/api/health",
    }
