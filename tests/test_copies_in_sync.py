"""The shared modules are deployed as verbatim copies in host/src and
guest/src (each side must be self-contained on its machine). This test
is the sync contract: if one copy is edited, the other must be too.
"""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SHARED = ["protocol.py", "loop_guard.py", "config_loader.py",
          "logger_setup.py"]


@pytest.mark.parametrize("name", SHARED)
def test_host_and_guest_copies_identical(name):
    host = (ROOT / "host" / "src" / name).read_text(encoding="utf-8")
    guest = (ROOT / "guest" / "src" / name).read_text(encoding="utf-8")
    assert host == guest, f"{name} differs between host/src and guest/src"
