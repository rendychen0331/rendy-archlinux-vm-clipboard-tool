"""clipsync-host entry point: load config, set up logging, run."""
import logging
from pathlib import Path

from src.app import HostApp
from src.config_loader import load_config
from src.logger_setup import setup_logging

DEFAULTS = {
    "listen_host": "0.0.0.0",
    "listen_port": 27333,
    "token": "change-me",
    "max_text_bytes": 1048576,
    "loop_guard_ttl_seconds": 10,
    "log_level": "INFO",
}


def main():
    base = Path(__file__).resolve().parent
    cfg = load_config(base / "config.json", DEFAULTS)
    setup_logging(base / "logs",
                  getattr(logging, str(cfg["log_level"]).upper(),
                          logging.INFO),
                  prefix="clipsync-host")
    logging.info("starting clipsync-host")
    HostApp(cfg).run()


if __name__ == "__main__":
    main()
