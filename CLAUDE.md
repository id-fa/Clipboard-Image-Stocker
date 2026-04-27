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

# テスト (79 件)
./.venv/Scripts/python.exe -m pytest tests/

# ポータブル zip ビルド (PyInstaller → portable.flag → Compress-Archive を一括)
pwsh ./build/make_portable.ps1
# 出力: dist/Stocker-v<pyproject.version>-win64.zip
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

### クリップボード自動取込
`core/clipboard_watcher.py`:
- `QClipboard.dataChanged` を購読。トグル ON 時のみ画像があれば `PasteQueue.enqueue()` に流す。保存先は `last_active_root` (PasteQueue の target_root)。
- 同一画像の再保存抑制は **フィンガープリント** (W×H + format + sizeInBytes + 四隅ピクセル) を直前のものと比較。dataChanged の重複発火と自分の Copy エコーを吸収する。
- `note_self_copy(qimg)`: Stocker 自身が `copy_image_to_clipboard()` でコピーする直前に呼んでフィンガープリントを記録 → 次の dataChanged を黙殺。
- `set_autocapture(enabled)` 切替時には現在のクリップボード画像のフィンガープリントをシードに使い、起動直後の既存画像を再取込しない。
- 設定: `AppConfig.clipboard_autocapture: bool` (デフォルト OFF / プライバシ重視)。

### サイドバー D&D ハイライトと Ctrl 修飾
- `Sidebar.dragMoveEvent` がカーソル下のフォルダノードを `DROP_HIGHLIGHT_BRUSH` (オレンジ半透明) で塗る (落下先を視認しやすく)
- `Sidebar.dropEvent` で `keyboardModifiers() & ControlModifier` を判定し signal 引数 `mode_str = "copy" | "move"` に乗せる。`MoveService.perform_move(mode=…)` で挙動を切替

### ホバー拡大プレビューの落とし穴
`HoverPreviewWindow` には **必ず `WA_TransparentForMouseEvents` + `WindowTransparentForInput`** を付ける。さもないと表示直後にプレビューがマウス下に来て `ThumbnailView.leaveEvent → cancel()` が発火し一瞬で消える。`HOVER_DELAY_MS = 1200` (`src/stocker/ui/hover_preview.py:18`)。

ツールバーの「ホバー拡大」チェックボックスから `set_enabled(bool)` で全停止可能。OFF 中は `schedule()` が即 return + 表示中のプレビューも `cancel()`。設定は `AppConfig.hover_preview_enabled` (デフォルト ON)。

### ごみ箱と復元
- `<workspace>/.trash/` に `<stem>_<ts_ms>.<ext>` で時刻スタンプ付き保存。ボリューム跨ぎは `os.replace` → `shutil.move` フォールバック。
- 復元情報は `<workspace>/.stocker/trash_index.json` に `{trashed_basename: {origin_folder_rel, original_name, trashed_at_ns}}` で保持。
- `auto_purge(days)` は mtime ベース。`days=0` で無効。
- `move_to_trash()` の引数は `list[tuple[Path, Path]]` = `(file_abs, src_managed_folder)`。**呼び出し側で必ず src_root をペアで渡す**。

### クロス DB 操作
`MainWindow._dbs: dict[Path, MetadataDB]` で開いた DB をキャッシュ。フォルダ移動・トラッシュ・復元は src DB と dst DB の両方を必要とするので、`_db(path)` で必要に応じて開いて使う。`closeEvent` で全 DB クローズ。

### フォルダのリネーム
サイドバー右クリック「名前を変更...」で `FolderManager.rename_folder()` を呼ぶ。ワークスペース基点フォルダは UI/API 両方で拒否される (`cfg.workspace_root` と整合させない)。`MainWindow._on_rename_folder_requested` の手順:
1. **対象配下の全 DB をクローズ**してから rename (Windows は SQLite ファイルロックでディレクトリ rename が失敗する)
2. `fs_watcher.watch(None)` と `paste_queue.set_target_root(None)` で旧パス参照を切る
3. `Path.rename()` 実行
4. `trash.rewrite_origin_paths(workspace, old_rel, new_rel)` で `trash_index.json` の `origin_folder_rel` をサブツリー含めて更新 (これがないと復元先がフォルダ消失扱いになる)
5. アクティブパスがリネームツリー配下なら新パスに翻訳して `_activate_folder()` で再構築 (DB 再オープン・モデル replace・FS watcher 復帰・`cfg.last_active_root` 永続化を一括)

### 国際化 (i18n)
`src/stocker/i18n.py` は辞書ベースの軽量 i18n (Qt Linguist 不採用 ─ ビルドステップ追加と PyInstaller の data 取り込みを避けるため)。
- `detect_language()` は `QLocale.system().language()` が日本語なら `"ja"`、それ以外は `"en"`。`main.py` で `QApplication` 構築直後に `set_language(detect_language())` を呼ぶ。
- `tr(key, **fmt)` は active lang → DEFAULT_LANG (`"en"`) → `"ja"` → key 自体 の順にフォールバック。`{name}` 等は `str.format()` で展開。
- カタログは `i18n.py` の `_CATALOG` に全部 inline。UI 文字列だけでなく `core/folder_manager.py`, `core/trash.py`, `core/move_service.py`, `core/paste_queue.py` の `ValueError`／エラーメッセージも `tr()` 経由 (UI で `QMessageBox` 表示されるため)。
- ログメッセージ・コミットログ・テストデータの日本語はそのまま (ユーザー目に触れない)。

### アプリアイコン
`src/stocker/assets/icons/` 配下に同梱:
- `app.png` (256×256, ランタイム `QApplication.setWindowIcon` 用 ─ Qt がタスクバー/Alt+Tab 用にスケーリング)
- `app.ico` (16/24/32/48/64/128/256 マルチサイズ, PyInstaker spec の `icon=` で EXE に埋込)

マスター画像はリポジトリルートの `icon_base.png`。Pillow で 256 PNG と マルチサイズ ICO を派生生成する (再生成が必要なら同様の Pillow ワンライナーで)。パッケージ内部に置くことで `db/schema.sql` と同じ `Path(__file__).resolve().parent / ...` パターンで参照でき、PyInstaller でも `datas` に追加するだけで `_internal/stocker/assets/icons/` に展開される。

### About ダイアログ
ツールバー右端「バージョン情報...」(EN: "About...") から `QMessageBox.about()`。表示内容は `app_paths.py` の `APP_VERSION`, `APP_AUTHOR`, `APP_HOMEPAGE` を `tr("about.body", ...)` の HTML テンプレートに差し込む。URL は `<a href>` でクリック → ブラウザ起動。`pyproject.toml` の `version` と `APP_VERSION` は揃える運用 (`make_portable.ps1` が pyproject から zip ファイル名を作るため)。

## ファイル構成 (主要)

| ファイル | 役割 |
|---|---|
| `src/stocker/main.py` | QApplication ブートストラップ、UTF-8 強制、i18n 言語選択 |
| `src/stocker/i18n.py` | 軽量 i18n: 辞書カタログ + `tr()` + `QLocale` 検出 (ja/en) |
| `src/stocker/assets/icons/` | アプリアイコン (`app.png` 256px ランタイム用 / `app.ico` マルチサイズ EXE 埋込用)。マスター画像 `icon_base.png` をリポジトリルートに保持、Pillow で派生生成 |
| `src/stocker/app_paths.py` | パス定数 (`STOCKER_DIRNAME=".stocker"`, `TRASH_DIRNAME=".trash"`, `HIDDEN_DIR_NAMES`) + アプリメタ (`APP_NAME`, `APP_VERSION`, `APP_AUTHOR`, `APP_HOMEPAGE`) |
| `src/stocker/config.py` | `AppConfig` dataclass、`%APPDATA%/Stocker/config.json` 永続化 (ポータブル時は `./userdata/`) |
| `src/stocker/db/metadata_db.py` | フォルダごとの SQLite (WAL, mmap, bulk upsert) |
| `src/stocker/core/folder_manager.py` | workspace + サブフォルダ管理 (作成 / リネーム) |
| `src/stocker/core/scanner.py` | 非再帰 diff スキャン |
| `src/stocker/core/paste_queue.py` | クリップボード貼り付けキュー (核心) |
| `src/stocker/core/clipboard_watcher.py` | Ctrl+V のブリッジ + 自動取込 (フィンガープリント dedup) |
| `src/stocker/core/thumbnail_cache.py` | LRU + ディスクキャッシュ協調 |
| `src/stocker/core/move_service.py` | フォルダ間移動/コピー (跨 DB トランザクション) |
| `src/stocker/core/rename_service.py` | ファイル単体リネーム (ディスク + DB を整合) |
| `src/stocker/core/trash.py` | ごみ箱 + 復元 + auto_purge + `rewrite_origin_paths` (フォルダリネーム追従) |
| `src/stocker/utils/clipboard_files.py` | Explorer 互換のファイル/画像コピー (Preferred DropEffect) |
| `src/stocker/ui/main_window.py` | UI 統括ハブ (~960 行) |
| `src/stocker/ui/toolbar.py` | ツールバー (列数/ソート/貼り付け形式/自動取込/ホバー/ツリー字/ごみ箱/About) |
| `src/stocker/ui/sidebar.py` | ツリーサイドバー + D&D ハイライト + フォルダリネーム |
| `src/stocker/ui/thumbnail_view.py` | 仮想化 IconMode QListView |
| `src/stocker/ui/thumbnail_model.py` | QAbstractListModel + dedupe + mime |
| `src/stocker/ui/hover_preview.py` | フローティングプレビュー (mouse-transparent) |
| `build/stocker.spec` | PyInstaller spec (icon 埋込・assets バンドル・15+ Qt サブモジュール除外) |
| `build/make_portable.ps1` | `pyinstaller` → `portable.flag` → `Compress-Archive` を一括実行 |

## テスト構成

`tests/` 配下、pytest-qt 使用。`conftest.py` が `src` を sys.path に注入。

- `test_metadata_db.py` (9): スキーマ、CRUD、bulk、ソート、日本語ファイル名
- `test_scanner.py` (5): 差分検出、非再帰、`.stocker` skip
- `test_thumbnail_cache.py` (6): LRU、500 件しきい値、SHA1 命名
- `test_thumbnail_model.py` (4): dedupe、PENDING ↔ real swap、FS watcher 競合
- `test_paste_queue.py` (4): 30 件連打損失ゼロ、衝突回避
- `test_clipboard_watcher.py` (9): フィンガープリント dedup、autocapture トグル、自己コピー抑制、起動シード
- `test_move_service.py` (7): 同一/異ボリューム、衝突採番、進捗キャンセル、日本語
- `test_trash.py` (12): origin tracking、復元 (衝突/フォルダ消失含む)、auto_purge、index 整合性、フォルダリネーム後の origin 追従
- `test_folder_manager.py` (10): workspace 設定、subfolder 作成、hidden 除外、リネーム (workspace 拒否/不正名/衝突/外部拒否)
- `test_clipboard_files.py` (5): URL roundtrip、DropEffect バイト列確認、画像コピー
- `test_i18n.py` (8): ja/en 切替、format kwargs、未知キーフォールバック、`detect_language()` ホスト非依存

## 既知の癖・注意点

- ツールバー初期化時に `set_columns()` 等を呼ぶと `valueChanged` が発火するので、**`blockSignals(True)` で囲んでから初期値をセット**してから signal を connect する。`MainWindow.__init__` 参照。
- Pyright が `stocker.*` の import を解決できない警告を頻発するが、`pyrightconfig.json` の `venvPath`/`venv` 設定で IDE 再起動後に解消する。実行時には影響なし。
- `QImage.save(BytesIO, "PNG")` は PySide6 で動かない (`QIODevice` 必須)。Pillow との変換は `utils/qt_helpers.qimage_to_pil` の **直接 buffer コピー**を使う。
- `from_rel(root, rel)` は内部で `\` 区切りに戻すので、Windows でそのまま `pathlib.Path` 操作可能。
- PyInstaller spec は **15 個近くの Qt サブモジュール** (QtNetwork, QtQml, QtMultimedia, Qt3D* 等) を `excludes` する。サイズ削減のため。
- `Ctrl+C` ショートカットは `self._view` スコープに付ける (グローバルにすると入力欄やリネーム編集と衝突)。`MainWindow.__init__` 参照。

### X (Twitter) への複数枚 D&D は不可 — 必ず Ctrl+C → Ctrl+V を案内する

X (Twitter) Web UI のドロップハンドラは `e.dataTransfer.files` (CF_HDROP) に加えて
`UniformResourceLocator` / `UniformResourceLocatorW` / `CF_HTML` 中の URL も
「添付候補」として数えるため、**3 枚以上をドラッグすると「添付できる画像は4枚までです」
で弾かれてドロップ自体が失敗する** (実測: 2 枚は成功、3 枚以上 NG)。

原因: Qt 6 が `QMimeData.setUrls()` 経由で複数 URL を渡されると、Windows IDataObject に
以下を自動登録する。

```
CF_HDROP                     ← 想定どおり (画像枚数分のファイルパス)
UniformResourceLocator       ← 単一 URL 形式 (1個)
UniformResourceLocatorW      ← 単一 URL Unicode 版 (1個)
CF_HTML                      ← URL を埋め込んだ HTML
Ole Private Data
```

抑制不可: 以下の `QMimeData` サブクラス override をすべて検証したが
**いずれも Windows 側登録形式に効果なし** (Qt の Windows コンバータは内部データを
直接見るため): `hasFormat`/`formats`/`hasUrls`/`urls`/`hasText`/`hasHtml`/
`retrieveData`、`application/x-qt-windows-mime;value="..."` への明示的空セット。

`application/x-qt-windows-mime;value="HDROP"` へ raw `DROPFILES` を直書きする逃げも
試したが、Qt の windows-mime escape は予約 ID 15 (CF_HDROP) を取れず必ず
新規 ID (49000+) を払い出すので Chrome は CF_HDROP として認識しない。

抜本対策: `pywin32` で自前の `IDataObject` + `IDropSource` + `DoDragDrop` を実装する
しかなく作業量大。Twitter 限定の問題で他のドロップ先 (Discord / Slack / GitHub /
Gmail / Explorer) では正常動作するため、コードでは直さず **Ctrl+C →（外部アプリで）
Ctrl+V を推奨ワークフロー**にした。クリップボード経路では同じ複数形式が登録されるが、
Twitter のペーストハンドラは `e.clipboardData.files` のみを見るので 4 枚まで添付可能。

`Ctrl+C` を `_on_copy_files_to_clipboard` にバインド済 (`MainWindow.__init__`)。
コンテキストメニューも「Ctrl+C ファイルをコピー」表記で発見性を確保。

## ユーザー設定の永続化

`AppConfig` (`src/stocker/config.py`):
- `workspace_root`, `last_active_root`, `columns` (1〜16), `sort_key/dir`
- `sidebar_font_size` (7〜28pt)
- `paste_format` ("png"|"jpeg"), `paste_jpeg_quality`
- `clipboard_autocapture` (bool, default False) — クリップボード自動取込の ON/OFF
- `hover_preview_enabled` (bool, default True) — ホバー拡大プレビューの ON/OFF
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
- `Stocker.exe` は約 2.8 MB のランチャ (アイコン埋込済) + `_internal/` (PySide6 ランタイム + `stocker/assets/icons/` + `stocker/db/schema.sql`)
- バージョンは `pyproject.toml` の `version` と `app_paths.APP_VERSION` の 2 箇所を揃える運用 (前者は zip ファイル名 / 後者は About ダイアログ)
- 配布は `build/make_portable.ps1` 1 コマンドで完結 (PyInstaller → portable.flag → Compress-Archive)
