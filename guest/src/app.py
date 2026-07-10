"""Guest app wiring: X11 clipboard change -> send to host;
message from host -> own the X11 selection (loop-guarded).
"""
import logging

from src import protocol
from src.client import SyncClient
from src.clipboard_x11 import X11Clipboard
from src.logger_setup import task_scope
from src.loop_guard import LoopGuard


class GuestApp:
    def __init__(self, cfg: dict):
        if not cfg["host_ip"]:
            raise SystemExit(
                "config.json: host_ip is empty. Set it to the Windows host "
                "IP on the VMware NAT network (usually x.x.x.1 - check "
                "'ip route' for the subnet).")
        self._max_text = cfg["max_text_bytes"]
        self._guard = LoopGuard(cfg["loop_guard_ttl_seconds"])
        self._last_hash = None  # last content sent or applied, for dedupe
        self._client = SyncClient(
            cfg["host_ip"], cfg["host_port"], cfg["token"],
            max_line_bytes=self._max_text * 2 + 4096,
            on_message=self._on_remote,
            reconnect_max_seconds=cfg["reconnect_max_seconds"])
        self._clip = X11Clipboard(self._on_local_text, self._max_text)
        if cfg["token"] == "change-me":
            logging.warning(
                "token is still the default 'change-me' - set your own in "
                "config.json on both sides")

    def run(self):
        self._client.start()
        logging.info("clipsync-guest ready")
        self._clip.run_forever()  # blocks; X event loop on main thread

    def _on_local_text(self, text: str):
        h = protocol.text_hash(text)
        if self._guard.should_skip(h):
            logging.debug("echo of remote content, not sent back")
            return
        if h == self._last_hash:
            return
        with task_scope("local->host"):
            if self._client.send(protocol.make_clip(text)):
                self._last_hash = h
                logging.info("sent %d chars to host", len(text))
            else:
                logging.info("host not connected, %d chars dropped",
                             len(text))

    def _on_remote(self, msg: dict):
        if msg.get("type") != "clip" or msg.get("mime") != "text/plain":
            logging.warning("unsupported message ignored: type=%s mime=%s",
                            msg.get("type"), msg.get("mime"))
            return
        with task_scope("host->local"):
            text = protocol.clip_text(msg)
            h = protocol.text_hash(text)
            self._guard.mark(h)
            self._last_hash = h
            self._clip.set_text(text)
            logging.info("applied %d chars from host", len(text))
