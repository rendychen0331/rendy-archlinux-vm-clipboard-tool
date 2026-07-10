"""The tool's backdoor assembly must stay identical to the version the probe
validated on the real VM. This is the sync contract between tmp_tests/backdoor.s
(the proven probe) and tool/rustsrc/backdoor.s (what ships).
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_backdoor_asm_matches_probe():
    probe = (ROOT / "tmp_tests" / "backdoor.s").read_text(encoding="utf-8")
    tool = (ROOT / "tool" / "rustsrc" / "backdoor.s").read_text(encoding="utf-8")
    assert probe == tool, "backdoor.s drifted between probe and tool"
