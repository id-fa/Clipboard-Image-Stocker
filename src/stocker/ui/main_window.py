"""Main application window: ties together sidebar, toolbar, grid, and services."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from PySide6.QtCore import QPoint, Qt, QThreadPool, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QFileDialog,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressDialog,
    QSplitter,
    QStatusBar,
)

from stocker.config import AppConfig, save_config
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
from stocker.core.scanner import scan_folder
from stocker.core.thumbnail_cache import ThumbnailCache
from stocker.core.thumbnail_worker import ThumbnailJob, ThumbnailSignals
from stocker.core import trash as trash_svc
from stocker.db.metadata_db import MetadataDB
from stocker.ui.hover_preview import HoverPreviewWindow
from stocker.ui.sidebar import Sidebar
from stocker.ui.thumbnail_delegate import ThumbnailDelegate
from stocker.ui.thumbnail_model import ITEM_ROLE, ThumbnailModel
from stocker.ui.thumbnail_view import ThumbnailView
from stocker.ui.toolbar import StockerToolbar
from stocker.utils.clipboard_files import (
    copy_files_to_clipboard,
    copy_image_to_clipboard,
    file_urls_from_clipboard,
)
from stocker.utils.paths import from_rel

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
        self._toolbar.set_sort(cfg.sort_key, cfg.sort_dir)
        self._toolbar.set_paste_format(cfg.paste_format)
        self._toolbar.set_autocapture(cfg.clipboard_autocapture)
        self._toolbar.set_hover_preview_enabled(cfg.hover_preview_enabled)
        self._toolbar.set_font_size(cfg.sidebar_font_size)
        self._toolbar.set_trash_days(cfg.trash_auto_delete_days)
        self._toolbar.blockSignals(False)
        self._toolbar.set_workspace_requested.connect(self._on_set_workspace)
        self._toolbar.add_subfolder_requested.connect(self._on_add_subfolder_clicked)
        self._toolbar.columns_changed.connect(self._on_columns_changed)
        self._toolbar.sort_changed.connect(self._on_sort_changed)
        self._toolbar.paste_format_changed.connect(self._on_paste_format_changed)
        self._toolbar.clipboard_autocapture_changed.connect(self._on_autocapture_changed)
        self._toolbar.hover_preview_enabled_changed.connect(self._on_hover_preview_enabled_changed)
        self._toolbar.sidebar_font_size_changed.connect(self._on_sidebar_font_changed)
        self._toolbar.trash_days_changed.connect(self._on_trash_days_changed)
        self._toolbar.empty_trash_requested.connect(self._on_empty_trash)

        # Center: splitter
        self._splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.setCentralWidget(self._splitter)

        # Sidebar
        self._sidebar = Sidebar(self)
        self._sidebar.set_font_size(cfg.sidebar_font_size)
        self._sidebar.folder_selected.connect(self._on_folder_selected)
        self._sidebar.trash_selected.connect(self._on_trash_selected)
        self._sidebar.create_subfolder_requested.connect(self._on_create_subfolder_under)
        self._sidebar.drop_stocker_items_to_folder.connect(self._on_drop_to_sidebar)
        self._sidebar.drop_external_files_to_folder.connect(self._on_drop_external_to_sidebar)
        self._splitter.addWidget(self._sidebar)

        # Thumbnail grid
        self._model = ThumbnailModel(self)
        self._model.set_cache_lookup(self._cache.get)
        self._model.request_thumbnail.connect(self._enqueue_thumbnail)
        self._view = ThumbnailView(self)
        self._view.setModel(self._model)
        self._view.setItemDelegate(ThumbnailDelegate(self))
        self._view.set_columns(cfg.columns)
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

        # Status bar
        self.setStatusBar(QStatusBar(self))
        self._status_label = QLabel("", self)
        self._queue_label = QLabel("", self)
        self.statusBar().addWidget(self._status_label, 1)
        self.statusBar().addPermanentWidget(self._queue_label)

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
        msg.setWindowTitle("ワークスペース選択")
        msg.setText(
            "画像を蓄積するワークスペース基点フォルダを選択してください。\n"
            "今後追加するサブフォルダはこの配下に作成されます。"
        )
        msg.setStandardButtons(
            QMessageBox.StandardButton.Open | QMessageBox.StandardButton.Cancel
        )
        if msg.exec() != QMessageBox.StandardButton.Open:
            return
        d = QFileDialog.getExistingDirectory(self, "ワークスペース基点フォルダを選択")
        if d:
            try:
                self._folder_manager.set_workspace(Path(d))
            except ValueError as e:
                QMessageBox.warning(self, "エラー", str(e))

    def _on_set_workspace(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "ワークスペース基点フォルダを選択")
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
            QMessageBox.warning(self, "エラー", str(e))
            return
        self._refresh_sidebar()
        ws = self._folder_manager.workspace
        if ws is not None:
            self._activate_folder(ws)

    def _on_add_subfolder_clicked(self) -> None:
        if not self._folder_manager.has_workspace():
            QMessageBox.information(self, "未設定", "先にワークスペースを設定してください。")
            return
        parent = self._active_root or self._folder_manager.workspace
        self._on_create_subfolder_under(parent)

    def _on_create_subfolder_under(self, parent: Path | None) -> None:
        if not self._folder_manager.has_workspace():
            return
        parent = parent or self._folder_manager.workspace
        name, ok = QInputDialog.getText(
            self, "サブフォルダを作成",
            f"親フォルダ: {parent.name}\n新しいフォルダ名:",
        )
        if not ok or not name.strip():
            return
        try:
            new_path = self._folder_manager.create_subfolder(name.strip(), parent=parent)
        except ValueError as e:
            QMessageBox.warning(self, "作成失敗", str(e))
            return
        self._refresh_sidebar()
        self._activate_folder(new_path)

    def _refresh_sidebar(self) -> None:
        ws = self._folder_manager.workspace
        folders = self._folder_manager.all_folders()
        n_trash = trash_svc.trash_count(ws) if ws else 0
        self._sidebar.populate(ws, folders, trash_count=n_trash)
        if self._active_root is not None:
            self._sidebar.select_path(self._active_root)

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
        self._update_status()

    # ---- toolbar handlers ----

    def _on_columns_changed(self, n: int) -> None:
        self._view.set_columns(n)
        self._cfg.columns = n
        save_config(self._cfg)

    def _on_sort_changed(self, key: str, direction: str) -> None:
        self._cfg.sort_key = key
        self._cfg.sort_dir = direction
        save_config(self._cfg)
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
                self, "確認", f"ごみ箱内の {n} 件を完全に削除します。よろしいですか？"
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        deleted = trash_svc.empty_trash(ws)
        self._sidebar.update_trash_count(trash_svc.trash_count(ws))
        if self._active_root is not None and self._active_root == trash_svc.trash_root(ws):
            self._activate_folder(self._active_root)  # refresh
        log.info("emptied trash: %d files", deleted)

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
                self, "取り込みエラー",
                "\n".join(f"{p.name}: {err}" for p, err in result.failed[:10]),
            )
        self._cache.update_policy(db.count_files())
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
                self, "取り込みエラー",
                "\n".join(f"{p.name}: {err}" for p, err in result.failed[:10]),
            )
        self._cache.update_policy(db.count_files())
        self._update_status()

    def _on_drop_to_sidebar(
        self, dst_root: Path, payload: bytes, mode_str: str = "move"
    ) -> None:
        try:
            refs = parse_payload(payload)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "エラー", f"移動データの解析に失敗: {e}")
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

        title = "ファイルコピー中..." if mode is MoveMode.COPY else "ファイル移動中..."
        progress = QProgressDialog(title, "キャンセル", 0, len(refs), self)
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
                self, "コピー/移動エラー",
                "\n".join(f"{ref.src_rel}: {err}" for ref, err in result.failed[:10]),
            )
        self._update_status()

    def _move_refs_to_trash(self, refs: list[MoveItemRef]) -> None:
        ws = self._folder_manager.workspace
        if ws is None:
            return
        per_src: dict[Path, list[MoveItemRef]] = {}
        for r in refs:
            per_src.setdefault(r.src_root.resolve(), []).append(r)
        moved_total = 0
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
        self._sidebar.update_trash_count(trash_svc.trash_count(ws))
        if (
            self._active_root is not None
            and self._active_root == trash_svc.trash_root(ws)
        ):
            self._activate_folder(self._active_root)
        self._update_status()
        log.info("trashed %d items", moved_total)

    # ---- Clipboard paste ----

    def _on_paste_shortcut(self) -> None:
        if self._active_root is None:
            QMessageBox.information(self, "貼り付け不可", "まず管理フォルダを選択してください。")
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
        self._update_status()

    def _on_paste_failed(self, pid: int, err: str) -> None:
        self._model.remove_pending(pid)
        QMessageBox.warning(self, "保存に失敗", f"#{pid}: {err}")

    def _on_backpressure(self, qlen: int) -> None:
        self._update_queue_label(qlen)

    def _update_queue_label(self, qlen: int) -> None:
        if qlen <= 0:
            self._queue_label.setText("")
        else:
            warn = " ⚠" if qlen > 200 else ""
            self._queue_label.setText(f"保存待ち: {qlen}{warn}")

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
            self, "名前を変更", "新しいファイル名:", text=item.name
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
            QMessageBox.warning(self, "リネーム失敗", str(e))
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
                    self, "完全削除",
                    f"ごみ箱内の {len(items)} 件を完全削除します。元に戻せません。",
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
                    self, "削除不可",
                    "ワークスペースが未設定のためごみ箱が使えません。",
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
                menu.addAction(QAction("削除元へ復元", self,
                                        triggered=self._on_restore_selected))
                menu.addAction(QAction("関連付けで開く", self,
                                        triggered=lambda: self._on_item_double_clicked(item)))
                menu.addAction(QAction("エクスプローラで開く", self,
                                        triggered=lambda: self._reveal_in_explorer(item)))
                menu.addAction(QAction("完全に削除", self,
                                        triggered=self._on_delete_shortcut))
            else:
                menu.addAction(QAction("関連付けで開く", self,
                                        triggered=lambda: self._on_item_double_clicked(item)))
                menu.addAction(QAction("エクスプローラで開く", self,
                                        triggered=lambda: self._reveal_in_explorer(item)))
                menu.addSeparator()
                menu.addAction(QAction("画像をコピー", self,
                                        triggered=self._on_copy_image_to_clipboard))
                menu.addAction(QAction("Ctrl+C ファイルをコピー", self,
                                        triggered=self._on_copy_files_to_clipboard))
                menu.addSeparator()
                menu.addAction(QAction("F2 名前を変更", self,
                                        triggered=self._on_rename_shortcut))
                menu.addAction(QAction("削除（ごみ箱へ）", self,
                                        triggered=self._on_delete_shortcut))

                move_menu = menu.addMenu("別フォルダへ移動 →")
                copy_menu = menu.addMenu("別フォルダへコピー →")
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
            menu.addAction(QAction("サブフォルダを作成", self,
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
            QMessageBox.warning(self, "コピー失敗", f"画像を読み込めませんでした: {item.name}")
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
        for r in results:
            if r.error is not None:
                continue
            dst_folder = (ws / r.origin_folder_rel) if r.origin_folder_rel else ws
            dst_db = self._db(dst_folder)
            new_item = FileItem.from_path(dst_folder, r.restored_abs)
            dst_db.upsert_file(new_item)
            if self._active_root == dst_folder.resolve():
                self._model.append_item(new_item)
        errs = [r for r in results if r.error]
        if errs:
            QMessageBox.warning(
                self, "一部復元失敗",
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
            self._status_label.setText("（ワークスペース未設定）")
            return
        db = self._db(self._active_root)
        n = db.count_files()
        policy = self._cache.policy.value
        self._status_label.setText(
            f"{self._display_name_for(self._active_root)}: {n} 件  /  サムネ: {policy}"
        )

    def closeEvent(self, e) -> None:
        self._paste_queue.stop()
        for db in self._dbs.values():
            db.close()
        self._dbs.clear()
        save_config(self._cfg)
        super().closeEvent(e)
