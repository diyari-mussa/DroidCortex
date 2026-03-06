"""
DroidCortex — API Routes: Devices.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from typing import Optional

from backend.models.schemas import DeviceOut, CommandRequest, CommandResponse
from backend.services.device_manager import device_manager
from backend.services.adb_service import adb_service

router = APIRouter(prefix="/api/devices", tags=["devices"])


@router.get("", response_model=list[DeviceOut])
async def list_devices():
    """List all known devices with their current status."""
    devices = device_manager.get_all_devices()
    return [
        DeviceOut(
            serial=d["serial"],
            model=d.get("model"),
            api_level=d.get("api_level"),
            device_type=d.get("device_type", "physical"),
            status=d["status"],
        )
        for d in devices
    ]


@router.get("/{serial}", response_model=DeviceOut)
async def get_device(serial: str):
    """Get details for a specific device."""
    d = device_manager.get_device(serial)
    if not d:
        raise HTTPException(404, f"Device {serial} not found")
    return DeviceOut(
        serial=d["serial"],
        model=d.get("model"),
        api_level=d.get("api_level"),
        device_type=d.get("device_type", "physical"),
        status=d["status"],
    )


@router.post("/refresh")
async def refresh_devices():
    """Force a device refresh scan."""
    devices = device_manager.refresh_devices()
    return {"count": len(devices), "devices": devices}


@router.post("/{serial}/command", response_model=CommandResponse)
async def send_command(serial: str, body: CommandRequest):
    """Execute a command on a device. Supports structured commands (command + args) or plain shell strings."""
    d = device_manager.get_device(serial)
    if not d:
        raise HTTPException(404, f"Device {serial} not found")
    if d["status"] == "offline":
        raise HTTPException(400, f"Device {serial} is offline")

    args = body.args or {}
    cmd = body.command

    if cmd == "shell":
        shell_cmd = args.get("command", "")
        result = adb_service.shell(serial, shell_cmd)
    elif cmd == "install":
        apk_path = args.get("apk_path", "")
        from backend.config import settings
        import os
        full_path = os.path.join(settings.apk_storage_path, apk_path)
        result = adb_service.install_apk(serial, full_path)
    elif cmd == "launch":
        pkg = args.get("package_name", "")
        activity = args.get("activity", "")
        result = adb_service.launch_app(serial, pkg, activity)
    elif cmd == "force_stop":
        pkg = args.get("package_name", "")
        result = adb_service.force_stop(serial, pkg)
    elif cmd == "clear_data":
        pkg = args.get("package_name", "")
        result = adb_service.clear_data(serial, pkg)
    elif cmd == "reboot":
        result = adb_service.reboot(serial)
    else:
        # Treat the command string itself as a plain shell command
        result = adb_service.shell(serial, cmd)

    return CommandResponse(
        success=result.success,
        output=result.output,
        error=result.error if not result.success else None,
    )


@router.get("/{serial}/screenshot")
async def get_screenshot(serial: str):
    """Take a live screenshot from a device."""
    from fastapi.responses import Response

    d = device_manager.get_device(serial)
    if not d:
        raise HTTPException(404, f"Device {serial} not found")

    ok, data, err = adb_service._run_binary(
        ["exec-out", "screencap", "-p"], serial=serial, timeout=10
    )
    if ok and data:
        return Response(content=data, media_type="image/png")
    raise HTTPException(500, f"Screenshot failed: {err}")


@router.post("/{serial}/reboot")
async def reboot_device(serial: str):
    """Reboot a device."""
    result = adb_service.reboot(serial)
    return {"success": result.success, "message": result.output or result.error}
