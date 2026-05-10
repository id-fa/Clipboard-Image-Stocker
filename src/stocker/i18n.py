"""Lightweight i18n: dict catalog + tr() + QLocale-based detection.

Translations are stored inline in ``_CATALOG`` (no .ts/.qm or .po/.mo files).
At startup ``main`` calls ``set_language(detect_language())`` which picks
``"ja"`` on Japanese OS locales and ``"en"`` everywhere else.

Usage::

    from stocker.i18n import tr
    label.setText(tr("toolbar.workspace"))
    msg.setText(tr("dialog.create_subfolder_body", parent=parent.name))

Missing keys fall through to the key string itself, which makes
untranslated strings visible during development.
"""

from __future__ import annotations

from typing import Literal

LangCode = Literal["ja", "en"]
DEFAULT_LANG: LangCode = "en"

_lang: LangCode = DEFAULT_LANG


def detect_language() -> LangCode:
    """Pick "ja" on Japanese OS locales, "en" everywhere else."""
    try:
        from PySide6.QtCore import QLocale
        if QLocale.system().language() == QLocale.Language.Japanese:
            return "ja"
    except Exception:  # noqa: BLE001
        pass
    return "en"


def set_language(lang: str) -> None:
    """Override the active language. Unknown codes fall back to DEFAULT_LANG."""
    global _lang
    _lang = lang if lang in ("ja", "en") else DEFAULT_LANG  # type: ignore[assignment]


def get_language() -> LangCode:
    return _lang


def tr(key: str, **fmt: object) -> str:
    """Return the translation for ``key`` in the active language.

    Falls back: active lang → DEFAULT_LANG → "ja" → key itself.
    Format kwargs are applied via ``str.format()``.
    """
    entry = _CATALOG.get(key)
    if entry is None:
        return key.format(**fmt) if fmt else key
    text = entry.get(_lang) or entry.get(DEFAULT_LANG) or entry.get("ja") or key
    return text.format(**fmt) if fmt else text


_CATALOG: dict[str, dict[str, str]] = {
    # ---- toolbar ----
    "toolbar.workspace": {
        "ja": "ワークスペース...",
        "en": "Workspace...",
    },
    "toolbar.add_subfolder": {
        "ja": "サブフォルダを追加",
        "en": "Add subfolder",
    },
    "toolbar.columns_label": {"ja": " 列数: ", "en": " Columns: "},
    "toolbar.aspect_label": {"ja": " 比率: ", "en": " Aspect: "},
    "toolbar.aspect_tooltip": {
        "ja": "サムネイルセルのアスペクト比。すべての画像が同じ比率なら隙間なく敷き詰められます。",
        "en": "Thumbnail cell aspect ratio. Images sharing this ratio tile without gaps.",
    },
    "toolbar.filter_label": {"ja": " 絞り込み: ", "en": " Filter: "},
    "toolbar.filter_placeholder": {"ja": "ファイル名", "en": "File name"},
    "toolbar.filter_tooltip": {
        "ja": "ファイル名で絞り込み (現在のフォルダのみ。サブフォルダは含みません)",
        "en": "Filter by file name (current folder only — subfolders are not searched)",
    },
    "toolbar.sort_label": {"ja": " 並び順: ", "en": " Sort: "},
    "toolbar.sort_name": {"ja": "ファイル名", "en": "Name"},
    "toolbar.sort_mtime": {"ja": "更新日時", "en": "Modified"},
    "toolbar.sort_added": {"ja": "追加日時", "en": "Added"},
    "toolbar.sort_asc": {"ja": "昇順", "en": "Ascending"},
    "toolbar.sort_desc": {"ja": "降順", "en": "Descending"},
    "toolbar.paste_format_label": {
        "ja": " 貼り付け形式: ",
        "en": " Paste format: ",
    },
    "toolbar.autocapture": {"ja": "自動取込", "en": "Auto-capture"},
    "toolbar.autocapture_tooltip": {
        "ja": "クリップボードに新しい画像が来たら自動的に現在のフォルダへ保存します",
        "en": "Automatically save new clipboard images to the current folder",
    },
    "toolbar.hover_preview": {"ja": "ホバー拡大", "en": "Hover preview"},
    "toolbar.hover_preview_tooltip": {
        "ja": "サムネイル上で停止すると拡大プレビューを表示します",
        "en": "Show an enlarged preview when the cursor pauses on a thumbnail",
    },
    "toolbar.hover_animate": {"ja": "アニメ再生", "en": "Animate"},
    "toolbar.hover_animate_tooltip": {
        "ja": "拡大プレビューでアニメ GIF / WebP を再生します",
        "en": "Play animated GIF / WebP in the hover preview",
    },
    "toolbar.minimize_to_tray": {
        "ja": "最小化でトレイに格納",
        "en": "Minimize to tray",
    },
    "toolbar.minimize_to_tray_tooltip": {
        "ja": "最小化したときにウィンドウをタスクトレイに収めます。タスクバーからは消えます。"
              "復元はトレイアイコンのダブルクリックまたは右クリックメニューから。",
        "en": "When minimized, hide the window to the system tray (the taskbar entry "
              "disappears). Double-click the tray icon, or use its context menu, to restore.",
    },
    "toolbar.tray_unavailable_tooltip": {
        "ja": "このシステムではタスクトレイが利用できません。",
        "en": "The system tray is not available on this system.",
    },
    "toolbar.dark_theme": {"ja": "ダークテーマ", "en": "Dark theme"},
    "toolbar.dark_theme_tooltip": {
        "ja": "UI 全体をダークパレットに切り替えます。",
        "en": "Switch the entire UI to a dark palette.",
    },
    "toolbar.log_panel": {"ja": "ログ表示", "en": "Show log"},
    "toolbar.log_panel_tooltip": {
        "ja": "ウィンドウ下部にログ行を表示します。クリックで履歴を展開できます。",
        "en": "Show a log row at the bottom of the window. Click to expand history.",
    },
    "tray.show": {"ja": "表示", "en": "Show"},
    "tray.quit": {"ja": "終了", "en": "Quit"},
    "toolbar.tree_font_label": {"ja": " ツリー字: ", "en": " Tree font: "},
    "toolbar.trash_keep_label": {"ja": " ごみ箱保持: ", "en": " Trash keep: "},
    "toolbar.days_suffix": {"ja": " 日 (0=無制限)", "en": " days (0=unlimited)"},
    "toolbar.empty_trash": {"ja": "ごみ箱を空にする", "en": "Empty trash"},
    "toolbar.about": {"ja": "バージョン情報...", "en": "About..."},

    # ---- about dialog ----
    "about.title": {
        "ja": "Clipboard Image Stocker について",
        "en": "About Clipboard Image Stocker",
    },
    "about.body": {
        "ja": "<h3>Clipboard Image Stocker</h3>"
              "<p>バージョン: {version}<br>"
              "作者: {author}<br>"
              "配布元: <a href=\"{url}\">{url}</a></p>",
        "en": "<h3>Clipboard Image Stocker</h3>"
              "<p>Version: {version}<br>"
              "Author: {author}<br>"
              "Homepage: <a href=\"{url}\">{url}</a></p>",
    },

    # ---- sidebar ----
    "sidebar.header": {"ja": "フォルダ", "en": "Folders"},
    "sidebar.trash_with_count": {
        "ja": "🗑 ごみ箱 ({n})",
        "en": "🗑 Trash ({n})",
    },
    "sidebar.folder_with_count": {
        "ja": "{name} ({n})",
        "en": "{name} ({n})",
    },
    "sidebar.trash": {"ja": "🗑 ごみ箱", "en": "🗑 Trash"},
    "sidebar.trash_tooltip": {"ja": "ごみ箱", "en": "Trash"},
    "sidebar.menu_create_subfolder": {
        "ja": "サブフォルダを作成...",
        "en": "Create subfolder...",
    },
    "sidebar.menu_rename_folder": {
        "ja": "名前を変更...",
        "en": "Rename...",
    },
    "sidebar.menu_delete_folder": {
        "ja": "フォルダを削除...",
        "en": "Delete folder...",
    },
    "sidebar.menu_expand_subtree": {
        "ja": "ここからツリーを全て展開",
        "en": "Expand all from here",
    },
    "sidebar.menu_collapse_subtree": {
        "ja": "ここからツリーを全て閉じる",
        "en": "Collapse all from here",
    },

    # ---- dialogs / status ----
    "dialog.workspace_select_title": {
        "ja": "ワークスペース選択",
        "en": "Select workspace",
    },
    "dialog.workspace_select_body": {
        "ja": "画像を蓄積するワークスペース基点フォルダを選択してください。\n"
              "今後追加するサブフォルダはこの配下に作成されます。",
        "en": "Choose a workspace root folder to store your images.\n"
              "New subfolders will be created under this root.",
    },
    "dialog.workspace_select_picker": {
        "ja": "ワークスペース基点フォルダを選択",
        "en": "Choose workspace root folder",
    },
    "dialog.error": {"ja": "エラー", "en": "Error"},
    "dialog.not_configured": {"ja": "未設定", "en": "Not configured"},
    "dialog.configure_workspace_first": {
        "ja": "先にワークスペースを設定してください。",
        "en": "Please configure a workspace first.",
    },
    "dialog.create_subfolder_title": {
        "ja": "サブフォルダを作成",
        "en": "Create subfolder",
    },
    "dialog.create_subfolder_body": {
        "ja": "親フォルダ: {parent}\n新しいフォルダ名:",
        "en": "Parent folder: {parent}\nNew folder name:",
    },
    "dialog.create_failed": {"ja": "作成失敗", "en": "Create failed"},
    "dialog.rename_failed": {"ja": "リネーム失敗", "en": "Rename failed"},
    "dialog.rename_disallowed": {"ja": "リネーム不可", "en": "Rename not allowed"},
    "dialog.workspace_rename_blocked": {
        "ja": "ワークスペース基点フォルダはここからリネームできません。",
        "en": "The workspace root folder cannot be renamed from here.",
    },
    "dialog.rename_folder_title": {
        "ja": "フォルダ名を変更",
        "en": "Rename folder",
    },
    "dialog.rename_folder_body": {
        "ja": "現在の名前: {name}\n新しい名前:",
        "en": "Current name: {name}\nNew name:",
    },
    "dialog.delete_folder_title": {
        "ja": "フォルダを削除",
        "en": "Delete folder",
    },
    "dialog.delete_folder_body": {
        "ja": "フォルダ「{name}」を削除します。\n"
              "中の {n} 件のファイルはごみ箱に移動されます。\n"
              "よろしいですか？",
        "en": "Delete folder \"{name}\".\n"
              "{n} file(s) inside will be moved to trash.\n"
              "Continue?",
    },
    "dialog.delete_folder_empty_body": {
        "ja": "空のフォルダ「{name}」を削除します。よろしいですか？",
        "en": "Delete empty folder \"{name}\". Continue?",
    },
    "dialog.delete_failed": {"ja": "削除失敗", "en": "Delete failed"},
    "dialog.delete_disallowed": {
        "ja": "削除不可",
        "en": "Delete not allowed",
    },
    "dialog.workspace_delete_blocked": {
        "ja": "ワークスペース基点フォルダはここから削除できません。",
        "en": "The workspace root folder cannot be deleted from here.",
    },
    "dialog.import_error": {"ja": "取り込みエラー", "en": "Import error"},
    "dialog.move_data_parse_failed": {
        "ja": "移動データの解析に失敗: {err}",
        "en": "Failed to parse move data: {err}",
    },
    "dialog.copying_files": {"ja": "ファイルコピー中...", "en": "Copying files..."},
    "dialog.moving_files": {"ja": "ファイル移動中...", "en": "Moving files..."},
    "dialog.cancel": {"ja": "キャンセル", "en": "Cancel"},
    "dialog.copy_move_error": {"ja": "コピー/移動エラー", "en": "Copy/move error"},
    "dialog.cannot_paste": {"ja": "貼り付け不可", "en": "Cannot paste"},
    "dialog.select_managed_folder_first": {
        "ja": "まず管理フォルダを選択してください。",
        "en": "Please select a managed folder first.",
    },
    "dialog.save_failed": {"ja": "保存に失敗", "en": "Save failed"},
    "dialog.save_failed_body": {"ja": "#{pid}: {err}", "en": "#{pid}: {err}"},
    "dialog.rename_file_title": {"ja": "名前を変更", "en": "Rename"},
    "dialog.rename_file_body": {"ja": "新しいファイル名:", "en": "New file name:"},
    "dialog.permanent_delete_title": {"ja": "完全削除", "en": "Permanent delete"},
    "dialog.permanent_delete_body": {
        "ja": "ごみ箱内の {n} 件を完全削除します。元に戻せません。",
        "en": "Permanently delete {n} item(s) from trash. This cannot be undone.",
    },
    "dialog.cannot_delete": {"ja": "削除不可", "en": "Cannot delete"},
    "dialog.no_workspace_no_trash": {
        "ja": "ワークスペースが未設定のためごみ箱が使えません。",
        "en": "No workspace is configured, so trash is unavailable.",
    },
    "dialog.confirm": {"ja": "確認", "en": "Confirm"},
    "dialog.empty_trash_body": {
        "ja": "ごみ箱内の {n} 件を完全に削除します。よろしいですか？",
        "en": "Permanently delete {n} item(s) from trash. Continue?",
    },
    "dialog.copy_failed": {"ja": "コピー失敗", "en": "Copy failed"},
    "dialog.image_load_failed": {
        "ja": "画像を読み込めませんでした: {name}",
        "en": "Failed to load image: {name}",
    },
    "dialog.partial_restore_failed": {
        "ja": "一部復元失敗",
        "en": "Partial restore failure",
    },

    # ---- status bar ----
    "status.no_workspace": {"ja": "（ワークスペース未設定）", "en": "(no workspace)"},
    "status.folder_summary": {
        "ja": "{name}: {n} 件  /  サムネ: {policy}",
        "en": "{name}: {n} items  /  thumbs: {policy}",
    },
    "status.queue": {"ja": "保存待ち: {n}", "en": "Queued: {n}"},
    "status.queue_warning": {"ja": "保存待ち: {n} ⚠", "en": "Queued: {n} ⚠"},

    # ---- context menu ----
    "menu.restore_to_origin": {"ja": "削除元へ復元", "en": "Restore to origin"},
    "menu.open_with_default": {
        "ja": "関連付けで開く",
        "en": "Open with default app",
    },
    "menu.reveal_in_explorer": {
        "ja": "エクスプローラで開く",
        "en": "Reveal in Explorer",
    },
    "menu.permanent_delete": {"ja": "Del 完全に削除", "en": "Del Delete permanently"},
    "menu.copy_image": {"ja": "画像をコピー", "en": "Copy image"},
    "menu.copy_files": {"ja": "Ctrl+C ファイルをコピー", "en": "Ctrl+C copy files"},
    "menu.rename_file": {"ja": "F2 名前を変更", "en": "F2 Rename"},
    "menu.delete_to_trash": {"ja": "Del 削除（ごみ箱へ）", "en": "Del Delete (to trash)"},
    "menu.move_to_folder": {"ja": "別フォルダへ移動 →", "en": "Move to folder →"},
    "menu.copy_to_folder": {"ja": "別フォルダへコピー →", "en": "Copy to folder →"},
    "menu.create_subfolder": {"ja": "サブフォルダを作成", "en": "Create subfolder"},

    # ---- delegate ----
    "delegate.saving": {"ja": "保存中...", "en": "Saving..."},

    # ---- log panel ----
    "log.empty": {"ja": "（ログなし）", "en": "(no log)"},
    "log.expand_tooltip": {
        "ja": "クリックで履歴を展開／折りたたみ",
        "en": "Click to expand / collapse history",
    },
    "log.workspace_root": {"ja": "(ワークスペース)", "en": "(workspace)"},
    "log.trash": {"ja": "ごみ箱", "en": "Trash"},
    "log.move": {
        "ja": "{src} から {dst} に {n} 個のファイルを移動しました",
        "en": "Moved {n} file(s) from {src} to {dst}",
    },
    "log.copy": {
        "ja": "{src} から {dst} に {n} 個のファイルをコピーしました",
        "en": "Copied {n} file(s) from {src} to {dst}",
    },
    "log.trash_op": {
        "ja": "{src} から {n} 個のファイルをごみ箱へ移動しました",
        "en": "Moved {n} file(s) from {src} to Trash",
    },
    "log.undo_move": {
        "ja": "Undo: {dst} から {src} に {n} 個のファイルを戻しました",
        "en": "Undo: moved {n} file(s) back from {dst} to {src}",
    },
    "log.undo_copy": {
        "ja": "Undo: {dst} にコピーした {n} 個のファイルをごみ箱へ移動しました",
        "en": "Undo: moved {n} copied file(s) in {dst} to Trash",
    },
    "log.undo_trash": {
        "ja": "Undo: ごみ箱から {n} 個のファイルを {src} に復元しました",
        "en": "Undo: restored {n} file(s) from Trash to {src}",
    },
    "log.redo_move": {
        "ja": "Redo: {src} から {dst} に {n} 個のファイルを再度移動しました",
        "en": "Redo: moved {n} file(s) again from {src} to {dst}",
    },
    "log.redo_copy": {
        "ja": "Redo: {src} から {dst} に {n} 個のファイルを再度コピーしました",
        "en": "Redo: copied {n} file(s) again from {src} to {dst}",
    },
    "log.redo_trash": {
        "ja": "Redo: {src} の {n} 個のファイルを再度ごみ箱へ移動しました",
        "en": "Redo: trashed {n} file(s) again from {src}",
    },
    "log.undo_failed": {
        "ja": "Undo に失敗: {err}",
        "en": "Undo failed: {err}",
    },
    "log.redo_failed": {
        "ja": "Redo に失敗: {err}",
        "en": "Redo failed: {err}",
    },
    "log.nothing_to_undo": {
        "ja": "Undo するものがありません",
        "en": "Nothing to undo",
    },
    "log.nothing_to_redo": {
        "ja": "Redo するものがありません",
        "en": "Nothing to redo",
    },

    # ---- undo dialogs ----
    "dialog.confirm_undo_copy_title": {
        "ja": "コピーの取り消し",
        "en": "Undo copy",
    },
    "dialog.confirm_undo_copy_body": {
        "ja": "「{dst}」にコピーした {n} 個のファイルをごみ箱へ移動します。よろしいですか？",
        "en": "Move {n} file(s) copied to \"{dst}\" into the Trash. Continue?",
    },
    "dialog.undo_trash_no_workspace_title": {
        "ja": "Undo 不可",
        "en": "Undo unavailable",
    },
    "dialog.undo_trash_no_workspace_body": {
        "ja": "ワークスペースが未設定のため、ごみ箱からの復元 Undo は実行できません。\n"
              "手動でごみ箱から復元してください。",
        "en": "No workspace is configured, so Undo from Trash cannot run.\n"
              "Please restore the items manually from Trash.",
    },
    "dialog.undo_trash_failed_title": {
        "ja": "ごみ箱からの復元に失敗",
        "en": "Restore from Trash failed",
    },
    "dialog.undo_trash_failed_body": {
        "ja": "一部または全部の復元に失敗しました。手動でごみ箱から復元してください。\n\n{detail}",
        "en": "Restore failed for some or all items. Please restore them manually from Trash.\n\n{detail}",
    },

    # ---- paste / move errors (caught by main_window and surfaced via QMessageBox) ----
    "paste.no_target": {
        "ja": "保存先フォルダが未指定",
        "en": "No target folder specified",
    },
    "move.same_folder": {
        "ja": "同一フォルダへの移動はできません",
        "en": "Cannot move into the same folder",
    },
    "move.source_missing": {
        "ja": "元ファイルが存在しません: {src}",
        "en": "Source file does not exist: {src}",
    },

    # ---- folder_manager errors (raised as ValueError, caught by UI) ----
    "fm.no_workspace": {
        "ja": "ワークスペースが未設定です",
        "en": "No workspace is configured",
    },
    "fm.not_a_folder": {"ja": "フォルダではありません: {path}", "en": "Not a folder: {path}"},
    "fm.invalid_name": {
        "ja": "無効なフォルダ名です: {name}",
        "en": "Invalid folder name: {name}",
    },
    "fm.reserved_name": {
        "ja": "予約済みのフォルダ名です: {name}",
        "en": "Reserved folder name: {name}",
    },
    "fm.outside_workspace_create": {
        "ja": "ワークスペース外には作成できません",
        "en": "Cannot create outside the workspace",
    },
    "fm.already_exists": {"ja": "既に存在します: {name}", "en": "Already exists: {name}"},
    "fm.cant_rename_workspace": {
        "ja": "ワークスペース基点フォルダはリネームできません",
        "en": "The workspace root folder cannot be renamed",
    },
    "fm.cant_rename_outside": {
        "ja": "ワークスペース外のフォルダはリネームできません",
        "en": "Cannot rename a folder outside the workspace",
    },
    "fm.not_found": {"ja": "フォルダが見つかりません: {path}", "en": "Folder not found: {path}"},
    "fm.cant_delete_workspace": {
        "ja": "ワークスペース基点フォルダは削除できません",
        "en": "The workspace root folder cannot be deleted",
    },
    "fm.cant_delete_outside": {
        "ja": "ワークスペース外のフォルダは削除できません",
        "en": "Cannot delete a folder outside the workspace",
    },

    # ---- trash errors ----
    "trash.not_in_trash": {
        "ja": "ごみ箱内にファイルがありません",
        "en": "File not found in trash",
    },
    "trash.restore_target_create_failed": {
        "ja": "復元先を作成できません: {err}",
        "en": "Cannot create restore target: {err}",
    },
}
