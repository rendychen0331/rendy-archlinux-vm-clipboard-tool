"""TCP server for the guest connection. Single client; a newly
authenticated connection replaces the previous one (reconnect wins).
"""
import logging
import socket
import threading

from src import protocol

HANDSHAKE_TIMEOUT = 10.0


class SyncServer:
    def __init__(self, host: str, port: int, token: str,
                 max_line_bytes: int, on_message):
        self._addr = (host, port)
        self._token = token
        self._max = max_line_bytes
        self._on_message = on_message
        self._client = None
        self._lock = threading.Lock()

    def start(self):
        self._sock = socket.create_server(self._addr, reuse_port=False)
        threading.Thread(
            target=self._accept_loop, name="accept", daemon=True).start()
        logging.info("listening on %s:%s", *self._addr)

    def _accept_loop(self):
        while True:
            conn, addr = self._sock.accept()
            threading.Thread(
                target=self._serve, args=(conn, addr),
                name=f"client-{addr[0]}", daemon=True).start()

    def _serve(self, conn, addr):
        try:
            conn.settimeout(HANDSHAKE_TIMEOUT)
            msgs = protocol.read_messages(conn, self._max)
            hello = next(msgs, None)
            if (not hello or hello.get("type") != "hello"
                    or hello.get("token") != self._token):
                logging.warning("client %s rejected: bad handshake", addr)
                return
            conn.settimeout(None)
            with self._lock:
                if self._client is not None:
                    logging.info("replacing previous client")
                    self._client.close()
                self._client = conn
            logging.info("client %s connected", addr)
            for msg in msgs:
                self._on_message(msg)
            logging.info("client %s disconnected", addr)
        except (OSError, protocol.ProtocolError) as e:
            logging.warning("client %s dropped: %s", addr, e)
        finally:
            with self._lock:
                if self._client is conn:
                    self._client = None
            conn.close()

    def send(self, msg: dict) -> bool:
        """Send to the connected client; False if none / send failed."""
        with self._lock:
            conn = self._client
        if conn is None:
            logging.debug("no client connected, message dropped")
            return False
        try:
            conn.sendall(protocol.encode(msg))
            return True
        except OSError as e:
            logging.warning("send failed: %s", e)
            return False
