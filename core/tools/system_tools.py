#!/usr/bin/env python3
"""
Cross-Platform System Tools (formerly macOS-specific)
======================================================
Tools that work across platforms with graceful fallbacks.

Available Tools:
- clipboard: Read/write system clipboard (macOS, Linux, Windows)
- notification: Send desktop notifications (macOS, Linux, Windows)
- system_info: Get system information (cross-platform via psutil)
- file_watcher: Watch files for changes (cross-platform)

Platform Support:
- macOS: Full support via native tools (pbcopy/pbpaste, osascript)
- Linux: Support via xclip/xsel/wl-clipboard, notify-send
- Windows: Support via clip.exe, PowerShell, native notifications
- Fallback: pyperclip library for clipboard, logging for notifications

Author: Torin AI Team
"""

import logging
import platform
import subprocess
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from .tool_registry import Tool, ToolParameter, ToolResult, ToolCategory, ToolSafety
from .capabilities import Capability, ToolCapabilityProfile, CapabilityMetadata


logger = logging.getLogger(__name__)


def detect_clipboard_backend() -> Tuple[str, Optional[str]]:
    """
    Detect available clipboard backend for the current platform.

    Returns:
        Tuple of (platform_type, command/method)
        platform_type: 'macos', 'linux', 'windows', 'pyperclip', 'none'
        command/method: The specific command or library to use
    """
    system = platform.system()

    if system == "Darwin":
        # macOS - pbcopy/pbpaste always available
        return ("macos", "pbcopy/pbpaste")

    elif system == "Linux":
        # Linux - check for available clipboard managers
        if shutil.which("xclip"):
            return ("linux", "xclip")
        elif shutil.which("xsel"):
            return ("linux", "xsel")
        elif shutil.which("wl-copy"):  # Wayland
            return ("linux", "wl-clipboard")
        else:
            # Try pyperclip as fallback
            try:
                import pyperclip
                return ("pyperclip", "pyperclip")
            except ImportError:
                return ("none", None)

    elif system == "Windows":
        # Windows - clip.exe for write, PowerShell for read
        return ("windows", "clip.exe")

    else:
        # Unknown platform - try pyperclip
        try:
            import pyperclip
            return ("pyperclip", "pyperclip")
        except ImportError:
            return ("none", None)


def detect_notification_backend() -> Tuple[str, Optional[str]]:
    """
    Detect available notification backend for the current platform.

    Returns:
        Tuple of (platform_type, command/method)
    """
    system = platform.system()

    if system == "Darwin":
        # macOS - osascript always available
        return ("macos", "osascript")

    elif system == "Linux":
        # Linux - check for notify-send
        if shutil.which("notify-send"):
            return ("linux", "notify-send")
        else:
            return ("log", "logger")

    elif system == "Windows":
        # Windows - PowerShell BurntToast or native
        return ("windows", "powershell")

    else:
        return ("log", "logger")


class ClipboardTool(Tool):
    """Access system clipboard (cross-platform)"""

    def __init__(self):
        super().__init__()
        self.name = "clipboard"
        self.description = "Read from or write to the system clipboard (macOS, Linux, Windows with fallbacks)"
        self.category = ToolCategory.SYSTEM
        self.safety_level = ToolSafety.MODERATE
        self.parameters = [
            ToolParameter(
                name="action",
                type="string",
                description="Action to perform: 'read' or 'write'",
                required=True,
                enum=["read", "write"]
            ),
            ToolParameter(
                name="content",
                type="string",
                description="Content to write to clipboard (required for 'write' action)",
                required=False
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="clipboard",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.MANAGE_PROCESS,
                    description="Clipboard capability"
                )
            ]
        )

    async def execute(self, action: str, content: Optional[str] = None) -> ToolResult:
        """Access clipboard with cross-platform support"""
        try:
            platform_type, backend = detect_clipboard_backend()

            if platform_type == "none":
                return ToolResult(
                    success=False,
                    output=None,
                    error="No clipboard backend available. Install xclip (Linux) or pyperclip: pip install pyperclip"
                )

            if action == "read":
                return await self._read_clipboard(platform_type, backend)
            elif action == "write":
                if content is None:
                    return ToolResult(
                        success=False,
                        output=None,
                        error="Content required for write action"
                    )
                return await self._write_clipboard(platform_type, backend, content)

        except subprocess.TimeoutExpired:
            return ToolResult(
                success=False,
                output=None,
                error="Clipboard operation timed out"
            )
        except PermissionError as e:
            return ToolResult(
                success=False,
                output=None,
                error=f"Permission denied. On macOS, grant Terminal accessibility permissions in System Settings > Privacy & Security > Accessibility"
            )
        except Exception as e:
            logger.error(f"Error accessing clipboard: {e}")
            return ToolResult(
                success=False,
                output=None,
                error=str(e)
            )

    async def _read_clipboard(self, platform_type: str, backend: str) -> ToolResult:
        """Read from clipboard based on platform"""
        if platform_type == "macos":
            result = subprocess.run(
                ["pbpaste"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode != 0:
                return ToolResult(success=False, output=None, error="Failed to read clipboard")
            return ToolResult(
                success=True,
                output={"content": result.stdout, "backend": "pbpaste"}
            )

        elif platform_type == "linux":
            if backend == "xclip":
                cmd = ["xclip", "-selection", "clipboard", "-o"]
            elif backend == "xsel":
                cmd = ["xsel", "--clipboard", "--output"]
            elif backend == "wl-clipboard":
                cmd = ["wl-paste"]
            else:
                return ToolResult(success=False, output=None, error="Unknown Linux clipboard backend")

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            if result.returncode != 0:
                return ToolResult(success=False, output=None, error=f"Failed to read clipboard: {result.stderr}")
            return ToolResult(
                success=True,
                output={"content": result.stdout, "backend": backend}
            )

        elif platform_type == "windows":
            # Use PowerShell Get-Clipboard
            result = subprocess.run(
                ["powershell", "-Command", "Get-Clipboard"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode != 0:
                return ToolResult(success=False, output=None, error="Failed to read clipboard")
            return ToolResult(
                success=True,
                output={"content": result.stdout.rstrip('\r\n'), "backend": "powershell"}
            )

        elif platform_type == "pyperclip":
            import pyperclip
            content = pyperclip.paste()
            return ToolResult(
                success=True,
                output={"content": content, "backend": "pyperclip"}
            )

        return ToolResult(success=False, output=None, error="Unsupported platform")

    async def _write_clipboard(self, platform_type: str, backend: str, content: str) -> ToolResult:
        """Write to clipboard based on platform"""
        if platform_type == "macos":
            result = subprocess.run(
                ["pbcopy"],
                input=content,
                text=True,
                capture_output=True,
                timeout=5
            )
            if result.returncode != 0:
                return ToolResult(success=False, output=None, error="Failed to write to clipboard")
            return ToolResult(
                success=True,
                output={"action": "write", "bytes_written": len(content.encode('utf-8')), "backend": "pbcopy"}
            )

        elif platform_type == "linux":
            if backend == "xclip":
                cmd = ["xclip", "-selection", "clipboard"]
            elif backend == "xsel":
                cmd = ["xsel", "--clipboard", "--input"]
            elif backend == "wl-clipboard":
                cmd = ["wl-copy"]
            else:
                return ToolResult(success=False, output=None, error="Unknown Linux clipboard backend")

            result = subprocess.run(cmd, input=content, text=True, capture_output=True, timeout=5)
            if result.returncode != 0:
                return ToolResult(success=False, output=None, error=f"Failed to write clipboard: {result.stderr}")
            return ToolResult(
                success=True,
                output={"action": "write", "bytes_written": len(content.encode('utf-8')), "backend": backend}
            )

        elif platform_type == "windows":
            # Use clip.exe (always available on Windows)
            result = subprocess.run(
                ["clip"],
                input=content,
                text=True,
                capture_output=True,
                timeout=5
            )
            if result.returncode != 0:
                return ToolResult(success=False, output=None, error="Failed to write to clipboard")
            return ToolResult(
                success=True,
                output={"action": "write", "bytes_written": len(content.encode('utf-8')), "backend": "clip.exe"}
            )

        elif platform_type == "pyperclip":
            import pyperclip
            pyperclip.copy(content)
            return ToolResult(
                success=True,
                output={"action": "write", "bytes_written": len(content.encode('utf-8')), "backend": "pyperclip"}
            )

        return ToolResult(success=False, output=None, error="Unsupported platform")


class NotificationTool(Tool):
    """Send desktop notifications (cross-platform)"""

    def __init__(self):
        super().__init__()
        self.name = "notification"
        self.description = "Send a desktop notification (macOS Notification Center, Linux notify-send, Windows toast)"
        self.category = ToolCategory.SYSTEM
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="title",
                type="string",
                description="Notification title",
                required=True
            ),
            ToolParameter(
                name="message",
                type="string",
                description="Notification message",
                required=True
            ),
            ToolParameter(
                name="subtitle",
                type="string",
                description="Optional subtitle (macOS only)",
                required=False
            ),
            ToolParameter(
                name="sound",
                type="string",
                description="Notification sound name (platform-specific)",
                required=False,
                default="default"
            ),
            ToolParameter(
                name="urgency",
                type="string",
                description="Notification urgency level (Linux only)",
                required=False,
                default="normal",
                enum=["low", "normal", "critical"]
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="notification",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.MANAGE_PROCESS,
                    description="Notification capability"
                )
            ]
        )

    async def execute(
        self,
        title: str,
        message: str,
        subtitle: Optional[str] = None,
        sound: str = "default",
        urgency: str = "normal"
    ) -> ToolResult:
        """Send notification with cross-platform support"""
        try:
            platform_type, backend = detect_notification_backend()

            if platform_type == "macos":
                return await self._send_macos_notification(title, message, subtitle, sound)
            elif platform_type == "linux":
                return await self._send_linux_notification(title, message, urgency, backend)
            elif platform_type == "windows":
                return await self._send_windows_notification(title, message)
            elif platform_type == "log":
                # Fallback: Log the notification
                logger.info(f"Notification: {title} - {message}")
                return ToolResult(
                    success=True,
                    output={
                        "title": title,
                        "message": message,
                        "backend": "logger",
                        "sent_at": datetime.now().isoformat(),
                        "note": "Notification logged (no desktop notification system available)"
                    }
                )

            return ToolResult(success=False, output=None, error="Unsupported platform")

        except PermissionError:
            return ToolResult(
                success=False,
                output=None,
                error="Permission denied. On macOS, grant notifications permission in System Settings > Notifications"
            )
        except Exception as e:
            logger.error(f"Error sending notification: {e}")
            return ToolResult(
                success=False,
                output=None,
                error=str(e)
            )

    async def _send_macos_notification(
        self, title: str, message: str, subtitle: Optional[str], sound: str
    ) -> ToolResult:
        """Send notification using macOS osascript"""
        # Escape quotes in strings
        title_esc = title.replace('"', '\\"')
        message_esc = message.replace('"', '\\"')

        script = f'display notification "{message_esc}" with title "{title_esc}"'

        if subtitle:
            subtitle_esc = subtitle.replace('"', '\\"')
            script = f'display notification "{message_esc}" with title "{title_esc}" subtitle "{subtitle_esc}"'

        if sound and sound != "default":
            script += f' sound name "{sound}"'

        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=5
        )

        if result.returncode != 0:
            return ToolResult(
                success=False,
                output=None,
                error=f"Failed to send notification: {result.stderr}"
            )

        return ToolResult(
            success=True,
            output={
                "title": title,
                "message": message,
                "subtitle": subtitle,
                "backend": "osascript",
                "sent_at": datetime.now().isoformat()
            }
        )

    async def _send_linux_notification(
        self, title: str, message: str, urgency: str, backend: str
    ) -> ToolResult:
        """Send notification using Linux notify-send"""
        if backend == "notify-send":
            cmd = ["notify-send", "-u", urgency, title, message]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)

            if result.returncode != 0:
                return ToolResult(
                    success=False,
                    output=None,
                    error=f"Failed to send notification: {result.stderr}"
                )

            return ToolResult(
                success=True,
                output={
                    "title": title,
                    "message": message,
                    "urgency": urgency,
                    "backend": "notify-send",
                    "sent_at": datetime.now().isoformat()
                }
            )
        else:
            # Fallback to logger
            logger.info(f"Notification: {title} - {message}")
            return ToolResult(
                success=True,
                output={
                    "title": title,
                    "message": message,
                    "backend": "logger",
                    "sent_at": datetime.now().isoformat(),
                    "note": "notify-send not installed. Install: sudo apt-get install libnotify-bin"
                }
            )

    async def _send_windows_notification(self, title: str, message: str) -> ToolResult:
        """Send notification using Windows PowerShell"""
        # Use msg command for simple notification, or try PowerShell toast notification
        # For now, use simple approach with msg
        script = f'''
$null = Add-Type -AssemblyName System.Windows.Forms
[System.Windows.Forms.MessageBox]::Show('{message}', '{title}', 'OK', 'Information')
'''

        # Simpler approach: Use msg command
        # Note: This requires interactive session
        result = subprocess.run(
            ["msg", "*", f"{title}: {message}"],
            capture_output=True,
            text=True,
            timeout=5
        )

        # If msg fails, log notification
        if result.returncode != 0:
            logger.info(f"Notification: {title} - {message}")
            return ToolResult(
                success=True,
                output={
                    "title": title,
                    "message": message,
                    "backend": "logger",
                    "sent_at": datetime.now().isoformat(),
                    "note": "Windows notification sent via logger (msg command requires interactive session)"
                }
            )

        return ToolResult(
            success=True,
            output={
                "title": title,
                "message": message,
                "backend": "msg.exe",
                "sent_at": datetime.now().isoformat()
            }
        )


class ListUsbDevicesTool(Tool):
    """Enumerate attached USB devices"""

    def __init__(self):
        super().__init__()
        self.name = "list_usb_devices"
        # Phrased for retrieval as much as for the reader: this is ranked by BM25
        # over name+description, and "is my phone plugged in" has to hit it without
        # the user ever saying "USB".
        self.description = (
            "Is a device plugged in or connected to this computer? Detect attached "
            "USB hardware and peripherals — phone, tablet, drive, dongle, keyboard, "
            "Rabbit R1, Android device. Lists every connected device with its vendor, "
            "product name, serial number and USB vendor/product IDs. On macOS 26 "
            "`system_profiler SPUSBDataType` exits 0 printing nothing even while "
            "devices are attached, so use this instead of a shell command."
        )
        self.category = ToolCategory.SYSTEM
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="name_filter",
                type="string",
                description="Case-insensitive substring to match vendor or product name",
                required=False,
                default=""
            )
        ]

        self.capability_profile = ToolCapabilityProfile(
            tool_name="list_usb_devices",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.MANAGE_PROCESS,
                    description="Inspect attached hardware"
                )
            ]
        )

    async def execute(self, name_filter: str = "") -> ToolResult:
        import platform
        import re
        import subprocess

        try:
            if platform.system() != "Darwin":
                proc = subprocess.run(["lsusb"], capture_output=True, text=True, timeout=20)
                if proc.returncode != 0:
                    return ToolResult(success=False, output=None,
                                      error=f"lsusb failed: {proc.stderr.strip()}")
                lines = [l for l in proc.stdout.splitlines() if l.strip()]
                if name_filter:
                    lines = [l for l in lines if name_filter.lower() in l.lower()]
                return ToolResult(success=True,
                                  output={"count": len(lines), "devices": lines})

            # ioreg on the IOUSB plane. NOT `-p USB` (no such plane; it silently
            # returns only the root node) and NOT system_profiler, which is broken.
            proc = subprocess.run(
                ["ioreg", "-p", "IOUSB", "-w0", "-l"],
                capture_output=True, text=True, timeout=30)
            if proc.returncode != 0:
                return ToolResult(success=False, output=None,
                                  error=f"ioreg failed: {proc.stderr.strip()}")

            devices, cur = [], None
            for line in proc.stdout.splitlines():
                if "+-o " in line:
                    if cur and cur.get("product"):
                        devices.append(cur)
                    cur = {}
                    continue
                if cur is None:
                    continue
                for key, field in (("USB Product Name", "product"),
                                   ("USB Vendor Name", "vendor"),
                                   ("USB Serial Number", "serial")):
                    m = re.search(rf'"{key}" = "(.*)"', line)
                    if m:
                        cur[field] = m.group(1)
                for key, field in (("idVendor", "vendor_id"), ("idProduct", "product_id")):
                    m = re.search(rf'"{key}" = (\d+)', line)
                    if m:
                        cur[field] = f"0x{int(m.group(1)):04x}"
            if cur and cur.get("product"):
                devices.append(cur)

            if name_filter:
                f = name_filter.lower()
                devices = [d for d in devices
                           if f in (d.get("product", "") + d.get("vendor", "")).lower()]

            return ToolResult(success=True, output={
                "count": len(devices),
                "devices": devices,
                "note": ("No USB devices matched." if not devices else None)
            })
        except Exception as e:
            return ToolResult(success=False, output=None, error=f"{type(e).__name__}: {e}")


class InstalledSoftwareTool(Tool):
    """Reliable inventory of installed software on the Mac or the Rabbit r1."""

    R1 = "/Users/stefan/bin/r1"

    def __init__(self):
        super().__init__()
        self.name = "installed_software"
        # BM25 retrieval bait: this must fire on every phrasing of "what do I
        # have", not only the literal word "installed".
        self.description = (
            "What software, tools, packages, programs, apps, binaries or CLI "
            "commands are installed on this Mac or on the Rabbit r1 / Android "
            "Termux device? List everything installed, or check whether one "
            "specific tool is present. Reliable and complete: it does not just "
            "read the package manager, it also lists the actual binaries on PATH, "
            "so tools installed outside the package manager (Go tools like nuclei, "
            "ffuf, gobuster; pipx apps; proot-guest tools) are NOT missed — the "
            "mistake a bare `pkg list-installed` makes. Use this instead of "
            "scanning a package list to decide if something is installed."
        )
        self.category = ToolCategory.SYSTEM
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="target",
                type="string",
                description="Which machine: 'r1' (the Rabbit device) or 'mac'",
                required=False, default="r1", enum=["r1", "mac"],
            ),
            ToolParameter(
                name="filter",
                type="string",
                description=("Check for one tool by name (substring). Empty lists "
                             "everything. This is the reliable 'is X installed?' path."),
                required=False, default="",
            ),
        ]
        self.capability_profile = ToolCapabilityProfile(
            tool_name="installed_software",
            capabilities=[
                CapabilityMetadata(capability=Capability.LIST_DATA,
                                   description="Enumerate installed software"),
                CapabilityMetadata(capability=Capability.MANAGE_PROCESS,
                                   description="Inspect the system"),
            ],
        )

    # One round-trip. `ls $PREFIX/bin` + `~/.local/bin` is the ground truth for
    # "what can actually run"; subtracting the dpkg-owned binaries leaves exactly
    # the manually-installed tools, which is the set a package list omits.
    _R1_SCRIPT = r'''
P="$PREFIX"; H="$HOME"
echo "@@APT@@"
pkg list-installed 2>/dev/null | sed 's|/.*||'
echo "@@BIN@@"
{ ls -1 "$P/bin" 2>/dev/null; ls -1 "$H/.local/bin" 2>/dev/null; } | sort -u
echo "@@APTBIN@@"
cat "$P"/var/lib/dpkg/info/*.list 2>/dev/null | grep -E '/bin/[^/]+$' | sed 's|.*/||' | sort -u
echo "@@PIPX@@"
pipx list --short 2>/dev/null
echo "@@PROOT@@"
ls -1 "$P/var/lib/proot-distro/installed-rootfs" 2>/dev/null
'''

    _MAC_SCRIPT = r'''
echo "@@BREW@@"
brew list --formula 2>/dev/null
echo "@@CASK@@"
brew list --cask 2>/dev/null
echo "@@PIPX@@"
pipx list --short 2>/dev/null
echo "@@BIN@@"
ls -1 /opt/homebrew/bin /usr/local/bin 2>/dev/null | grep -v '^/' | sort -u
'''

    async def execute(self, target: str = "r1", filter: str = "") -> ToolResult:
        import subprocess
        try:
            if target == "mac":
                proc = subprocess.run(["/bin/bash", "-lc", self._MAC_SCRIPT],
                                      capture_output=True, text=True, timeout=60)
            else:
                proc = subprocess.run([self.R1, "tx", self._R1_SCRIPT],
                                      capture_output=True, text=True, timeout=60)
            if proc.returncode != 0 and not proc.stdout.strip():
                return ToolResult(success=False, output=None,
                                  error=f"inventory failed: {proc.stderr.strip()[:300]}")

            # split the marker-delimited sections
            sec, cur = {}, None
            for line in proc.stdout.splitlines():
                if line.startswith("@@") and line.endswith("@@"):
                    cur = line.strip("@"); sec[cur] = []
                elif cur is not None and line.strip():
                    sec[cur].append(line.strip())

            if target == "mac":
                out = {
                    "target": "mac",
                    "brew_formulae": sorted(set(sec.get("BREW", []))),
                    "brew_casks": sorted(set(sec.get("CASK", []))),
                    "pipx": [p.split()[0] for p in sec.get("PIPX", []) if p],
                    "commands_count": len(set(sec.get("BIN", []))),
                }
            else:
                allbin = set(sec.get("BIN", []))
                aptbin = set(sec.get("APTBIN", []))
                # Stray docs land in bin dirs; they are not commands.
                noise = {"README", "LICENSE", "CHANGELOG"}
                unmanaged = sorted(x for x in (allbin - aptbin)
                                   if not x.endswith((".md", ".txt", ".rst"))
                                   and x.split(".")[0].upper() not in noise)
                out = {
                    "target": "r1",
                    "apt_packages": {"count": len(set(sec.get("APT", []))),
                                     "names": sorted(set(sec.get("APT", [])))},
                    # The valuable, reliable signal: runnable commands NOT owned by
                    # apt — nuclei/ffuf/gobuster, pipx shims, proot wrappers, etc.
                    "unmanaged_commands": unmanaged,
                    "pipx": [p.split()[0] for p in sec.get("PIPX", []) if p],
                    "proot_distros": sec.get("PROOT", []),
                    "commands_total": len(allbin),
                    "note": ("proot guests (e.g. debian) hold their own tools — "
                             "mitmproxy lives there; query inside them separately "
                             "if needed."),
                }

            if filter:
                f = filter.lower()
                hits = {}
                for key, val in out.items():
                    if isinstance(val, list):
                        m = [x for x in val if f in str(x).lower()]
                        if m: hits[key] = m
                    elif isinstance(val, dict) and "names" in val:
                        m = [x for x in val["names"] if f in x.lower()]
                        if m: hits[key] = m
                return ToolResult(success=True, output={
                    "target": out["target"], "filter": filter,
                    "installed": bool(hits), "found_in": hits or None,
                })
            return ToolResult(success=True, output=out)
        except subprocess.TimeoutExpired:
            return ToolResult(success=False, output=None,
                              error="inventory timed out")
        except Exception as e:
            return ToolResult(success=False, output=None,
                              error=f"{type(e).__name__}: {e}")


class SystemInfoTool(Tool):
    """Get cross-platform system information"""

    def __init__(self):
        super().__init__()
        self.name = "system_info"
        self.description = "Get system information (CPU, memory, disk, network, OS) - works on macOS, Linux, Windows"
        self.category = ToolCategory.SYSTEM
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="info_type",
                type="string",
                description="Type of system info to retrieve",
                required=False,
                default="all",
                enum=["all", "cpu", "memory", "disk", "network", "os"]
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="system_info",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.MANAGE_PROCESS,
                    description="SystemInfo capability"
                )
            ]
        )
    
    async def execute(self, info_type: str = "all") -> ToolResult:
        """Get system info"""
        try:
            import psutil
            
            info = {}
            
            if info_type in ["all", "cpu"]:
                info["cpu"] = {
                    "cores": psutil.cpu_count(logical=False),
                    "logical_cores": psutil.cpu_count(logical=True),
                    "usage_percent": psutil.cpu_percent(interval=1),
                    "frequency": psutil.cpu_freq().current if psutil.cpu_freq() else None
                }
            
            if info_type in ["all", "memory"]:
                mem = psutil.virtual_memory()
                info["memory"] = {
                    "total_gb": round(mem.total / (1024**3), 2),
                    "available_gb": round(mem.available / (1024**3), 2),
                    "used_gb": round(mem.used / (1024**3), 2),
                    "percent_used": mem.percent
                }
            
            if info_type in ["all", "disk"]:
                disk = psutil.disk_usage('/')
                info["disk"] = {
                    "total_gb": round(disk.total / (1024**3), 2),
                    "used_gb": round(disk.used / (1024**3), 2),
                    "free_gb": round(disk.free / (1024**3), 2),
                    "percent_used": disk.percent
                }
            
            if info_type in ["all", "network"]:
                net_io = psutil.net_io_counters()
                info["network"] = {
                    "bytes_sent_mb": round(net_io.bytes_sent / (1024**2), 2),
                    "bytes_recv_mb": round(net_io.bytes_recv / (1024**2), 2),
                    "packets_sent": net_io.packets_sent,
                    "packets_recv": net_io.packets_recv
                }
            
            if info_type in ["all", "os"]:
                info["os"] = {
                    "system": platform.system(),
                    "release": platform.release(),
                    "version": platform.version(),
                    "machine": platform.machine(),
                    "processor": platform.processor()
                }
            
            return ToolResult(
                success=True,
                output=info
            )
            
        except Exception as e:
            logger.error(f"Error getting system info: {e}")
            return ToolResult(
                success=False,
                output=None,
                error=str(e)
            )


class FileWatcherTool(Tool):
    """Watch files for changes (cross-platform)"""

    def __init__(self):
        super().__init__()
        self.name = "file_watcher"
        self.description = "Check if files have been modified since last check (works on all platforms)"
        self.category = ToolCategory.FILESYSTEM
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="file_paths",
                type="array",
                description="List of file paths to watch",
                required=True
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="file_watcher",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.MANAGE_PROCESS,
                    description="FileWatcher capability"
                )
            ]
        )
        self.last_modified = {}
    
    async def execute(self, file_paths: list) -> ToolResult:
        """Check for file modifications"""
        try:
            changes = []
            
            for file_path in file_paths:
                path = Path(file_path).resolve()
                
                if not path.exists():
                    changes.append({
                        "file": str(path),
                        "status": "deleted" if str(path) in self.last_modified else "not_found"
                    })
                    continue
                
                current_mtime = path.stat().st_mtime
                
                if str(path) in self.last_modified:
                    if current_mtime > self.last_modified[str(path)]:
                        changes.append({
                            "file": str(path),
                            "status": "modified",
                            "modified_time": datetime.fromtimestamp(current_mtime).isoformat()
                        })
                else:
                    changes.append({
                        "file": str(path),
                        "status": "new",
                        "modified_time": datetime.fromtimestamp(current_mtime).isoformat()
                    })
                
                self.last_modified[str(path)] = current_mtime
            
            return ToolResult(
                success=True,
                output={
                    "files_watched": len(file_paths),
                    "changes": changes,
                    "changes_detected": len(changes) > 0
                }
            )
            
        except Exception as e:
            logger.error(f"Error watching files: {e}")
            return ToolResult(
                success=False,
                output=None,
                error=str(e)
            )


class ListAvailableToolsTool(Tool):
    """
    List available tools and their capabilities.

    Allows the AI to introspect what tools it has access to and discover capabilities.
    Critical for autonomous operation - prevents trying to use unavailable tools.
    """

    def __init__(self):
        super().__init__()
        self.name = "list_available_tools"
        self.description = "List all tools currently available and their capabilities. Use this to discover what operations you can perform."
        self.category = ToolCategory.SYSTEM
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter("category", "string", "Filter by category (filesystem, execution, security, etc.)", required=False),
            ToolParameter("search", "string", "Search for tools matching this keyword", required=False)
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="list_available_tools",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.MANAGE_PROCESS,
                    description="ListAvailables capability"
                )
            ]
        )

    async def execute(self, category: Optional[str] = None, search: Optional[str] = None) -> ToolResult:
        """List available tools, optionally filtered by category or keyword."""
        try:
            from .tool_registry import tool_registry

            # Get all tools from registry
            all_tools = tool_registry.list_tools()

            # Filter by category if specified
            if category:
                all_tools = [t for t in all_tools if hasattr(t, 'category') and t.category.value == category]

            # Filter by search keyword if specified
            if search:
                search_lower = search.lower()
                all_tools = [t for t in all_tools if
                           search_lower in t.name.lower() or
                           (hasattr(t, 'description') and search_lower in t.description.lower())]

            # Build tool list
            tool_list = []
            categories_found = set()

            for tool in all_tools:
                tool_info = {
                    "name": tool.name,
                    "description": getattr(tool, 'description', 'No description'),
                    "category": tool.category.value if hasattr(tool, 'category') else 'unknown',
                    "safety": tool.safety_level.value if hasattr(tool, 'safety_level') else 'unknown'
                }

                # Add parameter info
                if hasattr(tool, 'parameters') and tool.parameters:
                    tool_info["parameters"] = [
                        {
                            "name": p.name if hasattr(p, 'name') else str(p),
                            "type": p.type if hasattr(p, 'type') else 'unknown',
                            "required": p.required if hasattr(p, 'required') else True
                        }
                        for p in tool.parameters
                    ]

                tool_list.append(tool_info)
                if hasattr(tool, 'category'):
                    categories_found.add(tool.category.value)

            return ToolResult(
                success=True,
                output={
                    "total_tools": len(tool_list),
                    "categories": sorted(list(categories_found)),
                    "tools": tool_list
                },
                tool_name=self.name,
                parameters={"category": category, "search": search}
            )

        except Exception as e:
            logger.error(f"Error listing tools: {e}")
            return ToolResult(
                success=False,
                output=None,
                error=str(e),
                tool_name=self.name,
                parameters={"category": category, "search": search}
            )
