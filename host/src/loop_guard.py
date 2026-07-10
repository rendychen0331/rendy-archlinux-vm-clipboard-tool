"""Echo-loop protection for bidirectional clipboard sync.

When we write remote content into the local clipboard, the OS fires a
local change event; without this guard that event would be sent back to
the peer and ping-pong forever. mark() before writing, should_skip() in
the change handler consumes the mark exactly once.

Duplicated verbatim in host/src and guest/src (see protocol.py header).
"""
import threading
import time


class LoopGuard:
    def __init__(self, ttl_seconds: float = 10.0):
        self._ttl = ttl_seconds
        self._items = {}  # content hash -> expiry (monotonic)
        self._lock = threading.Lock()

    def mark(self, content_hash: str) -> None:
        with self._lock:
            self._items[content_hash] = time.monotonic() + self._ttl

    def should_skip(self, content_hash: str) -> bool:
        now = time.monotonic()
        with self._lock:
            self._items = {h: t for h, t in self._items.items() if t > now}
            return self._items.pop(content_hash, None) is not None
