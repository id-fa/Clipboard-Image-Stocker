"""User configuration persisted as JSON in user_data_dir/config.json."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from stocker.app_paths import config_path, ensure_user_data_dir


@dataclass
class AppConfig:
    # Workspace model: a single base folder; managed folders are subdirectories.
    workspace_root: str | None = None
    last_active_root: str | None = None  # active subfolder (or workspace itself)
    columns: int = 6  # default / last-used column count
    # Per-folder column memory keyed by workspace-relative path ("." = root).
    folder_columns: dict[str, int] = field(default_factory=dict)
    thumbnail_aspect: str = "1:1"  # "1:1" | "4:3" | "16:9" | "3:4" | "9:16"
    sort_key: str = "name"  # "name" or "mtime" or "added"
    sort_dir: str = "asc"  # "asc" or "desc"
    sidebar_font_size: int = 12  # points
    paste_format: str = "png"  # "png" or "jpeg"
    paste_jpeg_quality: int = 92
    clipboard_autocapture: bool = False  # auto-import images appearing on clipboard
    hover_preview_enabled: bool = True  # show fitted preview after hover delay
    hover_preview_animate: bool = True  # play animated GIF/WebP in the hover preview
    minimize_to_tray: bool = False  # hide window to system tray on minimize
    theme: str = "light"  # "light" or "dark"
    log_panel_enabled: bool = True  # show the bottom log row above the status bar
    trash_auto_delete_days: int = 0  # 0 = never auto-delete
    window_geometry_b64: str | None = None
    window_state_b64: str | None = None
    splitter_state_b64: str | None = None

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)

    @classmethod
    def from_json(cls, text: str) -> AppConfig:
        data = json.loads(text)
        known = {f for f in cls.__dataclass_fields__}
        filtered = {k: v for k, v in data.items() if k in known}
        fc = filtered.get("folder_columns")
        if isinstance(fc, dict):
            filtered["folder_columns"] = {
                str(k): int(v) for k, v in fc.items()
                if isinstance(v, int) and not isinstance(v, bool)
            }
        else:
            filtered.pop("folder_columns", None)
        return cls(**filtered)


def load_config() -> AppConfig:
    ensure_user_data_dir()
    path: Path = config_path()
    if not path.exists():
        return AppConfig()
    try:
        return AppConfig.from_json(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, TypeError, ValueError):
        return AppConfig()


def save_config(cfg: AppConfig) -> None:
    ensure_user_data_dir()
    path: Path = config_path()
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(cfg.to_json(), encoding="utf-8")
    tmp.replace(path)
