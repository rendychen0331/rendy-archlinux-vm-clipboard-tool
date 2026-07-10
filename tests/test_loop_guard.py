import time

from src.loop_guard import LoopGuard


def test_mark_then_skip_consumes_once():
    g = LoopGuard(ttl_seconds=10)
    g.mark("h1")
    assert g.should_skip("h1") is True
    assert g.should_skip("h1") is False  # consumed


def test_unmarked_hash_not_skipped():
    g = LoopGuard(ttl_seconds=10)
    assert g.should_skip("nope") is False


def test_ttl_expiry():
    g = LoopGuard(ttl_seconds=0.01)
    g.mark("h1")
    time.sleep(0.03)
    assert g.should_skip("h1") is False
