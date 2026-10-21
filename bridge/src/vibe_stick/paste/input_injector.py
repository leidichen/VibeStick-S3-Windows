from __future__ import annotations

import platform
import subprocess
import time
from dataclasses import dataclass

from vibe_stick.desktop.process import hidden_subprocess_kwargs


@dataclass
class PasteResult:
    success: bool
    message: str


def make_paste_injector() -> "PasteInjector":
    system = platform.system()
    if system == "Darwin":
        return MacPasteInjector()
    if system == "Windows":
        return WindowsPasteInjector()
    return UnsupportedPasteInjector(system)


class PasteInjector:
    def paste(self, text: str, press_enter: bool = False) -> PasteResult:
        raise NotImplementedError

    def press_enter(self) -> PasteResult:
        raise NotImplementedError


class MacPasteInjector(PasteInjector):
    def paste(self, text: str, press_enter: bool = False) -> PasteResult:
        text = text.strip()
        if not text:
            return PasteResult(False, "No text to paste")
        if platform.system() != "Darwin":
            return PasteResult(False, "Automatic paste is only available on macOS")

        previous_text = self._read_clipboard()
        set_result = self._set_clipboard(text)
        if not set_result.success:
            return set_result

        script = [
            'tell application "System Events" to keystroke "v" using command down',
        ]
        if press_enter:
            script.extend([
                "delay 0.12",
                'tell application "System Events" to key code 36',
            ])

        args = ["osascript"]
        for line in script:
            args.extend(["-e", line])
        result = subprocess.run(args, check=False, capture_output=True, text=True, timeout=5)
        time.sleep(0.2)
        if previous_text is not None:
            self._set_clipboard(previous_text)

        if result.returncode != 0:
            message = (result.stderr or result.stdout or "macOS paste failed").strip()
            return PasteResult(False, message)
        return PasteResult(True, "Pasted into the focused app")

    def press_enter(self) -> PasteResult:
        if platform.system() != "Darwin":
            return PasteResult(False, "Enter injection is only available on macOS")
        try:
            result = subprocess.run(
                ["osascript", "-e", 'tell application "System Events" to key code 36'],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return PasteResult(False, f"macOS enter failed: {exc}")
        if result.returncode != 0:
            message = (result.stderr or result.stdout or "macOS enter failed").strip()
            return PasteResult(False, message)
        return PasteResult(True, "Pressed Enter in the focused app")

    def _read_clipboard(self) -> str | None:
        try:
            result = subprocess.run(
                ["pbpaste"],
                check=False,
                capture_output=True,
                text=True,
                timeout=2,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if result.returncode != 0:
            return None
        return result.stdout

    def _set_clipboard(self, text: str) -> PasteResult:
        try:
            result = subprocess.run(
                ["pbcopy"],
                input=text,
                check=False,
                capture_output=True,
                text=True,
                timeout=2,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return PasteResult(False, f"Clipboard write failed: {exc}")
        if result.returncode != 0:
            message = (result.stderr or "Clipboard write failed").strip()
            return PasteResult(False, message)
        return PasteResult(True, "Clipboard updated")


class WindowsPasteInjector(PasteInjector):
    def paste(self, text: str, press_enter: bool = False) -> PasteResult:
        text = text.strip()
        if not text:
            return PasteResult(False, "No text to paste")
        if platform.system() != "Windows":
            return PasteResult(False, "Windows paste injector can only run on Windows")

        set_result = self._set_clipboard(text)
        if not set_result.success:
            return set_result

        try:
            self._send_ctrl_v(press_enter=press_enter)
        except OSError as exc:
            return PasteResult(False, f"Windows paste failed: {exc}")
        time.sleep(0.1)
        return PasteResult(True, "Pasted into the focused app")

    def _set_clipboard(self, text: str) -> PasteResult:
        # Fast path: talk to the Windows clipboard directly (a few ms). Spawning PowerShell cost ~0.3 s.
        if _set_clipboard_native(text):
            return PasteResult(True, "Clipboard updated")
        return self._set_clipboard_powershell(text)

    def _set_clipboard_powershell(self, text: str) -> PasteResult:
        command = [
            "powershell",
            "-NoProfile",
            "-Command",
            "Set-Clipboard -Value ([Console]::In.ReadToEnd())",
        ]
        try:
            result = subprocess.run(
                command,
                input=text,
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
                **hidden_subprocess_kwargs(),
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return PasteResult(False, f"Clipboard write failed: {exc}")
        if result.returncode != 0:
            message = (result.stderr or result.stdout or "Clipboard write failed").strip()
            return PasteResult(False, message)
        return PasteResult(True, "Clipboard updated")

    def _send_ctrl_v(self, *, press_enter: bool) -> None:
        import ctypes

        user32 = ctypes.windll.user32
        keybd_event = user32.keybd_event
        keybd_event.argtypes = [
            ctypes.c_ubyte,
            ctypes.c_ubyte,
            ctypes.c_uint,
            ctypes.c_void_p,
        ]
        vk_control = 0x11
        vk_v = 0x56
        vk_enter = 0x0D
        key_up = 0x0002

        keybd_event(vk_control, 0, 0, None)
        keybd_event(vk_v, 0, 0, None)
        keybd_event(vk_v, 0, key_up, None)
        keybd_event(vk_control, 0, key_up, None)
        if press_enter:
            time.sleep(0.12)
            keybd_event(vk_enter, 0, 0, None)
            keybd_event(vk_enter, 0, key_up, None)

    def press_enter(self) -> PasteResult:
        if platform.system() != "Windows":
            return PasteResult(False, "Enter injection is only available on Windows")
        try:
            self._send_enter()
        except OSError as exc:
            return PasteResult(False, f"Windows enter failed: {exc}")
        time.sleep(0.1)
        return PasteResult(True, "Pressed Enter in the focused app")

    def _send_enter(self) -> None:
        import ctypes

        user32 = ctypes.windll.user32
        keybd_event = user32.keybd_event
        keybd_event.argtypes = [
            ctypes.c_ubyte,
            ctypes.c_ubyte,
            ctypes.c_uint,
            ctypes.c_void_p,
        ]
        vk_enter = 0x0D
        key_up = 0x0002

        keybd_event(vk_enter, 0, 0, None)
        keybd_event(vk_enter, 0, key_up, None)


class UnsupportedPasteInjector(PasteInjector):
    def __init__(self, system: str) -> None:
        self.system = system or "this platform"

    def paste(self, text: str, press_enter: bool = False) -> PasteResult:
        del press_enter
        if not text.strip():
            return PasteResult(False, "No text to paste")
        return PasteResult(False, f"Automatic paste is not available on {self.system}")

    def press_enter(self) -> PasteResult:
        return PasteResult(False, f"Enter injection is not available on {self.system}")


def _set_clipboard_native(text: str) -> bool:
    """Put Unicode text on the Windows clipboard via the Win32 API. Returns False on any failure."""
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        user32.OpenClipboard.argtypes = [wintypes.HWND]
        user32.OpenClipboard.restype = wintypes.BOOL
        user32.EmptyClipboard.restype = wintypes.BOOL
        user32.CloseClipboard.restype = wintypes.BOOL
        user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
        user32.SetClipboardData.restype = wintypes.HANDLE
        kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
        kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
        kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalLock.restype = wintypes.LPVOID
        kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalUnlock.restype = wintypes.BOOL
        kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalFree.restype = wintypes.HGLOBAL

        gmem_moveable = 0x0002
        cf_unicodetext = 13
        data = (text + "\0").encode("utf-16-le")

        # Another app may hold the clipboard for a moment; retry briefly.
        for _ in range(15):
            if user32.OpenClipboard(None):
                break
            time.sleep(0.02)
        else:
            return False
        try:
            user32.EmptyClipboard()
            handle = kernel32.GlobalAlloc(gmem_moveable, len(data))
            if not handle:
                return False
            pointer = kernel32.GlobalLock(handle)
            if not pointer:
                kernel32.GlobalFree(handle)
                return False
            ctypes.memmove(pointer, data, len(data))
            kernel32.GlobalUnlock(handle)
            if not user32.SetClipboardData(cf_unicodetext, handle):
                kernel32.GlobalFree(handle)
                return False
            return True  # the system owns the memory now
        finally:
            user32.CloseClipboard()
    except Exception:  # noqa: BLE001 - any failure falls back to PowerShell
        return False
