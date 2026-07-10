"""Host app wiring: local clipboard change -> send to guest;
message from guest -> write local clipboard (loop-guarded).
"""
import logging
import threading

from src import clipboard_win, protocol
from src.logger_setup import task_scope
from src.loop_guard import LoopGuard
from src.server import SyncServer


class HostApp:
    def __init__(self, cfg: dict):
        self._max_text = cfg["max_text_bytes"]
        self._guard = LoopGuard(cfg["loop_guard_ttl_seconds"])
        self._last_hash = None  # last content sent or applied, for dedupe
        self._server = SyncServer(
            cfg["listen_host"], cfg["listen_port"], cfg["token"],
            max_line_bytes=self._max_text * 2 + 4096,
            on_message=self._on_remote)
        self._listener = clipboard_win.WinClipboardListener(
            self._on_local_change)
        if cfg["token"] == "change-me":
            logging.warning(
                "token is still the default 'change-me' - set your own in "
                "config.json on both sides")

    def run(self):
        self._server.start()
        self._listener.start()
        logging.info("clipsync-host ready")
        threading.Event().wait()  # park main thread; workers are daemons

    def _on_local_change(self):
        text = clipboard_win.get_text()
        if not text:
            return  # empty or non-text clipboard
        if len(text.encode("utf-8")) > self._max_text:
            logging.warning("clipboard text exceeds max_text_bytes, skipped")
            return
        h = protocol.text_hash(text)
        if self._guard.should_skip(h):
            logging.debug("echo of remote content, not sent back")
            return
        if h == self._last_hash:
            return
        with task_scope("local->guest"):
            if self._server.send(protocol.make_clip(text)):
                self._last_hash = h
                logging.info("sent %d chars to guest", len(text))
            else:
                logging.info("guest not connected, %d chars dropped",
                             len(text))

    def _on_remote(self, msg: dict):
        if msg.get("type") != "clip" or msg.get("mime") != "text/plain":
            logging.warning("unsupported message ignored: type=%s mime=%s",
                            msg.get("type"), msg.get("mime"))
            return
        with task_scope("guest->local"):
            text = protocol.clip_text(msg)
            h = protocol.text_hash(text)
            self._guard.mark(h)
            self._last_hash = h
            clipboard_win.set_text(text)
            logging.info("applied %d chars from guest", len(text))
