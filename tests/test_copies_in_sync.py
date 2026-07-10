"""Shared modules are deployed as verbatim copies in each side's src/ so every
machine is self-contained. This test is the sync contract: edit one copy, edit
them all. Each module maps to the set of dirs that must hold an identical copy.
"""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# module -> dirs (under ROOT) whose src/ copies must be byte-identical
COPIES = {
    "config_loader.py": ["host", "guest", "tool"],
    "logger_setup.py": ["host", "guest", "tool"],
    "protocol.py": ["host", "guest"],
    "loop_guard.py": ["host", "guest"],
    "clipboard_x11.py": ["guest", "tool"],
}

CASES = [(name, dirs) for name, dirs in COPIES.items()]


@pytest.mark.parametrize("name,dirs", CASES)
def test_copies_identical(name, dirs):
    texts = {d: (ROOT / d / "src" / name).read_text(encoding="utf-8")
             for d in dirs}
    first = dirs[0]
    for d in dirs[1:]:
        assert texts[d] == texts[first], (
            f"{name} differs between {first}/src and {d}/src")


def test_backdoor_asm_matches_probe():
    # tool/rustsrc/backdoor.s is the same proven asm the probe validated.
    probe = (ROOT / "tmp_tests" / "backdoor.s").read_text(encoding="utf-8")
    tool = (ROOT / "tool" / "rustsrc" / "backdoor.s").read_text(encoding="utf-8")
    assert probe == tool, "backdoor.s drifted between probe and tool"
