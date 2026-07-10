"""clipsync-tool entry point (v2, backdoor transport)."""
import logging
import os
from pathlib import Path

from src.app import ToolApp
from src.config_loader import load_config
from src.logger_setup import setup_logging

DEFAULTS = {
    "helper_bin": "backdoor_helper",
    "poll_ms": 400,
    "max_text_bytes": 1048576,
    "log_level": "INFO",
}


def _runtime_paths(base: Path) -> tuple[Path, Path]:
    """Return (config_path, log_dir).

    Dev / self-contained (~/clipsync-tool): the code dir is writable, so keep
    config + logs next to main.py. Packaged (/usr/lib/... is root-owned and not
    writable by the user running the daemon): fall back to XDG user dirs so the
    normal user can still write. Mirrors config-management.md's exe-dir rule.
    """
    if os.access(base, os.W_OK):
        return base / "config.json", base / "logs"
    cfg_home = Path(os.environ.get("XDG_CONFIG_HOME",
                                   Path.home() / ".config")) / "clipsync-tool"
    state_home = Path(os.environ.get("XDG_STATE_HOME",
                                     Path.home() / ".local/state")) \
        / "clipsync-tool"
    cfg_home.mkdir(parents=True, exist_ok=True)
    return cfg_home / "config.json", state_home / "logs"


def main():
    base = Path(__file__).resolve().parent
    config_path, log_dir = _runtime_paths(base)
    cfg = load_config(config_path, DEFAULTS)
    setup_logging(log_dir,
                  getattr(logging, str(cfg["log_level"]).upper(),
                          logging.INFO),
                  prefix="clipsync-tool")
    logging.info("starting clipsync-tool (config=%s)", config_path)
    ToolApp(cfg, base).run()


if __name__ == "__main__":
    main()
