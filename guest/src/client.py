"""TCP client to the host daemon, with auto-reconnect and backoff."""
import logging
import socket
import threading
import time

from src import protocol


class SyncClient:
    def __init__(self, host: str, port: int, token: str,
                 max_line_bytes: int, on_message,
                 reconnect_max_seconds: int = 30):
        self._addr = (host, port)
        self._token = token
        self._max = max_line_bytes
        self._on_message = on_message
        self._backoff_cap = reconnect_max_seconds
        self._sock = None
        self._lock = threading.Lock()

    def start(self):
        threading.Thread(
            target=self._run, name="sync-client", daemon=True).start()

    def _run(self):
        backoff = 1
        while True:
            try:
                sock = socket.create_connection(self._addr, timeout=10)
                sock.settimeout(None)
                sock.sendall(protocol.encode(
                    protocol.make_hello(self._token)))
                with self._lock:
                    self._sock = sock
                logging.info("connected to host %s:%s", *self._addr)
                backoff = 1
                for msg in protocol.read_messages(sock, self._max):
                    self._on_message(msg)
                logging.warning("host closed the connection")
            except (OSError, protocol.ProtocolError) as e:
                logging.warning("connection failed: %s", e)
            with self._lock:
                if self._sock is not None:
                    self._sock.close()
                    self._sock = None
            logging.info("reconnecting in %ds", backoff)
            time.sleep(backoff)
            backoff = min(backoff * 2, self._backoff_cap)

    def send(self, msg: dict) -> bool:
        with self._lock:
            sock = self._sock
        if sock is None:
            logging.debug("not connected, message dropped")
            return False
        try:
            sock.sendall(protocol.encode(msg))
            return True
        except OSError as e:
            logging.warning("send failed: %s", e)
            return False
