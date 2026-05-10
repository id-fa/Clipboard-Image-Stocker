"""Main application window: ties together sidebar, toolbar, grid, and services."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from PySide6.QtCore import QEvent, QPoint, Qt, QThreadPool, QTimer, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressDialog,
    QSplitter,
    QStatusBar,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from stocker.app_paths import APP_AUTHOR, APP_HOMEPAGE, APP_NAME, APP_VERSION, HIDDEN_DIR_NAMES
from stocker.config import AppConfig, save_config
from stocker.i18n import tr
from stocker.core.clipboard_watcher import ClipboardWatcher
from stocker.core.folder_manager import FolderManager
from stocker.core.fs_watcher import FolderWatcher
from stocker.core.import_service import import_files
from stocker.core.models import FileItem, FileKind, PendingPaste, ThumbKey
from stocker.core.move_service import (
    MoveItemRef,
    MoveMode,
    MoveResult,
    parse_payload,
    perform_move,
)
from stocker.core.paste_queue import PasteQueue
from stocker.core.rename_service import rename_file
from stocker.core.scanner import count_image_files, scan_folder
from stocker.core.thumbnail_cache import ThumbnailCache
from stocker.core.thumbnail_worker import ThumbnailJob, ThumbnailSignals
from stocker.core import trash as trash_svc
from stocker.core.undo_manager import UndoEntry, UndoKind, UndoManager
from stocker.db.metadata_db import MetadataDB
from stocker.ui.hover_preview import HoverPreviewWindow
from stocker.ui.log_panel import LogPanel
from stocker.ui.sidebar import Sidebar
from stocker.ui.thumbnail_delegate import ThumbnailDelegate
from stocker.ui.theme import apply_theme
from stocker.ui.thumbnail_model import ITEM_ROLE, ThumbnailFilterProxy, ThumbnailModel
from stocker.ui.thumbnail_view import ThumbnailView
from stocker.ui.toolbar import StockerToolbar
from stocker.utils.clipboard_files import (
    copy_files_to_clipboard,
    copy_image_to_clipboard,
    file_urls_from_clipboard,
)
from stocker.utils.paths import from_rel, normalize_rel

log = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self, cfg: AppConfig):
        super().__init__()
        self.setWindowTitle("Clipboard Image Stocker")
        self.resize(1280, 800)

        self._cfg = cfg
        self._folder_manager = FolderManager(cfg)
        self._cache = ThumbnailCache()
        self._dbs: dict[Path, MetadataDB] = {}
        self._active_root: Path | None = None
        self._pool = QThreadPool.globalInstance()
        self._pool.setMaxThreadCount(min(8, os.cpu_count() or 4))
        self._thumb_signals = ThumbnailSignals(self)
        self._thumb_signals.ready.connect(self._on_thumb_ready)
        self._thumb_signals.failed.connect(self._on_thumb_failed)
        self._inflight_keys: set[ThumbKey] = set()

        # Toolbar (initial values applied with signals blocked so they don't
        # fire on widgets that haven't been constructed yet).
        self._toolbar = StockerToolbar(self)
        self.addToolBar(self._toolbar)
        self._toolbar.blockSignals(True)
        self._toolbar.set_columns(cfg.columns)
        self._toolbar.set_aspect(cfg.thumbnail_aspect)
        self._toolbar.set_sort(cfg.sort_key, cfg.sort_dir)
        self._toolbar.set_paste_format(cfg.paste_format)
        self._toolbar.set_autocapture(cfg.clipboard_autocapture)
        self._toolbar.set_hover_preview_enabled(cfg.hover_preview_enabled)
        self._toolbar.set_hover_preview_animate(cfg.hover_preview_animate)
        tray_available = QSystemTrayIcon.isSystemTrayAvailable()
        self._toolbar.set_minimize_to_tray(cfg.minimize_to_tray and tray_available)
        self._toolbar.set_minimize_to_tray_available(tray_available)
        self._toolbar.set_dark_theme(cfg.theme == "dark")
        self._toolbar.set_log_panel_enabled(cfg.log_panel_enabled)
        self._toolbar.set_font_size(cfg.sidebar_font_size)
        self._toolbar.set_trash_days(cfg.trash_auto_delete_days)
        self._toolbar.blockSignals(False)
        self._toolbar.set_workspace_requested.connect(self._on_set_workspace)
        self._toolbar.add_subfolder_requested.connect(self._on_add_subfolder_clicked)
        self._toolbar.columns_changed.connect(self._on_columns_changed)
        self._toolbar.aspect_changed.connect(self._on_aspect_changed)
        self._toolbar.filter_text_changed.connect(self._on_filter_changed)
        self._toolbar.sort_changed.connect(self._on_sort_changed)
        self._toolbar.paste_format_changed.connect(self._on_paste_format_changed)
        self._toolbar.clipboard_autocapture_changed.connect(self._on_autocapture_changed)
        self._toolbar.hover_preview_enabled_changed.connect(self._on_hover_preview_enabled_changed)
        self._toolbar.hover_preview_animate_changed.connect(self._on_hover_preview_animate_changed)
        self._toolbar.minimize_to_tray_changed.connect(self._on_minimize_to_tray_changed)
        self._toolbar.dark_theme_changed.connect(self._on_dark_theme_changed)
        self._toolbar.log_panel_enabled_changed.connect(self._on_log_panel_enabled_changed)
        self._toolbar.sidebar_font_size_changed.connect(self._on_sidebar_font_changed)
        self._toolbar.trash_days_changed.connect(self._on_trash_days_changed)
        self._toolbar.empty_trash_requested.connect(self._on_empty_trash)
        self._toolbar.about_requested.connect(self._on_about)

        # Center: splitter wrapped in a vertical layout so we can append a
        # log panel below it (between the grid and the QStatusBar).
        center = QWidget(self)
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(0)
        self._splitter = QSplitter(Qt.Orientation.Horizontal, center)
        center_layout.addWidget(self._splitter, 1)
        self._log_panel = LogPanel(center)
        self._log_panel.setVisible(cfg.log_panel_enabled)
        center_layout.addWidget(self._log_panel)
        self.setCentralWidget(center)

        # Sidebar
        self._sidebar = Sidebar(self)
        self._sidebar.set_font_size(cfg.sidebar_font_size)
        self._sidebar.folder_selected.connect(self._on_folder_selected)
        self._sidebar.trash_selected.connect(self._on_trash_selected)
        self._sidebar.create_subfolder_requested.connect(self._on_create_subfolder_under)
        self._sidebar.rename_folder_requested.connect(self._on_rename_folder_requested)
        self._sidebar.delete_folder_requested.connect(self._on_delete_folder_requested)
        self._sidebar.drop_stocker_items_to_folder.connect(self._on_drop_to_sidebar)
        self._sidebar.drop_external_files_to_folder.connect(self._on_drop_external_to_sidebar)
        self._splitter.addWidget(self._sidebar)

        # Thumbnail grid
        self._model = ThumbnailModel(self)
        self._model.set_cache_lookup(self._cache.get)
        self._model.set_sort(cfg.sort_key, cfg.sort_dir)
        self._model.request_thumbnail.connect(self._enqueue_thumbnail)
        self._proxy = ThumbnailFilterProxy(self)
        self._proxy.setSourceModel(self._model)
        self._view = ThumbnailView(self)
        self._view.setModel(self._proxy)
        self._view.setItemDelegate(ThumbnailDelegate(self))
        self._view.set_columns(cfg.columns)
        self._view.set_aspect(cfg.thumbnail_aspect)
        self._view.item_double_clicked.connect(self._on_item_double_clicked)
        self._view.drop_files.connect(self._on_drop_external_files_into_active)
        self._view.hover_changed.connect(self._on_hover_changed)
        self._view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._view.customContextMenuRequested.connect(self._on_context_menu)
        self._splitter.addWidget(self._view)
        self._splitter.setStretchFactor(0, 1)
        self._splitter.setStretchFactor(1, 4)

        # Hover preview
        self._hover_preview = HoverPreviewWindow(self)
        self._hover_preview.set_enabled(cfg.hover_preview_enabled)
        self._hover_preview.set_animate(cfg.hover_preview_animate)

        # FS watcher
        self._fs_watcher = FolderWatcher(self)
        self._fs_watcher.changed.connect(self._on_fs_changed)

        # Paste queue + clipboard
        self._paste_queue = PasteQueue(self)
        self._paste_queue.set_format(cfg.paste_format, cfg.paste_jpeg_quality)
        self._paste_queue.pending_added.connect(self._on_pending_added)
        self._paste_queue.paste_completed.connect(self._on_paste_completed)
        self._paste_queue.paste_failed.connect(self._on_paste_failed)
        self._paste_queue.backpressure_changed.connect(self._on_backpressure)
        self._paste_queue.start()
        self._clipboard = ClipboardWatcher(self._paste_queue, self)
        self._clipboard.set_autocapture(cfg.clipboard_autocapture)

        # Shortcuts
        self._paste_shortcut = QShortcut(QKeySequence.StandardKey.Paste, self)
        self._paste_shortcut.activated.connect(self._on_paste_shortcut)
        self._copy_files_shortcut = QShortcut(QKeySequence.StandardKey.Copy, self._view)
        self._copy_files_shortcut.activated.connect(self._on_copy_files_to_clipboard)
        self._rename_shortcut = QShortcut(QKeySequence("F2"), self._view)
        self._rename_shortcut.activated.connect(self._on_rename_shortcut)
        self._delete_shortcut = QShortcut(QKeySequence("Delete"), self._view)
        self._delete_shortcut.activated.connect(self._on_delete_shortcut)
        self._find_shortcut = QShortcut(QKeySequence.StandardKey.Find, self)
        self._find_shortcut.activated.connect(self._toolbar.focus_filter)
        self._undo_shortcut = QShortcut(QKeySequence.StandardKey.Undo, self)
        self._undo_shortcut.activated.connect(self._on_undo_shortcut)
        self._redo_shortcut = QShortcut(QKeySequence.StandardKey.Redo, self)
        self._redo_shortcut.activated.connect(self._on_redo_shortcut)

        # Undo/Redo state — 1 generation each side, cleared by any new op.
        self._undo_mgr = UndoManager()

        # Status bar
        self.setStatusBar(QStatusBar(self))
        self._status_label = QLabel("", self)
        self._queue_label = QLabel("", self)
        self.statusBar().addWidget(self._status_label, 1)
        self.statusBar().addPermanentWidget(self._queue_label)

        # System tray (optional). Built only when the platform exposes a tray;
        # toggled via cfg.minimize_to_tray. Closing via the [X] button still
        # quits the app — only an explicit minimize routes through the tray.
        self._tray: QSystemTrayIcon | None = None
        if tray_available:
            self._tray = QSystemTrayIcon(QApplication.windowIcon(), self)
            self._tray.setToolTip(APP_NAME)
            tray_menu = QMenu(self)
            act_show = tray_menu.addAction(tr("tray.show"))
            act_show.triggered.connect(self._show_from_tray)
            tray_menu.addSeparator()
            act_quit = tray_menu.addAction(tr("tray.quit"))
            act_quit.triggered.connect(self.close)
            self._tray.setContextMenu(tray_menu)
            self._tray.activated.connect(self._on_tray_activated)
            if cfg.minimize_to_tray:
                self._tray.show()

        # Initial workspace flow
        if not self._folder_manager.has_workspace():
            self._prompt_workspace_or_default()
        if self._folder_manager.has_workspace():
            self._refresh_sidebar()
            ws = self._folder_manager.workspace
            assert ws is not None
            initial: Path = ws
            if cfg.last_active_root:
                p = Path(cfg.last_active_root)
                if p.exists() and self._folder_manager.folder_under_workspace(p):
                    initial = p.resolve()
            self._activate_folder(initial)
            # Auto-purge old trash
            if cfg.trash_auto_delete_days > 0:
                purged = trash_svc.auto_purge(ws, cfg.trash_auto_delete_days)
                if purged:
                    log.info("auto-purged %d trashed files", purged)
            self._sidebar.update_trash_count(trash_svc.trash_count(ws))

    # ---- workspace ----

    def _prompt_workspace_or_default(self) -> None:
        msg = QMessageBox(self)
        msg.setWindowTitle(tr("dialog.workspace_select_title"))
        msg.setText(tr("dialog.workspace_select_body"))
        msg.setStandardButtons(
            QMessageBox.StandardButton.Open | QMessageBox.StandardButton.Cancel
        )
        if msg.exec() != QMessageBox.StandardButton.Open:
            return
        d = QFileDialog.getExistingDirectory(self, tr("dialog.workspace_select_picker"))
        if d:
            try:
                self._folder_manager.set_workspace(Path(d))
            except ValueError as e:
                QMessageBox.warning(self, tr("dialog.error"), str(e))

    def _on_set_workspace(self) -> None:
        d = QFileDialog.getExistingDirectory(self, tr("dialog.workspace_select_picker"))
        if not d:
            return
        # Close any open DBs from the previous workspace
        for db in self._dbs.values():
            db.close()
        self._dbs.clear()
        self._cache.clear()
        try:
            self._folder_manager.set_workspace(Path(d))
        except ValueError as e:
            QMessageBox.warning(self, tr("dialog.error"), str(e))
            return
        self._refresh_sidebar()
        ws = self._folder_manager.workspace
        if ws is not None:
            self._activate_folder(ws)

    def _on_add_subfolder_clicked(self) -> None:
        if not self._folder_manager.has_workspace():
            QMessageBox.information(
                self, tr("dialog.not_configured"),
                tr("dialog.configure_workspace_first"),
            )
            return
        parent = self._active_root or self._folder_manager.workspace
        self._on_create_subfolder_under(parent)

    def _on_create_subfolder_under(self, parent: Path | None) -> None:
        if not self._folder_manager.has_workspace():
            return
        parent = parent or self._folder_manager.workspace
        name, ok = QInputDialog.getText(
            self, tr("dialog.create_subfolder_title"),
            tr("dialog.create_subfolder_body", parent=parent.name),
        )
        if not ok or not name.strip():
            return
        try:
            new_path = self._folder_manager.create_subfolder(name.strip(), parent=parent)
        except ValueError as e:
            QMessageBox.warning(self, tr("dialog.create_failed"), str(e))
            return
        self._refresh_sidebar()
        self._activate_folder(new_path)

    def _on_rename_folder_requested(self, path: Path) -> None:
        """Rename a managed subfolder in place. Workspace root is excluded."""
        if not self._folder_manager.has_workspace():
            return
        ws = self._folder_manager.workspace
        assert ws is not None
        ws_resolved = ws.resolve()
        old_path = path.resolve()
        if old_path == ws_resolved:
            QMessageBox.information(
                self, tr("dialog.rename_disallowed"),
                tr("dialog.workspace_rename_blocked"),
            )
            return
        new_name, ok = QInputDialog.getText(
            self, tr("dialog.rename_folder_title"),
            tr("dialog.rename_folder_body", name=old_path.name),
            text=old_path.name,
        )
        if not ok:
            return
        new_name = new_name.strip()
        if not new_name or new_name == old_path.name:
            return

        old_active = self._active_root.resolve() if self._active_root else None

        # Windows holds locks on open SQLite files; close every DB whose path
        # is the renamed folder or any descendant before renaming the dir.
        affected_db_roots = [
            r for r in list(self._dbs.keys())
            if r == old_path or old_path in r.parents
        ]
        for r in affected_db_roots:
            self._dbs[r].close()
            del self._dbs[r]

        # Drop fs watcher and paste queue target so neither holds a stale path.
        self._fs_watcher.watch(None)
        self._paste_queue.set_target_root(None)

        try:
            old_rel = normalize_rel(old_path.relative_to(ws_resolved))
            new_path = self._folder_manager.rename_folder(old_path, new_name)
        except (ValueError, OSError) as e:
            QMessageBox.warning(self, tr("dialog.rename_failed"), str(e))
            if old_active is not None and old_active.exists():
                self._activate_folder(old_active)
            return

        new_rel = normalize_rel(new_path.relative_to(ws_resolved))
        trash_svc.rewrite_origin_paths(ws, old_rel, new_rel)

        # Translate the active path if it was inside the renamed subtree.
        new_active = old_active
        if old_active is not None and (
            old_active == old_path or old_path in old_active.parents
        ):
            try:
                sub = old_active.relative_to(old_path)
                new_active = (
                    new_path / sub if str(sub) not in ("", ".") else new_path
                ).resolve()
            except ValueError:
                new_active = new_path
        if new_active is None:
            new_active = new_path

        self._refresh_sidebar()
        self._activate_folder(new_active)

    def _on_delete_folder_requested(self, path: Path) -> None:
        """Delete a managed subfolder; files in the subtree go to trash.

        The workspace root is rejected. Every file under the subtree
        (excluding internal dirs like .stocker / .trash) is moved to the
        workspace trash with origin tracked at its immediate parent, then
        the directory is rmtree-d. DBs whose path lies within the subtree
        are closed first to release Windows file locks.
        """
        if not self._folder_manager.has_workspace():
            return
        ws = self._folder_manager.workspace
        assert ws is not None
        target = path.resolve()
        if target == ws.resolve():
            QMessageBox.information(
                self, tr("dialog.delete_disallowed"),
                tr("dialog.workspace_delete_blocked"),
            )
            return
        if not target.is_dir():
            return

        # Collect every file under the subtree, paired with its immediate
        # parent (which is the managed folder it belongs to in this app's
        # model — every dir under workspace owns its own .stocker DB).
        files_to_trash: list[tuple[Path, Path]] = []
        for current_root, dirnames, filenames in os.walk(target):
            dirnames[:] = [d for d in dirnames if d not in HIDDEN_DIR_NAMES]
            parent = Path(current_root)
            for fn in filenames:
                files_to_trash.append((parent / fn, parent))

        n_files = len(files_to_trash)
        body_key = (
            "dialog.delete_folder_body" if n_files
            else "dialog.delete_folder_empty_body"
        )
        if (
            QMessageBox.question(
                self, tr("dialog.delete_folder_title"),
                tr(body_key, name=target.name, n=n_files),
            )
            != QMessageBox.StandardButton.Yes
        ):
            return

        # Close every DB whose root is the target or below — Windows holds
        # file locks on open SQLite handles and would block rmtree.
        affected_db_roots = [
            r for r in list(self._dbs.keys())
            if r == target or target in r.parents
        ]
        for r in affected_db_roots:
            self._dbs[r].close()
            del self._dbs[r]

        active_in_subtree = (
            self._active_root is not None
            and (
                self._active_root == target
                or target in self._active_root.parents
            )
        )
        if active_in_subtree:
            self._fs_watcher.watch(None)
            self._paste_queue.set_target_root(None)

        moved = trash_svc.move_to_trash(ws, files_to_trash)

        try:
            self._folder_manager.delete_folder(target)
        except (ValueError, OSError) as e:
            QMessageBox.warning(self, tr("dialog.delete_failed"), str(e))
            self._refresh_sidebar()
            if active_in_subtree:
                self._activate_folder(ws)
            else:
                self._sidebar.update_trash_count(trash_svc.trash_count(ws))
            return

        self._refresh_sidebar()
        if active_in_subtree:
            self._activate_folder(ws)
        else:
            self._sidebar.update_trash_count(trash_svc.trash_count(ws))
        self._update_status()
        log.info("deleted folder %s; trashed %d files", target, len(moved))

    def _refresh_sidebar(self) -> None:
        ws = self._folder_manager.workspace
        folders = self._folder_manager.all_folders()
        n_trash = trash_svc.trash_count(ws) if ws else 0
        counts: dict[Path, int] = {}
        for f in folders:
            try:
                counts[f.resolve()] = count_image_files(f)
            except OSError as e:
                log.warning("count failed for %s: %s", f, e)
        self._sidebar.populate(ws, folders, trash_count=n_trash, folder_counts=counts)
        if self._active_root is not None:
            self._sidebar.select_path(self._active_root)

    def _refresh_folder_count(self, folder: Path | None) -> None:
        """Update one folder node's count badge in the sidebar.

        Cheap (single non-recursive scandir) so call sites don't need to debounce.
        Skips the trash root — trash uses ``update_trash_count`` instead.
        """
        if folder is None:
            return
        ws = self._folder_manager.workspace
        if ws is not None and folder.resolve() == trash_svc.trash_root(ws).resolve():
            return
        try:
            n = count_image_files(folder)
        except OSError as e:
            log.warning("count failed for %s: %s", folder, e)
            return
        self._sidebar.update_folder_count(folder, n)

    # ---- DB pool ----

    def _db(self, root: Path) -> MetadataDB:
        root = root.resolve()
        if root not in self._dbs:
            self._dbs[root] = MetadataDB.open(root)
        return self._dbs[root]

    # ---- folder activation ----

    def _on_folder_selected(self, path: Path) -> None:
        if self._active_root and path.resolve() == self._active_root.resolve():
            return
        self._activate_folder(path)

    def _activate_folder(self, root: Path) -> None:
        self._active_root = root.resolve()
        db = self._db(self._active_root)
        self._cache.clear()
        self._cache.configure(self._active_root, db.count_files())
        self._model.set_root(self._active_root)
        self._paste_queue.set_target_root(self._active_root)

        result = scan_folder(self._active_root, db)
        log.info(
            "scan: %s added=%d updated=%d removed=%d total=%d",
            self._active_root.name, len(result.added), len(result.updated),
            len(result.removed), result.total,
        )
        self._cache.update_policy(db.count_files())
        items = db.list_files(self._cfg.sort_key, self._cfg.sort_dir)
        self._model.replace(items)
        self._sidebar.select_path(self._active_root)
        if result.changed:
            self._refresh_folder_count(self._active_root)
        self._fs_watcher.watch(self._active_root)
        self._cfg.last_active_root = str(self._active_root)
        save_config(self._cfg)
        self._update_status()

    def _on_trash_selected(self) -> None:
        ws = self._folder_manager.workspace
        if ws is None:
            return
        # Open trash like a regular folder; write actions are limited by callers.
        troot = trash_svc.trash_root(ws)
        if not troot.exists():
            troot.mkdir(parents=True, exist_ok=True)
        self._activate_folder(troot)

    def _on_fs_changed(self, root: Path) -> None:
        if self._active_root is None or self._active_root != root:
            return
        db = self._db(root)
        result = scan_folder(root, db)
        if not result.changed:
            return
        log.info("fs change: %s added=%d removed=%d", root, len(result.added), len(result.removed))
        for it in result.added:
            self._model.append_item(it)  # dedupe inside append_item
        if result.removed:
            self._model.remove_by_rels(result.removed)
        self._cache.update_policy(db.count_files())
        self._refresh_folder_count(root)
        self._update_status()

    # ---- toolbar handlers ----

    def _on_columns_changed(self, n: int) -> None:
        self._view.set_columns(n)
        self._cfg.columns = n
        save_config(self._cfg)

    def _on_aspect_changed(self, ratio: str) -> None:
        if ratio == self._cfg.thumbnail_aspect:
            return
        self._cfg.thumbnail_aspect = ratio
        save_config(self._cfg)
        self._view.set_aspect(ratio)

    def _on_filter_changed(self, text: str) -> None:
        # Filter is intentionally session-only (not persisted) — opening the app
        # to a non-empty filter would be confusing.
        self._proxy.setFilterFixedString(text)

    def _on_sort_changed(self, key: str, direction: str) -> None:
        self._cfg.sort_key = key
        self._cfg.sort_dir = direction
        save_config(self._cfg)
        self._model.set_sort(key, direction)
        if self._active_root is not None:
            db = self._db(self._active_root)
            self._model.replace(db.list_files(key, direction))

    def _on_paste_format_changed(self, fmt: str) -> None:
        self._cfg.paste_format = fmt
        save_config(self._cfg)
        self._paste_queue.set_format(fmt, self._cfg.paste_jpeg_quality)

    def _on_autocapture_changed(self, enabled: bool) -> None:
        self._cfg.clipboard_autocapture = bool(enabled)
        save_config(self._cfg)
        self._clipboard.set_autocapture(bool(enabled))

    def _on_hover_preview_enabled_changed(self, enabled: bool) -> None:
        self._cfg.hover_preview_enabled = bool(enabled)
        save_config(self._cfg)
        self._hover_preview.set_enabled(bool(enabled))

    def _on_hover_preview_animate_changed(self, enabled: bool) -> None:
        self._cfg.hover_preview_animate = bool(enabled)
        save_config(self._cfg)
        self._hover_preview.set_animate(bool(enabled))

    def _on_minimize_to_tray_changed(self, enabled: bool) -> None:
        self._cfg.minimize_to_tray = bool(enabled)
        save_config(self._cfg)
        if self._tray is None:
            return
        if enabled:
            self._tray.show()
        else:
            self._tray.hide()
            # If the window was hidden via tray, surface it again so the user
            # isn't stranded with no taskbar entry and no tray icon.
            if not self.isVisible():
                self._show_from_tray()

    def _on_dark_theme_changed(self, enabled: bool) -> None:
        new_theme = "dark" if enabled else "light"
        if self._cfg.theme == new_theme:
            return
        self._cfg.theme = new_theme
        save_config(self._cfg)
        app = QApplication.instance()
        if isinstance(app, QApplication):
            apply_theme(app, new_theme)
        # Repaint views that use explicit theme-dependent colors.
        self._view.viewport().update()
        self._sidebar.viewport().update()

    def _on_log_panel_enabled_changed(self, enabled: bool) -> None:
        self._cfg.log_panel_enabled = bool(enabled)
        save_config(self._cfg)
        self._log_panel.setVisible(bool(enabled))

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        # Single-click on Windows = Trigger; double-click = DoubleClick.
        # Both restore — the context menu handles "Show" / "Quit" separately.
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self._show_from_tray()

    def _show_from_tray(self) -> None:
        # showNormal() also clears the WindowMinimized flag, which is required
        # since changeEvent() left the state as Minimized when it called hide().
        self.showNormal()
        self.activateWindow()
        self.raise_()

    def _on_sidebar_font_changed(self, points: int) -> None:
        self._cfg.sidebar_font_size = points
        save_config(self._cfg)
        self._sidebar.set_font_size(points)

    def _on_trash_days_changed(self, days: int) -> None:
        self._cfg.trash_auto_delete_days = days
        save_config(self._cfg)
        ws = self._folder_manager.workspace
        if ws is not None and days > 0:
            trash_svc.auto_purge(ws, days)
            self._sidebar.update_trash_count(trash_svc.trash_count(ws))

    def _on_empty_trash(self) -> None:
        ws = self._folder_manager.workspace
        if ws is None:
            return
        n = trash_svc.trash_count(ws)
        if not n:
            return
        if (
            QMessageBox.question(
                self, tr("dialog.confirm"), tr("dialog.empty_trash_body", n=n)
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        deleted = trash_svc.empty_trash(ws)
        self._sidebar.update_trash_count(trash_svc.trash_count(ws))
        if self._active_root is not None and self._active_root == trash_svc.trash_root(ws):
            self._activate_folder(self._active_root)  # refresh
        log.info("emptied trash: %d files", deleted)

    def _on_about(self) -> None:
        QMessageBox.about(
            self,
            tr("about.title"),
            tr("about.body", version=APP_VERSION, author=APP_AUTHOR, url=APP_HOMEPAGE),
        )

    # ---- thumbnail pipeline ----

    def _enqueue_thumbnail(self, key: ThumbKey, abs_path: Path) -> None:
        if key in self._inflight_keys:
            return
        self._inflight_keys.add(key)
        job = ThumbnailJob(key, abs_path, self._thumb_signals)
        self._pool.start(job)

    def _on_thumb_ready(self, key: ThumbKey, pm) -> None:
        self._cache.put(key, pm)
        self._inflight_keys.discard(key)
        for row, item in enumerate(self._model.items()):
            if item.kind is FileKind.DISK and item.rel_path == key.rel_path:
                idx = self._model.index(row)
                self._model.dataChanged.emit(idx, idx, [int(Qt.ItemDataRole.DecorationRole)])
                break

    def _on_thumb_failed(self, key: ThumbKey, err: str) -> None:
        log.warning("thumb failed: %s (%s)", key.rel_path, err)
        self._inflight_keys.discard(key)

    # ---- item activation ----

    def _on_item_double_clicked(self, item: FileItem) -> None:
        if self._active_root is None or item.kind is not FileKind.DISK:
            return
        abs_path = from_rel(self._active_root, item.rel_path)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(abs_path)))

    # ---- D&D into active grid ----

    def _on_drop_external_files_into_active(self, urls: list[str]) -> None:
        if self._active_root is None:
            return
        sources = [Path(u) for u in urls]
        db = self._db(self._active_root)
        result = import_files(sources, self._active_root, db)
        for item in result.imported:
            self._model.append_item(item)
        if result.failed:
            QMessageBox.warning(
                self, tr("dialog.import_error"),
                "\n".join(f"{p.name}: {err}" for p, err in result.failed[:10]),
            )
        self._cache.update_policy(db.count_files())
        self._refresh_folder_count(self._active_root)
        self._update_status()

    # ---- D&D onto sidebar ----

    def _on_drop_external_to_sidebar(self, dst_root: Path, urls: list[str]) -> None:
        # Drop external files onto a specific subfolder in the tree.
        sources = [Path(u) for u in urls]
        db = self._db(dst_root)
        result = import_files(sources, dst_root, db)
        if dst_root == self._active_root:
            for item in result.imported:
                self._model.append_item(item)
        if result.failed:
            QMessageBox.warning(
                self, tr("dialog.import_error"),
                "\n".join(f"{p.name}: {err}" for p, err in result.failed[:10]),
            )
        self._cache.update_policy(db.count_files())
        self._refresh_folder_count(dst_root)
        self._update_status()

    def _on_drop_to_sidebar(
        self, dst_root: Path, payload: bytes, mode_str: str = "move"
    ) -> None:
        try:
            refs = parse_payload(payload)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(
                self, tr("dialog.error"),
                tr("dialog.move_data_parse_failed", err=e),
            )
            return
        if not refs:
            return
        ws = self._folder_manager.workspace
        if ws is not None and dst_root.resolve() == trash_svc.trash_root(ws).resolve():
            # Drop on trash always means MOVE-to-trash regardless of modifier.
            self._move_refs_to_trash(refs)
            return

        mode = MoveMode.COPY if mode_str == "copy" else MoveMode.MOVE
        for r in {ref.src_root for ref in refs}:
            self._db(r)
        self._db(dst_root)

        title = tr("dialog.copying_files") if mode is MoveMode.COPY else tr("dialog.moving_files")
        progress = QProgressDialog(title, tr("dialog.cancel"), 0, len(refs), self)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(300)

        def cb(done: int, total: int) -> bool:
            del total
            progress.setValue(done)
            return not progress.wasCanceled()

        result: MoveResult = perform_move(
            refs, dst_root, db_for=self._db, cache=self._cache,
            mode=mode, progress_cb=cb,
        )
        progress.setValue(len(refs))

        if self._active_root is not None:
            active = self._active_root.resolve()
            if mode is MoveMode.MOVE:
                removed_rels = [
                    ref.src_rel for ref, _ in result.moved
                    if ref.src_root.resolve() == active
                ]
                if removed_rels:
                    self._model.remove_by_rels(removed_rels)
            if dst_root.resolve() == active:
                for _, new_item in result.moved:
                    self._model.append_item(new_item)
        if result.failed:
            QMessageBox.warning(
                self, tr("dialog.copy_move_error"),
                "\n".join(f"{ref.src_rel}: {err}" for ref, err in result.failed[:10]),
            )
        # Refresh affected sidebar nodes — destination always; sources only on MOVE.
        self._refresh_folder_count(dst_root)
        if mode is MoveMode.MOVE:
            for src in {ref.src_root for ref in refs}:
                self._refresh_folder_count(src)
        self._update_status()
        self._record_move_or_copy_undo(result.moved, dst_root, mode)

    def _move_refs_to_trash(self, refs: list[MoveItemRef]) -> None:
        ws = self._folder_manager.workspace
        if ws is None:
            return
        per_src: dict[Path, list[MoveItemRef]] = {}
        for r in refs:
            per_src.setdefault(r.src_root.resolve(), []).append(r)
        moved_total = 0
        all_trashed: list[trash_svc.TrashedItem] = []
        src_roots_seen: list[Path] = []
        for src_root, group in per_src.items():
            src_db = self._db(src_root)
            pairs = [(from_rel(src_root, r.src_rel), src_root) for r in group]
            moved = trash_svc.move_to_trash(ws, pairs)
            moved_origin_paths = {m.src_abs for m in moved}
            actually_moved_rels = [
                r.src_rel for r in group
                if from_rel(src_root, r.src_rel) in moved_origin_paths
            ]
            src_db.bulk_delete(actually_moved_rels)
            if self._active_root == src_root:
                self._model.remove_by_rels(actually_moved_rels)
            moved_total += len(actually_moved_rels)
            all_trashed.extend(moved)
            if moved:
                src_roots_seen.append(src_root)
            self._refresh_folder_count(src_root)
        self._sidebar.update_trash_count(trash_svc.trash_count(ws))
        if (
            self._active_root is not None
            and self._active_root == trash_svc.trash_root(ws)
        ):
            self._activate_folder(self._active_root)
        self._update_status()
        log.info("trashed %d items", moved_total)
        self._record_trash_undo(all_trashed, src_roots_seen)

    # ---- Clipboard paste ----

    def _on_paste_shortcut(self) -> None:
        if self._active_root is None:
            QMessageBox.information(
                self, tr("dialog.cannot_paste"),
                tr("dialog.select_managed_folder_first"),
            )
            return
        # Files on the clipboard (from Explorer cut/copy or our own
        # "ファイルをコピー") take priority over raw image data, mirroring
        # Explorer's Ctrl+V semantics.
        urls = file_urls_from_clipboard()
        if urls:
            self._on_drop_external_files_into_active([str(u) for u in urls])
            return
        if not self._clipboard.paste():
            log.debug("paste: clipboard had no image or files")

    def _on_pending_added(self, pending: PendingPaste) -> None:
        self._model.add_pending(pending)
        self._update_queue_label(self._paste_queue_qsize())

    def _on_paste_completed(self, pid: int, item: FileItem) -> None:
        self._model.replace_pending_with_real(pid, item)
        if self._active_root is not None:
            db = self._db(self._active_root)
            self._cache.update_policy(db.count_files())
            self._refresh_folder_count(self._active_root)
        self._update_status()

    def _on_paste_failed(self, pid: int, err: str) -> None:
        self._model.remove_pending(pid)
        QMessageBox.warning(
            self, tr("dialog.save_failed"),
            tr("dialog.save_failed_body", pid=pid, err=err),
        )

    def _on_backpressure(self, qlen: int) -> None:
        self._update_queue_label(qlen)

    def _update_queue_label(self, qlen: int) -> None:
        if qlen <= 0:
            self._queue_label.setText("")
        else:
            key = "status.queue_warning" if qlen > 200 else "status.queue"
            self._queue_label.setText(tr(key, n=qlen))

    def _paste_queue_qsize(self) -> int:
        return self._paste_queue._queue.qsize()  # noqa: SLF001

    # ---- Hover preview ----

    def _on_hover_changed(self, item: FileItem | None) -> None:
        if item is None or self._active_root is None or item.kind is not FileKind.DISK:
            self._hover_preview.cancel()
            return
        self._hover_preview.schedule(from_rel(self._active_root, item.rel_path))

    # ---- Rename / Delete ----

    def _on_rename_shortcut(self) -> None:
        idx = self._view.currentIndex()
        if not idx.isValid():
            return
        item = idx.data(ITEM_ROLE)
        if not isinstance(item, FileItem) or item.kind is not FileKind.DISK:
            return
        new_name, ok = QInputDialog.getText(
            self, tr("dialog.rename_file_title"),
            tr("dialog.rename_file_body"), text=item.name,
        )
        if not ok or not new_name or new_name == item.name:
            return
        self._do_rename(item, new_name)

    def _do_rename(self, item: FileItem, new_name: str) -> None:
        if self._active_root is None:
            return
        db = self._db(self._active_root)
        try:
            updated = rename_file(self._active_root, item, new_name, db)
        except (OSError, ValueError) as e:
            QMessageBox.warning(self, tr("dialog.rename_failed"), str(e))
            return
        self._model.update_item(item.rel_path, updated)

    def _on_delete_shortcut(self) -> None:
        if self._active_root is None:
            return
        sel = self._view.selectionModel().selectedIndexes()
        if not sel:
            return
        items: list[FileItem] = []
        for idx in sel:
            it = idx.data(ITEM_ROLE)
            if isinstance(it, FileItem) and it.kind is FileKind.DISK:
                items.append(it)
        if not items:
            return
        ws = self._folder_manager.workspace
        in_trash = ws is not None and self._active_root == trash_svc.trash_root(ws)
        if in_trash:
            # Permanent delete from trash
            if (
                QMessageBox.question(
                    self, tr("dialog.permanent_delete_title"),
                    tr("dialog.permanent_delete_body", n=len(items)),
                )
                != QMessageBox.StandardButton.Yes
            ):
                return
            for it in items:
                try:
                    from_rel(self._active_root, it.rel_path).unlink(missing_ok=True)
                except OSError as e:
                    log.warning("hard-delete failed: %s", e)
            db = self._db(self._active_root)
            db.bulk_delete([it.rel_path for it in items])
            self._model.remove_by_rels([it.rel_path for it in items])
            if ws is not None:
                self._sidebar.update_trash_count(trash_svc.trash_count(ws))
        else:
            # Soft delete -> trash (no confirmation; trash is recoverable)
            if ws is None:
                QMessageBox.warning(
                    self, tr("dialog.cannot_delete"),
                    tr("dialog.no_workspace_no_trash"),
                )
                return
            assert self._active_root is not None
            pairs = [(from_rel(self._active_root, it.rel_path), self._active_root) for it in items]
            moved = trash_svc.move_to_trash(ws, pairs)
            moved_origin_paths = {m.src_abs for m in moved}
            moved_rels = [
                it.rel_path for it, src_pair in zip(items, pairs)
                if src_pair[0] in moved_origin_paths
            ]
            db = self._db(self._active_root)
            db.bulk_delete(moved_rels)
            self._model.remove_by_rels(moved_rels)
            self._sidebar.update_trash_count(trash_svc.trash_count(ws))
            self._refresh_folder_count(self._active_root)
            self._record_trash_undo(moved, [self._active_root])
        self._update_status()

    # ---- Context menu ----

    def _on_context_menu(self, pos: QPoint) -> None:
        idx = self._view.indexAt(pos)
        item = idx.data(ITEM_ROLE) if idx.isValid() else None
        menu = QMenu(self)
        ws = self._folder_manager.workspace
        in_trash = (
            ws is not None
            and self._active_root is not None
            and self._active_root == trash_svc.trash_root(ws)
        )
        if isinstance(item, FileItem) and item.kind is FileKind.DISK and self._active_root:
            if in_trash:
                # Trash view: restore, hard-delete, open
                menu.addAction(QAction(tr("menu.restore_to_origin"), self,
                                        triggered=self._on_restore_selected))
                menu.addAction(QAction(tr("menu.open_with_default"), self,
                                        triggered=lambda: self._on_item_double_clicked(item)))
                menu.addAction(QAction(tr("menu.reveal_in_explorer"), self,
                                        triggered=lambda: self._reveal_in_explorer(item)))
                menu.addAction(QAction(tr("menu.permanent_delete"), self,
                                        triggered=self._on_delete_shortcut))
            else:
                menu.addAction(QAction(tr("menu.open_with_default"), self,
                                        triggered=lambda: self._on_item_double_clicked(item)))
                menu.addAction(QAction(tr("menu.reveal_in_explorer"), self,
                                        triggered=lambda: self._reveal_in_explorer(item)))
                menu.addSeparator()
                menu.addAction(QAction(tr("menu.copy_image"), self,
                                        triggered=self._on_copy_image_to_clipboard))
                menu.addAction(QAction(tr("menu.copy_files"), self,
                                        triggered=self._on_copy_files_to_clipboard))
                menu.addSeparator()
                menu.addAction(QAction(tr("menu.rename_file"), self,
                                        triggered=self._on_rename_shortcut))
                menu.addAction(QAction(tr("menu.delete_to_trash"), self,
                                        triggered=self._on_delete_shortcut))

                move_menu = menu.addMenu(tr("menu.move_to_folder"))
                copy_menu = menu.addMenu(tr("menu.copy_to_folder"))
                any_other = False
                for f in self._folder_manager.all_folders():
                    if f.resolve() == self._active_root.resolve():
                        continue
                    label = self._display_name_for(f)
                    act_m = QAction(label, self)
                    act_m.triggered.connect(
                        lambda _c=False, dst=f: self._move_selected_to(dst, MoveMode.MOVE)
                    )
                    move_menu.addAction(act_m)
                    act_c = QAction(label, self)
                    act_c.triggered.connect(
                        lambda _c=False, dst=f: self._move_selected_to(dst, MoveMode.COPY)
                    )
                    copy_menu.addAction(act_c)
                    any_other = True
                if not any_other:
                    move_menu.setEnabled(False)
                    copy_menu.setEnabled(False)
        else:
            menu.addAction(QAction(tr("menu.create_subfolder"), self,
                                    triggered=self._on_add_subfolder_clicked))
        menu.exec(self._view.viewport().mapToGlobal(pos))

    def _on_copy_image_to_clipboard(self) -> None:
        from PySide6.QtGui import QImage  # local import to keep top-level slim
        if self._active_root is None:
            return
        idx = self._view.currentIndex()
        item = idx.data(ITEM_ROLE) if idx.isValid() else None
        if not isinstance(item, FileItem) or item.kind is not FileKind.DISK:
            return
        path = from_rel(self._active_root, item.rel_path)
        qimg = QImage(str(path))
        if qimg.isNull():
            QMessageBox.warning(
                self, tr("dialog.copy_failed"),
                tr("dialog.image_load_failed", name=item.name),
            )
            return
        self._clipboard.note_self_copy(qimg)
        copy_image_to_clipboard(qimg)

    def _on_copy_files_to_clipboard(self) -> None:
        if self._active_root is None:
            return
        sel = self._view.selectionModel().selectedIndexes()
        paths: list[Path] = []
        for s in sel:
            it = s.data(ITEM_ROLE)
            if isinstance(it, FileItem) and it.kind is FileKind.DISK:
                paths.append(from_rel(self._active_root, it.rel_path))
        if not paths:
            return
        copy_files_to_clipboard(paths)

    def _on_restore_selected(self) -> None:
        ws = self._folder_manager.workspace
        if ws is None or self._active_root is None:
            return
        sel = self._view.selectionModel().selectedIndexes()
        basenames: list[str] = []
        for s in sel:
            it = s.data(ITEM_ROLE)
            if isinstance(it, FileItem) and it.kind is FileKind.DISK:
                basenames.append(it.name)
        if not basenames:
            return
        results = trash_svc.restore(ws, basenames)
        # Sync trash DB / model
        trash_db = self._db(self._active_root)
        ok_basenames = [b for b, r in zip(basenames, results) if r.error is None]
        trash_db.bulk_delete(ok_basenames)
        self._model.remove_by_rels(ok_basenames)
        # Sync destination DBs (so restored items show up if those folders are visible)
        restored_dst_folders: set[Path] = set()
        for r in results:
            if r.error is not None:
                continue
            dst_folder = (ws / r.origin_folder_rel) if r.origin_folder_rel else ws
            dst_db = self._db(dst_folder)
            new_item = FileItem.from_path(dst_folder, r.restored_abs)
            dst_db.upsert_file(new_item)
            if self._active_root == dst_folder.resolve():
                self._model.append_item(new_item)
            restored_dst_folders.add(dst_folder.resolve())
        for dst in restored_dst_folders:
            self._refresh_folder_count(dst)
        errs = [r for r in results if r.error]
        if errs:
            QMessageBox.warning(
                self, tr("dialog.partial_restore_failed"),
                "\n".join(f"{r.restored_abs.name}: {r.error}" for r in errs[:10]),
            )
        self._sidebar.update_trash_count(trash_svc.trash_count(ws))
        self._update_status()

    def _display_name_for(self, p: Path) -> str:
        ws = self._folder_manager.workspace
        if ws is None or p == ws:
            return p.name or str(p)
        try:
            return str(p.resolve().relative_to(ws.resolve())).replace("\\", "/")
        except ValueError:
            return p.name

    def _reveal_in_explorer(self, item: FileItem) -> None:
        if self._active_root is None:
            return
        p = from_rel(self._active_root, item.rel_path)
        if p.exists():
            os.startfile(p.parent)  # type: ignore[attr-defined]

    def _move_selected_to(self, dst_root: Path, mode: MoveMode = MoveMode.MOVE) -> None:
        if self._active_root is None:
            return
        sel = self._view.selectionModel().selectedIndexes()
        items: list[FileItem] = []
        for idx in sel:
            it = idx.data(ITEM_ROLE)
            if isinstance(it, FileItem) and it.kind is FileKind.DISK:
                items.append(it)
        if not items:
            return
        refs = [MoveItemRef(src_root=self._active_root, src_rel=it.rel_path) for it in items]
        payload = json.dumps(
            [{"root": str(r.src_root), "rel": r.src_rel} for r in refs],
            ensure_ascii=False,
        ).encode("utf-8")
        self._on_drop_to_sidebar(dst_root, payload, mode_str=mode.value)

    # ---- misc ----

    def _update_status(self) -> None:
        if self._active_root is None:
            self._status_label.setText(tr("status.no_workspace"))
            return
        db = self._db(self._active_root)
        n = db.count_files()
        policy = self._cache.policy.value
        self._status_label.setText(
            tr(
                "status.folder_summary",
                name=self._display_name_for(self._active_root),
                n=n,
                policy=policy,
            )
        )

    # ---- Log + Undo/Redo ----

    def _folder_log_label(self, p: Path) -> str:
        """Display label for a folder in log strings (workspace-relative)."""
        ws = self._folder_manager.workspace
        if ws is None:
            return p.name or str(p)
        try:
            rel = p.resolve().relative_to(ws.resolve())
        except ValueError:
            return p.name or str(p)
        rel_str = str(rel).replace("\\", "/")
        if rel_str in ("", "."):
            # The workspace root itself has no name in a "FolderA → FolderB"
            # sentence; surface it as "(workspace)" instead.
            return tr("log.workspace_root")
        return rel_str

    def _log(self, message: str) -> None:
        """Append a one-line entry to the log panel."""
        if not message:
            return
        self._log_panel.append(message)

    def _record_move_or_copy_undo(
        self,
        moved: list[tuple[MoveItemRef, FileItem]],
        dst_root: Path,
        mode: MoveMode,
    ) -> None:
        """Record an undo entry for a successful move/copy and log it.

        Skips recording undo (but still logs) when sources span multiple
        managed folders — reversing a multi-source op needs per-source dst
        bookkeeping that the single-entry model can't express cleanly.
        """
        if not moved:
            return
        src_roots = {ref.src_root.resolve() for ref, _ in moved}
        dst_resolved = dst_root.resolve()
        # Pick a label for the source side (use the only src or a fallback).
        if len(src_roots) == 1:
            src_root_single = next(iter(src_roots))
            src_label = self._folder_log_label(src_root_single)
        else:
            src_root_single = None
            src_label = "(multiple)"
        dst_label = self._folder_log_label(dst_root)
        n = len(moved)

        key = "log.copy" if mode is MoveMode.COPY else "log.move"
        self._log(tr(key, src=src_label, dst=dst_label, n=n))

        if src_root_single is None:
            # Cannot encode multi-source op as a single undo entry; drop history.
            self._undo_mgr.clear()
            return
        pairs = [(ref.src_rel, new_item.rel_path) for ref, new_item in moved]
        self._undo_mgr.record(UndoEntry(
            kind=UndoKind.COPY if mode is MoveMode.COPY else UndoKind.MOVE,
            src_label=src_label, dst_label=dst_label,
            src_root=src_root_single, dst_root=dst_resolved,
            pairs=pairs,
        ))

    def _record_trash_undo(
        self,
        trashed: list[trash_svc.TrashedItem],
        src_roots_seen: list[Path],
    ) -> None:
        """Record an undo entry for a successful trash op and log it."""
        if not trashed:
            return
        ws = self._folder_manager.workspace
        if ws is None:
            return
        unique_src = {p.resolve() for p in src_roots_seen}
        if len(unique_src) == 1:
            src_label = self._folder_log_label(next(iter(unique_src)))
        elif len(unique_src) > 1:
            src_label = "(multiple)"
        else:
            src_label = ""
        n = len(trashed)
        self._log(tr("log.trash_op", src=src_label, n=n))

        self._undo_mgr.record(UndoEntry(
            kind=UndoKind.TRASH,
            src_label=src_label, dst_label=tr("log.trash"),
            workspace=ws.resolve(),
            trashed_basenames=[m.trashed_abs.name for m in trashed],
        ))

    def _on_undo_shortcut(self) -> None:
        entry = self._undo_mgr.peek_undo()
        if entry is None:
            self._log(tr("log.nothing_to_undo"))
            return
        try:
            if entry.kind is UndoKind.MOVE:
                redo_entry = self._undo_move(entry)
            elif entry.kind is UndoKind.COPY:
                redo_entry = self._undo_copy(entry)
            else:
                redo_entry = self._undo_trash(entry)
        except Exception as e:  # noqa: BLE001
            log.exception("undo failed")
            self._log(tr("log.undo_failed", err=e))
            return
        if redo_entry is None:
            return
        # Move the entry from undo → redo only on success.
        self._undo_mgr.take_undo()
        self._undo_mgr.push_redo(redo_entry)

    def _on_redo_shortcut(self) -> None:
        entry = self._undo_mgr.peek_redo()
        if entry is None:
            self._log(tr("log.nothing_to_redo"))
            return
        try:
            if entry.kind is UndoKind.MOVE:
                undo_entry = self._redo_move(entry)
            elif entry.kind is UndoKind.COPY:
                undo_entry = self._redo_copy(entry)
            else:
                undo_entry = self._redo_trash(entry)
        except Exception as e:  # noqa: BLE001
            log.exception("redo failed")
            self._log(tr("log.redo_failed", err=e))
            return
        if undo_entry is None:
            return
        self._undo_mgr.take_redo()
        self._undo_mgr.push_undo(undo_entry)

    # ---- inverse operations ----

    def _undo_move(self, entry: UndoEntry) -> UndoEntry | None:
        """Move files at dst_root back to src_root. Returns redo entry."""
        assert entry.src_root is not None and entry.dst_root is not None
        refs = [MoveItemRef(src_root=entry.dst_root, src_rel=dst_rel)
                for _, dst_rel in entry.pairs]
        result = self._perform_move_silently(refs, entry.src_root, MoveMode.MOVE)
        n = len(result.moved)
        if n == 0:
            return None
        # Build redo entry: when "redone", we want to move the files (now back
        # at src_root) forward to dst_root again. Track each file's current rel
        # under src_root so the redo refs are accurate.
        redo_pairs: list[tuple[str, str]] = []
        for (_orig_src_rel, _orig_dst_rel), (_ref, new_item) in zip(entry.pairs, result.moved):
            redo_pairs.append((new_item.rel_path, _orig_dst_rel))
        self._log(tr(
            "log.undo_move",
            src=entry.src_label, dst=entry.dst_label, n=n,
        ))
        return UndoEntry(
            kind=UndoKind.MOVE,
            src_label=entry.src_label, dst_label=entry.dst_label,
            src_root=entry.src_root, dst_root=entry.dst_root,
            pairs=redo_pairs,
        )

    def _redo_move(self, entry: UndoEntry) -> UndoEntry | None:
        """Re-apply a move from src_root to dst_root. Returns undo entry."""
        assert entry.src_root is not None and entry.dst_root is not None
        refs = [MoveItemRef(src_root=entry.src_root, src_rel=src_rel)
                for src_rel, _ in entry.pairs]
        result = self._perform_move_silently(refs, entry.dst_root, MoveMode.MOVE)
        n = len(result.moved)
        if n == 0:
            return None
        new_pairs: list[tuple[str, str]] = []
        for (orig_src_rel, _), (_ref, new_item) in zip(entry.pairs, result.moved):
            new_pairs.append((orig_src_rel, new_item.rel_path))
        self._log(tr(
            "log.redo_move",
            src=entry.src_label, dst=entry.dst_label, n=n,
        ))
        return UndoEntry(
            kind=UndoKind.MOVE,
            src_label=entry.src_label, dst_label=entry.dst_label,
            src_root=entry.src_root, dst_root=entry.dst_root,
            pairs=new_pairs,
        )

    def _undo_copy(self, entry: UndoEntry) -> UndoEntry | None:
        """Trash the copies at dst_root after user confirmation. Returns redo entry."""
        assert entry.src_root is not None and entry.dst_root is not None
        ws = self._folder_manager.workspace
        if ws is None:
            QMessageBox.warning(
                self, tr("dialog.cannot_delete"),
                tr("dialog.no_workspace_no_trash"),
            )
            return None
        n = len(entry.pairs)
        if (
            QMessageBox.question(
                self, tr("dialog.confirm_undo_copy_title"),
                tr("dialog.confirm_undo_copy_body", dst=entry.dst_label, n=n),
            )
            != QMessageBox.StandardButton.Yes
        ):
            return None
        dst_db = self._db(entry.dst_root)
        pairs_to_trash = [
            (from_rel(entry.dst_root, dst_rel), entry.dst_root)
            for _, dst_rel in entry.pairs
        ]
        moved = trash_svc.move_to_trash(ws, pairs_to_trash)
        moved_origin_paths = {m.src_abs for m in moved}
        trashed_dst_rels = [
            dst_rel for (_, dst_rel), (file_abs, _) in zip(entry.pairs, pairs_to_trash)
            if file_abs in moved_origin_paths
        ]
        dst_db.bulk_delete(trashed_dst_rels)
        if self._active_root == entry.dst_root:
            self._model.remove_by_rels(trashed_dst_rels)
        self._sidebar.update_trash_count(trash_svc.trash_count(ws))
        self._refresh_folder_count(entry.dst_root)
        if (
            self._active_root is not None
            and self._active_root == trash_svc.trash_root(ws)
        ):
            self._activate_folder(self._active_root)
        n_ok = len(trashed_dst_rels)
        if n_ok == 0:
            return None
        self._log(tr(
            "log.undo_copy", dst=entry.dst_label, n=n_ok,
        ))
        # Redo: re-copy the same originals (still present at src_root) to dst_root.
        kept_pairs = [
            (src_rel, dst_rel) for (src_rel, dst_rel), (file_abs, _)
            in zip(entry.pairs, pairs_to_trash)
            if file_abs in moved_origin_paths
        ]
        return UndoEntry(
            kind=UndoKind.COPY,
            src_label=entry.src_label, dst_label=entry.dst_label,
            src_root=entry.src_root, dst_root=entry.dst_root,
            pairs=kept_pairs,
        )

    def _redo_copy(self, entry: UndoEntry) -> UndoEntry | None:
        """Re-execute a copy from src_root to dst_root. Returns undo entry."""
        assert entry.src_root is not None and entry.dst_root is not None
        refs = [MoveItemRef(src_root=entry.src_root, src_rel=src_rel)
                for src_rel, _ in entry.pairs]
        result = self._perform_move_silently(refs, entry.dst_root, MoveMode.COPY)
        n = len(result.moved)
        if n == 0:
            return None
        new_pairs: list[tuple[str, str]] = []
        for (orig_src_rel, _), (_ref, new_item) in zip(entry.pairs, result.moved):
            new_pairs.append((orig_src_rel, new_item.rel_path))
        self._log(tr(
            "log.redo_copy",
            src=entry.src_label, dst=entry.dst_label, n=n,
        ))
        return UndoEntry(
            kind=UndoKind.COPY,
            src_label=entry.src_label, dst_label=entry.dst_label,
            src_root=entry.src_root, dst_root=entry.dst_root,
            pairs=new_pairs,
        )

    def _undo_trash(self, entry: UndoEntry) -> UndoEntry | None:
        """Restore files from trash to their original folders. Returns redo entry."""
        ws = entry.workspace
        if ws is None or not ws.exists():
            QMessageBox.warning(
                self, tr("dialog.undo_trash_no_workspace_title"),
                tr("dialog.undo_trash_no_workspace_body"),
            )
            return None
        basenames = list(entry.trashed_basenames)
        if not basenames:
            return None
        results = trash_svc.restore(ws, basenames)
        ok_results = [r for r in results if r.error is None]
        err_results = [r for r in results if r.error is not None]
        if not ok_results:
            detail = "\n".join(f"{r.restored_abs.name}: {r.error}" for r in err_results[:10])
            QMessageBox.warning(
                self, tr("dialog.undo_trash_failed_title"),
                tr("dialog.undo_trash_failed_body", detail=detail),
            )
            return None

        # Mirror restore side-effects from _on_restore_selected.
        troot = trash_svc.trash_root(ws)
        if self._active_root is not None and self._active_root == troot:
            trash_db = self._db(self._active_root)
            ok_basenames = [b for b, r in zip(basenames, results) if r.error is None]
            trash_db.bulk_delete(ok_basenames)
            self._model.remove_by_rels(ok_basenames)

        restored_dst_folders: set[Path] = set()
        redo_sources: list[tuple[Path, Path]] = []
        for r in ok_results:
            dst_folder = (ws / r.origin_folder_rel) if r.origin_folder_rel else ws
            dst_db = self._db(dst_folder)
            new_item = FileItem.from_path(dst_folder, r.restored_abs)
            dst_db.upsert_file(new_item)
            if self._active_root == dst_folder.resolve():
                self._model.append_item(new_item)
            restored_dst_folders.add(dst_folder.resolve())
            redo_sources.append((r.restored_abs, dst_folder.resolve()))
        for dst in restored_dst_folders:
            self._refresh_folder_count(dst)
        self._sidebar.update_trash_count(trash_svc.trash_count(ws))
        self._update_status()

        if err_results:
            detail = "\n".join(f"{r.restored_abs.name}: {r.error}" for r in err_results[:10])
            QMessageBox.warning(
                self, tr("dialog.undo_trash_failed_title"),
                tr("dialog.undo_trash_failed_body", detail=detail),
            )

        n = len(ok_results)
        self._log(tr("log.undo_trash", src=entry.src_label, n=n))
        # Redo trash entry holds the current paths to be re-trashed.
        return UndoEntry(
            kind=UndoKind.TRASH,
            src_label=entry.src_label, dst_label=entry.dst_label,
            workspace=ws,
            trash_sources=redo_sources,
        )

    def _redo_trash(self, entry: UndoEntry) -> UndoEntry | None:
        """Re-trash the files that a prior undo restored. Returns undo entry."""
        ws = entry.workspace
        if ws is None or not entry.trash_sources:
            return None
        moved = trash_svc.move_to_trash(ws, entry.trash_sources)
        if not moved:
            return None
        moved_origin_paths = {m.src_abs for m in moved}
        # Update each src DB (delete the rel) and mirror in the active model.
        per_src: dict[Path, list[tuple[Path, Path]]] = {}
        for file_abs, src_root in entry.trash_sources:
            per_src.setdefault(src_root, []).append((file_abs, src_root))
        src_roots_seen: list[Path] = []
        for src_root, items in per_src.items():
            src_db = self._db(src_root)
            rels_to_delete: list[str] = []
            for file_abs, _ in items:
                if file_abs not in moved_origin_paths:
                    continue
                try:
                    rel = normalize_rel(file_abs.relative_to(src_root))
                except ValueError:
                    continue
                rels_to_delete.append(rel)
            if rels_to_delete:
                src_db.bulk_delete(rels_to_delete)
                if self._active_root == src_root.resolve():
                    self._model.remove_by_rels(rels_to_delete)
                src_roots_seen.append(src_root)
                self._refresh_folder_count(src_root)
        self._sidebar.update_trash_count(trash_svc.trash_count(ws))
        if (
            self._active_root is not None
            and self._active_root == trash_svc.trash_root(ws)
        ):
            self._activate_folder(self._active_root)
        self._update_status()
        n = len(moved)
        self._log(tr("log.redo_trash", src=entry.src_label, n=n))
        return UndoEntry(
            kind=UndoKind.TRASH,
            src_label=entry.src_label, dst_label=entry.dst_label,
            workspace=ws,
            trashed_basenames=[m.trashed_abs.name for m in moved],
        )

    def _perform_move_silently(
        self,
        refs: list[MoveItemRef],
        dst_root: Path,
        mode: MoveMode,
    ) -> MoveResult:
        """Run perform_move + update DBs/model, without a progress dialog.

        Used by undo/redo paths where the user already saw the original op.
        Mirrors the bookkeeping in _on_drop_to_sidebar but without the dialog
        and without recording another undo entry.
        """
        for r in {ref.src_root for ref in refs}:
            self._db(r)
        self._db(dst_root)
        result = perform_move(
            refs, dst_root, db_for=self._db, cache=self._cache, mode=mode,
        )
        if self._active_root is not None:
            active = self._active_root.resolve()
            if mode is MoveMode.MOVE:
                removed_rels = [
                    ref.src_rel for ref, _ in result.moved
                    if ref.src_root.resolve() == active
                ]
                if removed_rels:
                    self._model.remove_by_rels(removed_rels)
            if dst_root.resolve() == active:
                for _, new_item in result.moved:
                    self._model.append_item(new_item)
        self._refresh_folder_count(dst_root)
        if mode is MoveMode.MOVE:
            for src in {ref.src_root for ref in refs}:
                self._refresh_folder_count(src)
        self._update_status()
        return result

    def changeEvent(self, e) -> None:
        # Hide-to-tray trigger. We watch WindowStateChange and divert minimize
        # via QTimer.singleShot(0, self.hide) — calling hide() directly inside
        # changeEvent confuses Qt's window state bookkeeping on Windows.
        if (
            e.type() == QEvent.Type.WindowStateChange
            and self._tray is not None
            and self._cfg.minimize_to_tray
            and self.isMinimized()
        ):
            QTimer.singleShot(0, self.hide)
        super().changeEvent(e)

    def closeEvent(self, e) -> None:
        if self._tray is not None:
            self._tray.hide()
        self._paste_queue.stop()
        for db in self._dbs.values():
            db.close()
        self._dbs.clear()
        save_config(self._cfg)
        super().closeEvent(e)
