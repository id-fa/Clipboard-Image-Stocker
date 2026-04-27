# Clipboard Image Stocker — 開発メモ

軽量 Eagle ライクの画像ストッカー (Windows / Python 3.12 + PySide6)。Eagle が重いので「眺める・貯める・取り出す」の最小機能に絞ったローカルアプリ。

## 開発環境

- Python: **3.12.12** (Astral 経由)。`.venv/` がプロジェクト直下にある (`py -V:Astral/CPython3.12.12 -m venv .venv` で再作成可)
- 依存: `requirements.txt` (PySide6, Pillow) + `requirements-dev.txt` (pytest, pytest-qt, pyinstaller, ruff, black)
- `src` レイアウト: ランタイムは `pyproject.toml` の `[tool.pytest.ini_options].pythonpath = ["src"]`、IDE は `pyrightconfig.json` の `extraPaths`、テストは `tests/conftest.py` で sys.path 注入
- 凍結中は `os.environ.setdefault("PYTHONUTF8", "1")` を `main.py` 先頭で設定済 (日本語パス対策)

## 主要コマンド

```sh
# 開発起動
./.venv/Scripts/python.exe -m stocker

# テスト (54 件)
./.venv/Scripts/python.exe -m pytest tests/

# ポータブル zip ビルド
./.venv/Scripts/pyinstaller.exe --clean build/stocker.spec --distpath dist --workpath build/build
# その後 dist/Stocker/portable.flag をタッチして Compress-Archive
```

凍結 exe を起動した状態でテストや再ビルドをすると `python3.dll` がロックされる。先に `Get-Process Stocker | Stop-Process -Force` する。

## アーキテクチャ要点

### ワークスペースモデル
- `AppConfig.workspace_root` 1 つを基点とする (Eagle ライブラリ式)。
- 配下の任意サブフォルダがそれぞれ「管理フォルダ」で、自分の `.stocker/` (DB + サムネキャッシュ) を持つ。
- 「フォルダを追加」UI はサブフォルダ作成 (workspace 配下のみ許可)。`FolderManager.create_subfolder()`。
- ワークスペース外への作成は明示的に拒否される。

### Scanner は非再帰
`core/scanner.py` の `_iter_image_files()` は **トップレベルのみ**を走査する。各サブフォルダは独立 DB を持つので再帰すると二重計上になる。サブディレクトリも `.stocker` も `.trash` もまとめて skip。

### パスとファイル名
- DB の `rel_path` は **forward-slash** (`utils.paths.normalize_rel`)。Windows パス変換は `from_rel(root, rel)`。
- ディスクサムネキャッシュは SHA1 命名 (`<sha1(rel)>_<size>.webp`) で日本語ファイル名衝突を回避。
- 衝突時のリネームは `avoid_collision()` で `name (2).png`, `name (3).png` …。
- 全関数で `pathlib.Path` 経由、`os.fspath()` で正規化。

### サムネイル戦略 (500 件しきい値)
- フォルダ内ファイル数 < 500 → メモリ LRU のみ (`OrderedDict[ThumbKey, QPixmap]`, capacity 1024)
- ≥ 500 → 加えてディスクキャッシュ (`<root>/.stocker/thumbs/<sha1>_<size>.webp`) に書き出し
- `policy_for(file_count)` が `MEMORY_ONLY | MEMORY_PLUS_DISK` を返す
- `cache.get()` は memory miss → disk → 双方 miss なら `request_thumbnail` シグナル経由でワーカー投入

### クリップボード貼り付けキュー (核心機能)
`core/paste_queue.py`:
- Ctrl+V 押下時に **`QImage.copy()` で深いコピー**を取り `queue.Queue` へ → UI スレッドは即解放
- ワーカー QThread は **1 本のみ** (タイムスタンプ命名の順序保証)
- `pending_added` シグナル → ThumbnailModel が PENDING 行を即追加 → 保存完了で `paste_completed` → 実 FileItem に差し替え
- 失敗は指数バックオフ 3 回 → エラー UI
- 連打 30 件で取りこぼしゼロ (`tests/test_paste_queue.py`)

### Ctrl+V の優先順位
クリップボードに **ファイル URL があればそれを `import_files()`**、無ければ画像を `PasteQueue.enqueue()`。Explorer の Ctrl+V と整合する挙動。

### サムネ二重表示問題への対処
`paste_completed` と FS Watcher の `directoryChanged` が同じ新規ファイルを別ルートで model に追加する競合があった。`ThumbnailModel.append_item()` は **`rel_path` 重複時に no-op** で吸収する。新しい行を入れる際は必ずこのメソッド経由で。

### 外部 D&D
- 受信: `ThumbnailView` に `setDragDropMode(DragDrop)` + `viewport().setAcceptDrops(True)` + `Model.canDropMimeData` を返す。これらの 1 つでも欠けると外部からの D&D が無視される。
- 送信: `Model.mimeData()` が `text/uri-list` + 独自 `application/x-stocker-items` (送信元 root + rel をJSON 化) を載せる。Explorer は `text/uri-list` → `CF_HDROP` に自動変換。

### サイドバー D&D ハイライトと Ctrl 修飾
- `Sidebar.dragMoveEvent` がカーソル下のフォルダノードを `DROP_HIGHLIGHT_BRUSH` (オレンジ半透明) で塗る (落下先を視認しやすく)
- `Sidebar.dropEvent` で `keyboardModifiers() & ControlModifier` を判定し signal 引数 `mode_str = "copy" | "move"` に乗せる。`MoveService.perform_move(mode=…)` で挙動を切替

### ホバー拡大プレビューの落とし穴
`HoverPreviewWindow` には **必ず `WA_TransparentForMouseEvents` + `WindowTransparentForInput`** を付ける。さもないと表示直後にプレビューがマウス下に来て `ThumbnailView.leaveEvent → cancel()` が発火し一瞬で消える。`HOVER_DELAY_MS = 1200` (`src/stocker/ui/hover_preview.py:18`)。

### ごみ箱と復元
- `<workspace>/.trash/` に `<stem>_<ts_ms>.<ext>` で時刻スタンプ付き保存。ボリューム跨ぎは `os.replace` → `shutil.move` フォールバック。
- 復元情報は `<workspace>/.stocker/trash_index.json` に `{trashed_basename: {origin_folder_rel, original_name, trashed_at_ns}}` で保持。
- `auto_purge(days)` は mtime ベース。`days=0` で無効。
- `move_to_trash()` の引数は `list[tuple[Path, Path]]` = `(file_abs, src_managed_folder)`。**呼び出し側で必ず src_root をペアで渡す**。

### クロス DB 操作
`MainWindow._dbs: dict[Path, MetadataDB]` で開いた DB をキャッシュ。フォルダ移動・トラッシュ・復元は src DB と dst DB の両方を必要とするので、`_db(path)` で必要に応じて開いて使う。`closeEvent` で全 DB クローズ。

## ファイル構成 (主要)

| ファイル | 役割 |
|---|---|
| `src/stocker/main.py` | QApplication ブートストラップ、UTF-8 強制 |
| `src/stocker/app_paths.py` | パス定数 (`STOCKER_DIRNAME=".stocker"`, `TRASH_DIRNAME=".trash"`, `HIDDEN_DIR_NAMES`) |
| `src/stocker/config.py` | `AppConfig` dataclass、`%APPDATA%/Stocker/config.json` 永続化 (ポータブル時は `./userdata/`) |
| `src/stocker/db/metadata_db.py` | フォルダごとの SQLite (WAL, mmap, bulk upsert) |
| `src/stocker/core/folder_manager.py` | workspace + サブフォルダ管理 |
| `src/stocker/core/scanner.py` | 非再帰 diff スキャン |
| `src/stocker/core/paste_queue.py` | クリップボード貼り付けキュー (核心) |
| `src/stocker/core/thumbnail_cache.py` | LRU + ディスクキャッシュ協調 |
| `src/stocker/core/move_service.py` | フォルダ間移動/コピー (跨 DB トランザクション) |
| `src/stocker/core/trash.py` | ごみ箱 + 復元 + auto_purge |
| `src/stocker/utils/clipboard_files.py` | Explorer 互換のファイル/画像コピー (Preferred DropEffect) |
| `src/stocker/ui/main_window.py` | UI 統括ハブ (~720 行) |
| `src/stocker/ui/sidebar.py` | ツリーサイドバー + D&D ハイライト |
| `src/stocker/ui/thumbnail_view.py` | 仮想化 IconMode QListView |
| `src/stocker/ui/thumbnail_model.py` | QAbstractListModel + dedupe + mime |
| `src/stocker/ui/hover_preview.py` | フローティングプレビュー (mouse-transparent) |

## テスト構成

`tests/` 配下、pytest-qt 使用。`conftest.py` が `src` を sys.path に注入。

- `test_metadata_db.py` (9): スキーマ、CRUD、bulk、ソート、日本語ファイル名
- `test_scanner.py` (5): 差分検出、非再帰、`.stocker` skip
- `test_thumbnail_cache.py` (6): LRU、500 件しきい値、SHA1 命名
- `test_thumbnail_model.py` (4): dedupe、PENDING ↔ real swap、FS watcher 競合
- `test_paste_queue.py` (4): 30 件連打損失ゼロ、衝突回避
- `test_move_service.py` (7): 同一/異ボリューム、衝突採番、進捗キャンセル、日本語
- `test_trash.py` (9): origin tracking、復元 (衝突/フォルダ消失含む)、auto_purge、index 整合性
- `test_folder_manager.py` (5): workspace 設定、subfolder 作成、hidden 除外
- `test_clipboard_files.py` (5): URL roundtrip、DropEffect バイト列確認、画像コピー

## 既知の癖・注意点

- ツールバー初期化時に `set_columns()` 等を呼ぶと `valueChanged` が発火するので、**`blockSignals(True)` で囲んでから初期値をセット**してから signal を connect する。`MainWindow.__init__` 参照。
- Pyright が `stocker.*` の import を解決できない警告を頻発するが、`pyrightconfig.json` の `venvPath`/`venv` 設定で IDE 再起動後に解消する。実行時には影響なし。
- `QImage.save(BytesIO, "PNG")` は PySide6 で動かない (`QIODevice` 必須)。Pillow との変換は `utils/qt_helpers.qimage_to_pil` の **直接 buffer コピー**を使う。
- `from_rel(root, rel)` は内部で `\` 区切りに戻すので、Windows でそのまま `pathlib.Path` 操作可能。
- PyInstaller spec は **15 個近くの Qt サブモジュール** (QtNetwork, QtQml, QtMultimedia, Qt3D* 等) を `excludes` する。サイズ削減のため。

## ユーザー設定の永続化

`AppConfig` (`src/stocker/config.py`):
- `workspace_root`, `last_active_root`, `columns` (1〜16), `sort_key/dir`
- `sidebar_font_size` (7〜28pt)
- `paste_format` ("png"|"jpeg"), `paste_jpeg_quality`
- `trash_auto_delete_days` (0=無効)
- 起動時に `auto_purge(workspace, trash_auto_delete_days)` を実行

## 拒否された/採用しなかった選択肢

- **C# WPF**: 真にネイティブだが、コンパイル不要の開発速度を優先して Python に。
- **watchdog ライブラリ**: PyInstaller サイズと Qt 統合性のため `QFileSystemWatcher` 一本。
- **再帰スキャン**: ワークスペースモデル採用に伴い意味的に矛盾するため非再帰へ。
- **タグ/全文検索 (FTS5)**: 「軽量」要件のため M6 として保留。

## 配布

- ポータブル zip 形式 (約 52 MB)
- `dist/Stocker/portable.flag` の有無で `userdata/` モードに切替 (`app_paths.is_portable()`)
- `Stocker.exe` は約 2.6 MB のランチャ + `_internal/` (PySide6 ランタイム)
