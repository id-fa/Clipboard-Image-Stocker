"""Centralised path resolution for app data, config, and per-folder .stocker layout."""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "Stocker"
APP_VERSION = "1.05"
APP_AUTHOR = "id-fa"
APP_HOMEPAGE = "https://github.com/id-fa/Clipboard-Image-Stocker"
STOCKER_DIRNAME = ".stocker"
THUMBS_DIRNAME = "thumbs"
TRASH_DIRNAME = ".trash"
DB_FILENAME = "metadata.db"
PORTABLE_FLAG = "portable.flag"
CONFIG_FILENAME = "config.json"

# Directory names that should be hidden from the sidebar tree and skipped
# during scans. The .stocker dir is per-folder; .trash lives at the workspace root.
HIDDEN_DIR_NAMES = frozenset({STOCKER_DIRNAME, TRASH_DIRNAME})


def _exe_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent.parent


def is_portable() -> bool:
    return (_exe_dir() / PORTABLE_FLAG).exists()


def user_data_dir() -> Path:
    if is_portable():
        return _exe_dir() / "userdata"
    appdata = os.getenv("APPDATA")
    base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
    return base / APP_NAME


def config_path() -> Path:
    return user_data_dir() / CONFIG_FILENAME


def log_dir() -> Path:
    return user_data_dir() / "logs"


def stocker_dir(folder_root: Path) -> Path:
    return folder_root / STOCKER_DIRNAME


def db_path(folder_root: Path) -> Path:
    return stocker_dir(folder_root) / DB_FILENAME


def thumbs_dir(folder_root: Path) -> Path:
    return stocker_dir(folder_root) / THUMBS_DIRNAME


def ensure_stocker_layout(folder_root: Path) -> None:
    stocker_dir(folder_root).mkdir(parents=True, exist_ok=True)
    thumbs_dir(folder_root).mkdir(parents=True, exist_ok=True)


def ensure_user_data_dir() -> Path:
    d = user_data_dir()
    d.mkdir(parents=True, exist_ok=True)
    log_dir().mkdir(parents=True, exist_ok=True)
    return d
