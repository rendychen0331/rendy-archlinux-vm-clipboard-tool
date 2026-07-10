"""Wire protocol: newline-delimited JSON over TCP.

Message types:
  {"type": "hello", "token": "..."}                      -- client handshake
  {"type": "clip", "mime": "text/plain",
   "data": "<base64 utf-8>", "hash": "<sha256 hex>"}     -- clipboard payload

This file is duplicated verbatim in host/src and guest/src so each side
deploys self-contained; tests/test_copies_in_sync.py enforces equality.
"""
import base64
import hashlib
import json


class ProtocolError(Exception):
    pass


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def make_hello(token: str) -> dict:
    return {"type": "hello", "token": token}


def make_clip(text: str) -> dict:
    return {
        "type": "clip",
        "mime": "text/plain",
        "data": base64.b64encode(text.encode("utf-8")).decode("ascii"),
        "hash": text_hash(text),
    }


def clip_text(msg: dict) -> str:
    return base64.b64decode(msg["data"]).decode("utf-8")


def encode(msg: dict) -> bytes:
    return json.dumps(msg, ensure_ascii=True).encode("ascii") + b"\n"


def read_messages(sock, max_line_bytes: int):
    """Yield decoded messages from a socket until it closes.

    Raises ProtocolError on an oversized line or malformed JSON.
    """
    buf = b""
    while True:
        chunk = sock.recv(65536)
        if not chunk:
            return
        buf += chunk
        if len(buf) > max_line_bytes:
            raise ProtocolError(
                "line too long: %d > %d" % (len(buf), max_line_bytes))
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            if not line.strip():
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as e:
                raise ProtocolError("bad json: %s" % e) from e
