import socket
import threading

import pytest

from src import protocol


def test_clip_roundtrip_chinese():
    text = "中文剪貼簿 test 123\n\tline2"
    msg = protocol.make_clip(text)
    assert msg["type"] == "clip"
    assert msg["mime"] == "text/plain"
    assert protocol.clip_text(msg) == text
    assert msg["hash"] == protocol.text_hash(text)


def test_encode_is_ascii_line():
    raw = protocol.encode(protocol.make_clip("測試"))
    assert raw.endswith(b"\n")
    raw.decode("ascii")  # must not raise


def _pipe():
    a, b = socket.socketpair()
    return a, b


def test_read_messages_multiple_and_partial():
    a, b = _pipe()
    m1 = protocol.encode(protocol.make_clip("one"))
    m2 = protocol.encode(protocol.make_hello("tok"))
    # send in awkward fragments crossing message boundaries
    blob = m1 + m2
    def feed():
        for i in range(0, len(blob), 7):
            a.sendall(blob[i:i + 7])
        a.close()
    threading.Thread(target=feed).start()
    got = list(protocol.read_messages(b, 65536))
    assert len(got) == 2
    assert protocol.clip_text(got[0]) == "one"
    assert got[1] == {"type": "hello", "token": "tok"}


def test_read_messages_oversize_raises():
    a, b = _pipe()
    a.sendall(b"x" * 200)
    with pytest.raises(protocol.ProtocolError):
        list(protocol.read_messages(b, 100))
    a.close()


def test_read_messages_bad_json_raises():
    a, b = _pipe()
    a.sendall(b"{not json}\n")
    a.close()
    with pytest.raises(protocol.ProtocolError):
        list(protocol.read_messages(b, 65536))
