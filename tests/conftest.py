import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Import shared modules from the host copy; test_copies_in_sync.py
# guarantees the guest copy is byte-identical.
sys.path.insert(0, str(ROOT / "host"))
