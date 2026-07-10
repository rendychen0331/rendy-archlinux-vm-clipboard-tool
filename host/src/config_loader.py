"""Load config.json next to the entry file; create with defaults if missing.

Duplicated verbatim in host/src and guest/src (see protocol.py header).
"""
import json
import os
from pathlib import Path


def load_config(path: Path, defaults: dict) -> dict:
    if not path.exists():
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(defaults, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8")
        os.replace(tmp, path)
        return dict(defaults)
    cfg = json.loads(path.read_text(encoding="utf-8"))
    return {**defaults, **cfg}
