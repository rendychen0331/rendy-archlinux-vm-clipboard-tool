"""Smoke-test client: pretends to be the guest.
1. Connects + handshakes with the host daemon.
2. Sends a clip message -> host must write it to the Windows clipboard.
3. Waits for a clip message from the host (triggered by a local
   clipboard change) and prints it.
Run while host/main.py is running.
"""
import socket
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "host"))
from src import protocol  # noqa: E402

TOKEN = sys.argv[1] if len(sys.argv) > 1 else "change-me"
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 27333

sock = socket.create_connection(("127.0.0.1", PORT), timeout=5)
sock.sendall(protocol.encode(protocol.make_hello(TOKEN)))
print("[OK] connected + hello sent")

payload = "clipsync smoke test 中文 " + time.strftime("%H:%M:%S")
sock.sendall(protocol.encode(protocol.make_clip(payload)))
print(f"[OK] sent clip: {payload!r}")


def set_host_clipboard_later():
    time.sleep(1.0)
    import win32clipboard, win32con  # noqa: E401
    win32clipboard.OpenClipboard(0)
    win32clipboard.EmptyClipboard()
    win32clipboard.SetClipboardData(
        win32con.CF_UNICODETEXT, "host copy 事件測試")
    win32clipboard.CloseClipboard()
    print("[OK] host clipboard set externally, expecting push...")


threading.Thread(target=set_host_clipboard_later, daemon=True).start()

sock.settimeout(5)
try:
    for msg in protocol.read_messages(sock, 4 * 1024 * 1024):
        if msg.get("type") == "clip":
            print(f"[OK] received from host: {protocol.clip_text(msg)!r}")
            break
except socket.timeout:
    print("[FAIL] no push from host within 5s")
    sys.exit(1)

# verify step 2 landed in the real clipboard
import win32clipboard, win32con  # noqa: E401,E402
win32clipboard.OpenClipboard(0)
got = win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
win32clipboard.CloseClipboard()
if got == "host copy 事件測試":
    print("[OK] clipboard now holds the externally-set text (expected)")
print("[DONE] smoke test passed")
