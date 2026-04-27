"""Application entry point."""

from __future__ import annotations

import logging
import os
import sys

# Force UTF-8 mode early — required for Japanese paths in frozen exes.
os.environ.setdefault("PYTHONUTF8", "1")
try:
    if sys.stdout is not None and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    if sys.stderr is not None and hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001
    pass

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from stocker.app_paths import APP_NAME
from stocker.config import load_config
from stocker.i18n import detect_language, set_language
from stocker.logging_setup import setup_logging
from stocker.ui.main_window import MainWindow


def main() -> int:
    setup_logging()
    log = logging.getLogger(__name__)

    QApplication.setAttribute(Qt.ApplicationAttribute.AA_DontUseNativeMenuBar, False)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("Stocker")

    set_language(detect_language())

    cfg = load_config()
    win = MainWindow(cfg)
    win.show()

    log.info("application started")
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
