"""clipsync-tool entry point (v2, backdoor transport)."""
import logging
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


def main():
    base = Path(__file__).resolve().parent
    cfg = load_config(base / "config.json", DEFAULTS)
    setup_logging(base / "logs",
                  getattr(logging, str(cfg["log_level"]).upper(),
                          logging.INFO),
                  prefix="clipsync-tool")
    logging.info("starting clipsync-tool")
    ToolApp(cfg, base).run()


if __name__ == "__main__":
    main()
