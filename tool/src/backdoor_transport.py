"""Transport for v2: spawn the Rust backdoor helper and bridge it over pipes.

Line protocol (hex-encoded UTF-8, matching rustsrc/main.rs):
  helper stdout  "H <hex>"  -> host clipboard changed
  helper stdin   "G <hex>"  -> write guest clipboard to the host

Replaces v1's SyncClient; the app-facing shape (start / send / on_host_text)
is deliberately similar so app wiring stays thin.
"""
import logging
import subprocess
import threading
from pathlib import Path


class BackdoorTransport:
    def __init__(self, helper_path: Path, poll_ms: int, on_host_text,
                 max_text_bytes: int):
        self._helper = helper_path
        self._poll_ms = poll_ms
        self._on_host_text = on_host_text
        self._max = max_text_bytes
        self._proc = None
        self._lock = threading.Lock()

    def start(self):
        if not self._helper.exists():
            raise SystemExit(
                f"helper binary not found: {self._helper}. Run tool/build.sh "
                "on the VM first.")
        self._proc = subprocess.Popen(
            [str(self._helper), str(self._poll_ms)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, bufsize=0)
        threading.Thread(target=self._read_stdout, name="helper-out",
                         daemon=True).start()
        threading.Thread(target=self._read_stderr, name="helper-err",
                         daemon=True).start()
        logging.info("backdoor helper started (poll %dms)", self._poll_ms)

    def _read_stdout(self):
        for raw in self._proc.stdout:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("H "):
                continue
            try:
                text = bytes.fromhex(line[2:]).decode("utf-8", "replace")
            except ValueError:
                logging.warning("bad hex from helper, dropped")
                continue
            try:
                self._on_host_text(text)
            except Exception:
                logging.exception("host-text handler failed")
        logging.warning("helper stdout closed; exiting")
        self._crash()

    def _read_stderr(self):
        for raw in self._proc.stderr:
            logging.info("helper: %s", raw.decode("utf-8", "replace").rstrip())

    def send(self, text: str) -> bool:
        data = text.encode("utf-8")
        if len(data) > self._max:
            logging.warning("guest text exceeds max_text_bytes, not sent")
            return False
        line = ("G " + data.hex() + "\n").encode("ascii")
        with self._lock:
            if self._proc is None or self._proc.poll() is not None:
                logging.warning("helper not running, guest text dropped")
                return False
            try:
                self._proc.stdin.write(line)
                self._proc.stdin.flush()
                return True
            except OSError as e:
                logging.warning("write to helper failed: %s", e)
                return False

    def _crash(self):
        # Helper death is fatal: without it there is no host channel. systemd
        # (Restart=on-failure) brings the whole daemon back.
        import os
        os._exit(1)
