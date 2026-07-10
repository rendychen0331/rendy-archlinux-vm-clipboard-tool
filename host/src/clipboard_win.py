"""Windows clipboard access: event-driven listener via a message-only
window + AddClipboardFormatListener, plus text get/set with busy-retry.
"""
import ctypes
import logging
import threading
import time

import win32api
import win32clipboard
import win32con
import win32gui

WM_CLIPBOARDUPDATE = 0x031D


def _open_clipboard(retries: int = 10, delay: float = 0.05) -> bool:
    # Another process may hold the clipboard open; retry briefly.
    for _ in range(retries):
        try:
            win32clipboard.OpenClipboard(0)
            return True
        except win32api.error:
            time.sleep(delay)
    return False


def get_text():
    """Return clipboard text, or None if unavailable / not text."""
    if not _open_clipboard():
        logging.warning("clipboard busy, get_text gave up")
        return None
    try:
        if not win32clipboard.IsClipboardFormatAvailable(
                win32con.CF_UNICODETEXT):
            return None
        return win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
    finally:
        win32clipboard.CloseClipboard()


def set_text(text: str) -> None:
    if not _open_clipboard():
        raise RuntimeError("clipboard busy, set_text failed")
    try:
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, text)
    finally:
        win32clipboard.CloseClipboard()


class WinClipboardListener:
    """Fires on_change() on every WM_CLIPBOARDUPDATE (event push, no poll)."""

    def __init__(self, on_change):
        self._on_change = on_change
        self._ready = threading.Event()

    def start(self):
        threading.Thread(
            target=self._pump, name="clip-pump", daemon=True).start()
        if not self._ready.wait(5):
            raise RuntimeError("clipboard listener window failed to start")

    def _pump(self):
        wc = win32gui.WNDCLASS()
        wc.lpfnWndProc = self._wndproc
        wc.lpszClassName = "ClipSyncHostWnd"
        wc.hInstance = win32api.GetModuleHandle(None)
        atom = win32gui.RegisterClass(wc)
        hwnd = win32gui.CreateWindow(
            atom, "clipsync", 0, 0, 0, 0, 0,
            win32con.HWND_MESSAGE, 0, wc.hInstance, None)
        if not ctypes.windll.user32.AddClipboardFormatListener(hwnd):
            logging.error("AddClipboardFormatListener failed: %s",
                          ctypes.get_last_error())
        self._ready.set()
        win32gui.PumpMessages()

    def _wndproc(self, hwnd, msg, wparam, lparam):
        if msg == WM_CLIPBOARDUPDATE:
            try:
                self._on_change()
            except Exception:
                logging.exception("clipboard change handler failed")
            return 0
        return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)
