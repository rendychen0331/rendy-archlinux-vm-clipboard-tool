"""v2 app wiring: X11 CLIPBOARD selection <-> host clipboard via the backdoor
helper. No explicit loop guard is needed -- the two echoes are killed at their
natural points:
  - guest self-set: clipboard_x11 ignores its own selection-owner notify.
  - host write-back: the Rust helper remembers what it wrote and does not
    re-emit it on the next poll.
"""
import logging
from pathlib import Path

from src.backdoor_transport import BackdoorTransport
from src.clipboard_x11 import X11Clipboard
from src.logger_setup import task_scope


class ToolApp:
    def __init__(self, cfg: dict, base_dir: Path):
        max_text = cfg["max_text_bytes"]
        helper = base_dir / cfg["helper_bin"]
        self._tx = BackdoorTransport(
            helper, cfg["poll_ms"], self._on_host_copy, max_text)
        self._clip = X11Clipboard(self._on_guest_copy, max_text)

    def run(self):
        self._tx.start()
        logging.info("clipsync-tool ready")
        self._clip.run_forever()  # blocks: X event loop on the main thread

    def _on_guest_copy(self, text: str):
        # A guest app put new text on the X11 CLIPBOARD selection.
        with task_scope("guest->host"):
            if self._tx.send(text):
                logging.info("guest->host %d chars", len(text))

    def _on_host_copy(self, text: str):
        # The helper reports the host clipboard changed.
        with task_scope("host->guest"):
            self._clip.set_text(text)
            logging.info("host->guest %d chars", len(text))
