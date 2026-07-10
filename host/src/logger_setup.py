"""Logging setup per rules/python/logging.md: pipe format with trace_id,
daily file + .err.log + .task.jsonl derived views, 30-day retention.

Duplicated verbatim in host/src and guest/src (see protocol.py header).
"""
import contextvars
import glob
import itertools
import json
import logging
import os
import sys
import time
from contextlib import contextmanager
from datetime import datetime

_parent = os.environ.get("LOG_TRACE_ID")
RUN_ID = (f"{_parent}>{os.getpid()}" if _parent
          else f"{datetime.now():%H%M%S}-{os.getpid()}")
_seq = itertools.count(1)
_trace = contextvars.ContextVar("trace_id", default="-")


class TraceFilter(logging.Filter):
    def filter(self, record):
        record.trace_id = _trace.get()
        return True


class DailyFileHandler(logging.FileHandler):
    """Append-mode handler with the date in the filename; re-opens under the
    new name when the day changes. No rename-and-reopen."""

    def __init__(self, log_dir, prefix, suffix=".log"):
        self._dir, self._prefix, self._suffix = log_dir, prefix, suffix
        self._day = f"{datetime.now():%Y%m%d}"
        super().__init__(self._path(), mode="a", encoding="utf-8", delay=True)

    def _path(self):
        return os.path.join(
            self._dir, f"{self._prefix}_{self._day}{self._suffix}")

    def emit(self, record):
        day = f"{datetime.now():%Y%m%d}"
        if day != self._day:
            self._day = day
            self.close()
            self.baseFilename = os.path.abspath(self._path())
        super().emit(record)


def _cleanup_old_logs(log_dir, prefix, keep_days=30):
    cutoff = time.time() - keep_days * 86400
    for p in glob.glob(os.path.join(log_dir, f"{prefix}_*")):
        try:
            if os.path.getmtime(p) < cutoff:
                os.remove(p)
        except OSError as e:
            logging.warning("log cleanup skipped %s: %s", p, e)


def setup_logging(log_dir, log_level=logging.INFO, prefix="app"):
    root = logging.getLogger()
    if root.handlers:  # idempotent: a second call must not duplicate handlers
        return
    os.makedirs(log_dir, exist_ok=True)
    root.setLevel(log_level)
    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(trace_id)s | %(message)s")

    def _add(handler, level=None):
        handler.setFormatter(fmt)
        handler.addFilter(TraceFilter())
        if level:
            handler.setLevel(level)
        root.addHandler(handler)

    _add(DailyFileHandler(log_dir, prefix))
    _add(DailyFileHandler(log_dir, prefix, ".err.log"), logging.WARNING)
    _add(logging.StreamHandler(sys.stdout))

    journal = logging.getLogger("task_journal")
    journal.propagate = False
    jh = DailyFileHandler(log_dir, prefix, ".task.jsonl")
    jh.setFormatter(logging.Formatter("%(message)s"))
    journal.addHandler(jh)

    _cleanup_old_logs(log_dir, prefix)


@contextmanager
def task_scope(biz_key: str = ""):
    tid = f"{RUN_ID}.{next(_seq):04d}"
    token = _trace.set(tid)
    t0 = time.monotonic()
    logging.info("task start | %s", biz_key)
    status, err = "ok", ""
    try:
        yield tid
    except Exception as e:
        status, err = "fail", f"{type(e).__name__}: {e}"
        logging.exception("task failed")
        raise
    finally:
        _trace.reset(token)
        logging.getLogger("task_journal").info(json.dumps({
            "time": datetime.now().isoformat(timespec="seconds"),
            "task_id": tid, "biz_key": biz_key, "status": status,
            "duration_ms": round((time.monotonic() - t0) * 1000),
            "error": err}, ensure_ascii=False))
