"""Rotating file logger configured for Japanese-safe Windows paths."""

from __future__ import annotations

import logging
import logging.handlers
import sys

from stocker.app_paths import log_dir


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    log_dir().mkdir(parents=True, exist_ok=True)
    log_file = log_dir() / "stocker.log"

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)

    stream_handler = logging.StreamHandler(sys.stderr)
    stream_handler.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    root.addHandler(file_handler)
    root.addHandler(stream_handler)
    return root
