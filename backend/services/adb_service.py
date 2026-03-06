"""
DroidCortex — ADB Service.
Provides a clean interface to Android Debug Bridge operations using both
`adbutils` library and subprocess calls for maximum compatibility.
"""

from __future__ import annotations

import base64
import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import structlog

from backend.config import settings

logger = structlog.get_logger(__name__)


@dataclass
class DeviceInfo:
    """Basic info about a connected Android device."""

    serial: str
    state: str  # "device", "offline", "unauthorized"
    model: Optional[str] = None
    product: Optional[str] = None
    transport_id: Optional[str] = None
    api_level: Optional[int] = None
    is_emulator: bool = False
    properties: dict = field(default_factory=dict)


@dataclass
class APKInfo:
    """Metadata extracted from an APK file."""

    package_name: str
    main_activity: Optional[str] = None
    version_name: Optional[str] = None
    version_code: Optional[int] = None
    min_sdk: Optional[int] = None
    target_sdk: Optional[int] = None


@dataclass
class CommandResult:
    """Result of an ADB command execution."""

    success: bool
    output: str = ""
    error: str = ""
    return_code: int = 0


class ADBService:
    """Wraps ADB CLI calls for device interaction."""

    def __init__(self, adb_path: str | None = None):
        self.adb_path = adb_path or settings.adb_path

    # ── Helpers ────────────────────────────────────────────

    def _run(
        self,
        args: list[str],
        timeout: int = 30,
        serial: str | None = None,
    ) -> CommandResult:
        """Execute an ADB command via subprocess."""
        cmd = [self.adb_path]
        if serial:
            cmd.extend(["-s", serial])
        cmd.extend(args)

        logger.debug("adb_command", cmd=" ".join(cmd))
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                creationflags=subprocess.CREATE_NO_WINDOW
                if os.name == "nt"
                else 0,
            )
            return CommandResult(
                success=proc.returncode == 0,
                output=proc.stdout.strip(),
                error=proc.stderr.strip(),
                return_code=proc.returncode,
            )
        except subprocess.TimeoutExpired:
            logger.warning("adb_timeout", cmd=" ".join(cmd), timeout=timeout)
            return CommandResult(success=False, error=f"Command timed out after {timeout}s")
        except FileNotFoundError:
            return CommandResult(
                success=False,
                error=f"ADB not found at '{self.adb_path}'. Ensure Android SDK is installed.",
            )
        except Exception as exc:
            logger.error("adb_error", cmd=" ".join(cmd), error=str(exc))
            return CommandResult(success=False, error=str(exc))

    def _run_binary(
        self,
        args: list[str],
        timeout: int = 30,
        serial: str | None = None,
    ) -> tuple[bool, bytes, str]:
        """Execute an ADB command returning binary output (e.g., screencap)."""
        cmd = [self.adb_path]
        if serial:
            cmd.extend(["-s", serial])
        cmd.extend(args)

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                timeout=timeout,
                creationflags=subprocess.CREATE_NO_WINDOW
                if os.name == "nt"
                else 0,
            )
            return proc.returncode == 0, proc.stdout, proc.stderr.decode(errors="replace")
        except Exception as exc:
            return False, b"", str(exc)

    # ── Device Discovery ───────────────────────────────────

    def list_devices(self) -> list[DeviceInfo]:
        """List all connected devices with details."""
        result = self._run(["devices", "-l"])
        if not result.success:
            logger.error("list_devices_failed", error=result.error)
            return []

        devices: list[DeviceInfo] = []
        for line in result.output.splitlines()[1:]:  # skip header
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) < 2:
                continue

            serial = parts[0]
            state = parts[1]

            # Parse key:value properties from the line
            props = {}
            for part in parts[2:]:
                if ":" in part:
                    k, v = part.split(":", 1)
                    props[k] = v

            info = DeviceInfo(
                serial=serial,
                state=state,
                model=props.get("model"),
                product=props.get("product"),
                transport_id=props.get("transport_id"),
                is_emulator=serial.startswith("emulator-"),
                properties=props,
            )

            # Fetch API level if device is online
            if state == "device":
                api_result = self._run(
                    ["shell", "getprop", "ro.build.version.sdk"],
                    serial=serial,
                    timeout=5,
                )
                if api_result.success and api_result.output.strip().isdigit():
                    info.api_level = int(api_result.output.strip())

            devices.append(info)

        return devices

    # ── APK Management ─────────────────────────────────────

    def install_apk(self, serial: str, apk_path: str) -> CommandResult:
        """Install an APK on a device. Returns result."""
        logger.info("install_apk", serial=serial, apk=apk_path)
        if not Path(apk_path).exists():
            return CommandResult(success=False, error=f"APK file not found: {apk_path}")
        return self._run(["install", "-r", "-t", apk_path], serial=serial, timeout=120)

    def uninstall_apk(self, serial: str, package: str) -> CommandResult:
        """Uninstall an app by package name."""
        logger.info("uninstall_apk", serial=serial, package=package)
        return self._run(["uninstall", package], serial=serial, timeout=30)

    def analyze_apk(self, apk_path: str) -> APKInfo | None:
        """Extract package name, main activity, version, etc. from an APK using aapt2/aapt."""
        for tool in ("aapt2", "aapt"):
            try:
                proc = subprocess.run(
                    [tool, "dump", "badging", apk_path],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    creationflags=subprocess.CREATE_NO_WINDOW
                    if os.name == "nt"
                    else 0,
                )
                if proc.returncode == 0:
                    return self._parse_aapt_output(proc.stdout)
            except FileNotFoundError:
                continue
            except Exception:
                continue

        logger.warning("analyze_apk_failed", apk=apk_path, msg="aapt2/aapt not found, trying Python fallback")
        return self._analyze_apk_python(apk_path)

    def _parse_aapt_output(self, output: str) -> APKInfo:
        """Parse aapt/aapt2 dump badging output."""
        pkg_match = re.search(r"package: name='([^']+)'", output)
        ver_name = re.search(r"versionName='([^']+)'", output)
        ver_code = re.search(r"versionCode='([^']+)'", output)
        min_sdk_m = re.search(r"sdkVersion:'(\d+)'", output)
        target_sdk_m = re.search(r"targetSdkVersion:'(\d+)'", output)
        activity_match = re.search(r"launchable-activity: name='([^']+)'", output)

        return APKInfo(
            package_name=pkg_match.group(1) if pkg_match else "unknown",
            main_activity=activity_match.group(1) if activity_match else None,
            version_name=ver_name.group(1) if ver_name else None,
            version_code=int(ver_code.group(1)) if ver_code else None,
            min_sdk=int(min_sdk_m.group(1)) if min_sdk_m else None,
            target_sdk=int(target_sdk_m.group(1)) if target_sdk_m else None,
        )

    def _analyze_apk_python(self, apk_path: str) -> APKInfo | None:
        """Fallback APK analysis using Python zipfile to read AndroidManifest.xml.
        Extracts package name from the binary XML manifest.
        """
        import zipfile
        import struct

        try:
            with zipfile.ZipFile(apk_path, 'r') as zf:
                if 'AndroidManifest.xml' not in zf.namelist():
                    return None

                data = zf.read('AndroidManifest.xml')

                # Binary XML: extract UTF-16 strings from the string pool
                # The package name is typically one of the first strings
                strings = self._extract_strings_from_binary_xml(data)

                # Look for package-name-like strings (com.xxx.xxx pattern)
                package_name = None
                for s in strings:
                    if re.match(r'^[a-zA-Z][a-zA-Z0-9]*(\.[a-zA-Z][a-zA-Z0-9]*){1,}$', s):
                        # Prefer longer matches (actual package names vs short ones)
                        if not package_name or (len(s) > len(package_name) and '.' in s):
                            package_name = s

                if package_name:
                    logger.info("apk_package_from_manifest", package=package_name)
                    return APKInfo(
                        package_name=package_name,
                        main_activity=None,
                        version_name=None,
                        version_code=None,
                        min_sdk=None,
                        target_sdk=None,
                    )
        except Exception as exc:
            logger.warning("python_apk_analysis_failed", error=str(exc))

        return None

    def _extract_strings_from_binary_xml(self, data: bytes) -> list[str]:
        """Extract string pool from Android binary XML format."""
        strings = []
        try:
            # Android binary XML header:
            # Offset 8: string pool chunk
            # Offset 16 (in string pool): string count
            # Offset 20: style count
            # Offset 28: strings start offset (relative to string pool start)
            if len(data) < 40:
                return strings

            # Find string pool chunk (type 0x0001)
            pos = 8
            if pos + 8 > len(data):
                return strings

            chunk_type = struct.unpack_from('<H', data, pos)[0]
            if chunk_type != 0x0001:
                return strings

            str_count = struct.unpack_from('<I', data, pos + 8)[0]
            _style_count = struct.unpack_from('<I', data, pos + 12)[0]
            flags = struct.unpack_from('<I', data, pos + 16)[0]
            strings_start = struct.unpack_from('<I', data, pos + 20)[0]

            is_utf8 = bool(flags & (1 << 8))

            # String offsets start at pos + 28
            offsets_start = pos + 28
            pool_start = pos + strings_start

            for i in range(min(str_count, 200)):  # Limit to avoid huge loops
                if offsets_start + i * 4 + 4 > len(data):
                    break
                str_offset = struct.unpack_from('<I', data, offsets_start + i * 4)[0]
                abs_offset = pool_start + str_offset

                if abs_offset >= len(data):
                    break

                if is_utf8:
                    # UTF-8: skip char count (1-2 bytes), then byte count (1-2 bytes)
                    char_count = data[abs_offset]
                    abs_offset += 1
                    if char_count & 0x80:
                        abs_offset += 1
                    byte_count = data[abs_offset]
                    abs_offset += 1
                    if byte_count & 0x80:
                        byte_count = ((byte_count & 0x7F) << 8) | data[abs_offset]
                        abs_offset += 1
                    if abs_offset + byte_count <= len(data):
                        try:
                            s = data[abs_offset:abs_offset + byte_count].decode('utf-8', errors='ignore')
                            if s and len(s) > 1:
                                strings.append(s)
                        except Exception:
                            pass
                else:
                    # UTF-16
                    if abs_offset + 2 > len(data):
                        break
                    char_count = struct.unpack_from('<H', data, abs_offset)[0]
                    abs_offset += 2
                    if char_count & 0x8000:
                        char_count = ((char_count & 0x7FFF) << 16) | struct.unpack_from('<H', data, abs_offset)[0]
                        abs_offset += 2
                    byte_len = char_count * 2
                    if abs_offset + byte_len <= len(data):
                        try:
                            s = data[abs_offset:abs_offset + byte_len].decode('utf-16-le', errors='ignore')
                            if s and len(s) > 1:
                                strings.append(s)
                        except Exception:
                            pass
        except Exception:
            pass
        return strings

    # ── App Lifecycle ──────────────────────────────────────

    def launch_app(
        self, serial: str, package: str, activity: str | None = None
    ) -> CommandResult:
        """Launch an app. If activity not given, use monkey to launch main."""
        if activity:
            component = f"{package}/{activity}"
            if not activity.startswith(package) and not activity.startswith("."):
                component = f"{package}/{activity}"
            return self._run(
                ["shell", "am", "start", "-n", component], serial=serial
            )
        else:
            # Use monkey to launch the default activity
            return self._run(
                [
                    "shell",
                    "monkey",
                    "-p",
                    package,
                    "-c",
                    "android.intent.category.LAUNCHER",
                    "1",
                ],
                serial=serial,
            )

    def is_app_running(self, serial: str, package: str) -> bool:
        """Check if an app process is currently running."""
        result = self._run(["shell", "pidof", package], serial=serial, timeout=5)
        return result.success and bool(result.output.strip())

    def force_stop(self, serial: str, package: str) -> CommandResult:
        """Force-stop an app."""
        return self._run(["shell", "am", "force-stop", package], serial=serial)

    def clear_data(self, serial: str, package: str) -> CommandResult:
        """Clear app data."""
        return self._run(["shell", "pm", "clear", package], serial=serial)

    # ── Intents & Broadcasts ───────────────────────────────

    def send_broadcast(
        self,
        serial: str,
        action: str,
        extras: dict[str, str] | None = None,
        package: str | None = None,
    ) -> CommandResult:
        """Send a broadcast intent."""
        cmd = ["shell", "am", "broadcast", "-a", action]
        if package:
            cmd.extend(["-p", package])
        if extras:
            for key, value in extras.items():
                cmd.extend(["--es", key, str(value)])
        return self._run(cmd, serial=serial)

    def send_intent(
        self,
        serial: str,
        action: str,
        data_uri: str | None = None,
        extras: dict[str, str] | None = None,
    ) -> CommandResult:
        """Send an activity intent (deep link)."""
        cmd = ["shell", "am", "start", "-a", action]
        if data_uri:
            cmd.extend(["-d", data_uri])
        if extras:
            for key, value in extras.items():
                cmd.extend(["--es", key, str(value)])
        return self._run(cmd, serial=serial)

    # ── UI Interaction ─────────────────────────────────────

    def input_tap(self, serial: str, x: int, y: int) -> CommandResult:
        """Tap at coordinates."""
        return self._run(["shell", "input", "tap", str(x), str(y)], serial=serial)

    def input_text(self, serial: str, text: str) -> CommandResult:
        """Type text. Spaces are handled by replacing with %s."""
        escaped = text.replace(" ", "%s").replace("&", "\\&")
        return self._run(["shell", "input", "text", escaped], serial=serial)

    def input_swipe(
        self, serial: str, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300
    ) -> CommandResult:
        """Swipe gesture."""
        return self._run(
            [
                "shell",
                "input",
                "swipe",
                str(x1),
                str(y1),
                str(x2),
                str(y2),
                str(duration_ms),
            ],
            serial=serial,
        )

    def press_key(self, serial: str, keycode: int | str) -> CommandResult:
        """Press a key by keycode (e.g., 3=HOME, 4=BACK, 66=ENTER)."""
        return self._run(
            ["shell", "input", "keyevent", str(keycode)], serial=serial
        )

    # ── Screen Capture & UI ────────────────────────────────

    def take_screenshot(self, serial: str, save_path: str | None = None) -> str | None:
        """Take a screenshot. Returns the file path or None on failure.
        If save_path is not given, saves to screenshots dir with timestamp.
        """
        if save_path is None:
            ts = int(time.time() * 1000)
            save_path = str(
                Path(settings.screenshot_storage_path)
                / f"{serial}_{ts}.png"
            )

        Path(save_path).parent.mkdir(parents=True, exist_ok=True)

        ok, data, err = self._run_binary(
            ["exec-out", "screencap", "-p"], serial=serial, timeout=10
        )
        if ok and data:
            with open(save_path, "wb") as f:
                f.write(data)
            logger.info("screenshot_saved", serial=serial, path=save_path)
            return save_path
        else:
            logger.error("screenshot_failed", serial=serial, error=err)
            return None

    def take_screenshot_base64(self, serial: str) -> str | None:
        """Take a screenshot and return as base64-encoded PNG string."""
        ok, data, err = self._run_binary(
            ["exec-out", "screencap", "-p"], serial=serial, timeout=10
        )
        if ok and data:
            return base64.b64encode(data).decode("ascii")
        return None

    def dump_ui_hierarchy(self, serial: str) -> str | None:
        """Dump the current UI hierarchy as XML. Used by AI agent."""
        result = self._run(
            ["exec-out", "uiautomator", "dump", "/dev/tty"],
            serial=serial,
            timeout=10,
        )
        if result.success:
            # uiautomator dump outputs XML followed by "UI hierchary dumped to..."
            xml_output = result.output
            # Remove the trailing status message
            if "UI hierarch" in xml_output:
                xml_output = xml_output[: xml_output.index("UI hierarch")].strip()
            return xml_output
        return None

    # ── Logcat ─────────────────────────────────────────────

    def get_logcat(
        self,
        serial: str,
        tag: str | None = None,
        lines: int = 100,
        level: str = "V",
    ) -> str:
        """Get recent logcat output, optionally filtered by tag."""
        cmd = ["shell", "logcat", "-d", "-t", str(lines)]
        if tag:
            cmd.extend(["-s", f"{tag}:{level}"])
        result = self._run(cmd, serial=serial, timeout=10)
        return result.output if result.success else ""

    def clear_logcat(self, serial: str) -> CommandResult:
        """Clear the logcat buffer."""
        return self._run(["shell", "logcat", "-c"], serial=serial)

    # ── Generic Shell ──────────────────────────────────────

    def shell(self, serial: str, command: str, timeout: int = 30) -> CommandResult:
        """Execute an arbitrary shell command on the device."""
        return self._run(["shell", command], serial=serial, timeout=timeout)

    def get_current_activity(self, serial: str) -> str | None:
        """Get the currently focused activity."""
        result = self._run(
            ["shell", "dumpsys", "activity", "activities"],
            serial=serial,
            timeout=10,
        )
        if result.success:
            # Look for the "mResumedActivity" or "mFocusedActivity" line
            for line in result.output.splitlines():
                if "mResumedActivity" in line or "mFocusedActivity" in line:
                    match = re.search(r"(\S+/\S+)", line)
                    if match:
                        return match.group(1)
        return None

    def get_device_property(
        self, serial: str, prop: str
    ) -> str | None:
        """Get a single device property."""
        result = self._run(
            ["shell", "getprop", prop], serial=serial, timeout=5
        )
        return result.output.strip() if result.success else None

    # ── Reboot & Misc ──────────────────────────────────────

    def reboot(self, serial: str) -> CommandResult:
        """Reboot the device."""
        return self._run(["reboot"], serial=serial, timeout=10)

    def wait_for_device(self, serial: str, timeout: int = 60) -> bool:
        """Wait until device comes online."""
        result = self._run(
            ["wait-for-device"], serial=serial, timeout=timeout
        )
        return result.success

    def list_packages(self, serial: str) -> list[str]:
        """List all installed packages."""
        result = self._run(
            ["shell", "pm", "list", "packages"], serial=serial, timeout=10
        )
        if result.success:
            return [
                line.replace("package:", "").strip()
                for line in result.output.splitlines()
                if line.startswith("package:")
            ]
        return []


# ── Module-level singleton ─────────────────────────────────────
adb_service = ADBService()
