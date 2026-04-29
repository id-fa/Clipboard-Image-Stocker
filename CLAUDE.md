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

# テスト (87 件)
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

公開ヘルパー `count_image_files(root)` は同じ走査ロジックでファイル数だけを返す (DB を開かずに済むのでサイドバーのフォルダ件数表示用)。

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
- `pending_added` シグナル → ThumbnailModel が PENDING 行をソート位置に即追加 → 保存完了で `paste_completed` → PENDING 行を**削除**して実 FileItem を**ソート位置に再挿入** (in-place swap ではない)
- 失敗は指数バックオフ 3 回 → エラー UI
- 連打 30 件で取りこぼしゼロ (`tests/test_paste_queue.py`)

### Ctrl+V の優先順位
クリップボードに **ファイル URL があればそれを `import_files()`**、無ければ画像を `PasteQueue.enqueue()`。Explorer の Ctrl+V と整合する挙動。

### サムネ二重表示問題への対処
`paste_completed` と FS Watcher の `directoryChanged` が同じ新規ファイルを別ルートで model に追加する競合があった。`ThumbnailModel.append_item()` は **`rel_path` 重複時に no-op** で吸収する。新しい行を入れる際は必ずこのメソッド経由で (名前は append だが実体はソート位置挿入。後述)。

### ソート順を維持した挿入
`ThumbnailModel` は現在のソートキー/向き (`name`/`mtime`/`added` × `asc`/`desc`) を `set_sort()` で保持し、`append_item()` / `add_pending()` / `replace_pending_with_real()` はすべて **`_sorted_insert_position(item)` で算出した位置に挿入**する。これにより:
- 貼り付け画像はソート順に従った位置に着地する (以前は無条件で先頭に積まれていた)
- FS Watcher・外部 D&D・フォルダ間 move/copy・ごみ箱からの復元など、ランタイムで model に行を足す全経路で順序が保たれる
- ソート切替 (`_on_sort_changed`) では `MainWindow` が `model.set_sort(...)` で同期してから `db.list_files(...)` で全件 replace する

`replace_pending_with_real()` は in-place swap ではなく **PENDING 行削除 → `append_item(real)` でソート位置挿入** に変更されているため、PENDING/DISK が同じ rel_path で並ぶ過渡状態は dedupe で吸収される。

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

### サイドバーのフォルダ件数表示
ごみ箱と同様に各フォルダノード名の右に `({n})` で画像数を表示する (件数 0 のフォルダは数値非表示)。サブフォルダを含む合算ではなく、そのフォルダ直下の画像数のみ (= scanner の非再帰走査と同じ範囲)。

- 集計は `core/scanner.py` の `count_image_files(folder)` で行う。DB を開かずに `scandir` するだけなので軽量
- フル更新: `MainWindow._refresh_sidebar()` が全フォルダの件数を集めて `Sidebar.populate(..., folder_counts=...)` に渡す (ワークスペース変更・フォルダ作成/リネーム/削除・起動時)
- 部分更新: 件数が変わる経路で `_refresh_folder_count(folder)` → `Sidebar.update_folder_count(path, n)` で対象ノードのテキストだけ書き換え (paste 完了 / 外部 D&D / move/copy 結果 / 削除 / トラッシュ復元 / FS Watcher 検知 / `_activate_folder` のスキャン差分が出たとき)
- ごみ箱ノードは別 (`update_trash_count`) なので `_refresh_folder_count` は trash root を no-op で素通りさせる
- リアルタイム集計が必要なら `count_image_files()` のままで十分軽い。重くなったら遅延化を検討するが、現状は同期で問題なし

### ホバー拡大プレビュー
**トリガーはサムネイル右下コーナーのみ**。`ThumbnailView.mouseMoveEvent` が `visualRect(idx)` の右下 40%×40% (`HOVER_CORNER_FRAC = 0.4`、最小 16px) に入った時だけ `hover_changed(item)` を発火する。`entered` シグナルは未接続 (アイテム全体で発火するため使えない)。コーナー外/インデックス無効/`leaveEvent` ではいずれも `hover_changed(None)` を出す。`HOVER_DELAY_MS = 1200` (`src/stocker/ui/hover_preview.py:17`)。

**閉じるのはクリックのみ** (`HoverPreviewWindow.mousePressEvent → dismiss()`)。マウスをコーナー外に出してもプレビューは残る。これを成立させるため:
- ウィンドウフラグから `WindowTransparentForInput` を、属性から `WA_TransparentForMouseEvents` を **外している**。`QLabel` は子→親へのクリック透過のため `WA_TransparentForMouseEvents` のまま。
- `cancel()` の意味は「保留中のタイマー停止のみ／表示中は隠さない」。表示直後に view の `leaveEvent → hover_changed(None) → cancel()` が走っても消えないのはこのため。`_pending_path` も表示中はクリアしない (再ホバー時の dedup 維持)。
- 完全に閉じる時は `dismiss()` (= タイマー停止 + `_pending_path` クリア + `_stop_movie()` + `hide()`)。`set_enabled(False)` と `mousePressEvent` から呼ぶ。

ツールバーの「ホバー拡大」チェックボックスから `set_enabled(bool)` で全停止可能。OFF 中は `schedule()` が即 return + 表示中のプレビューも `dismiss()`。設定は `AppConfig.hover_preview_enabled` (デフォルト ON)。

#### アニメ GIF / WebP 再生
`_show_now()` で `QImageReader(path).supportsAnimation() and imageCount() > 1` を判定。アニメなら `_show_animated()` で `QMovie` を **GUI スレッド上に** 生成 (QMovie はスレッド移動不可) し `setScaledSize()` でスクリーンに合わせ縮小して `start()`。静止画は従来どおり `_LoadJob` (PIL → QPixmap) で worker 経由。

切替境界 (`_show_animated` / `_on_loaded`) と `dismiss()` で必ず `_stop_movie()` (`stop()` + `deleteLater()`) を呼んで前回の QMovie を確実に解放する。設定 `AppConfig.hover_preview_animate` (デフォルト ON、ツールバー「アニメ再生」チェックボックス)。OFF にすると静止画経路に固定され、現在再生中のプレビューも `dismiss()` で即停止。`QMovie.isValid()` が False の場合は静止画にフォールバック。

注意点:
- アニメ判定は `imageCount() > 1` で行うので、単一フレーム GIF は静止画扱い (PIL 経路)。
- QMovie がファイルハンドルを保持するため、プレビュー表示中の対象ファイルは Windows ロックがかかる (移動・リネーム失敗の可能性)。ただしクリックで dismiss → `deleteLater` で即解放されるので実害は限定的。
- PyInstaller spec の `excludes` には `QtImageFormats` が無く、`qwebp.dll` プラグインが取り込まれるので凍結ビルドでもアニメ WebP が動作する。

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

### フォルダの削除
サイドバー右クリック「フォルダを削除...」で `MainWindow._on_delete_folder_requested` を呼ぶ。リネームと同じくワークスペース基点は拒否。手順:
1. サブツリーを `os.walk` で走査し全ファイルを `(file, file.parent)` ペアで収集 (`HIDDEN_DIR_NAMES` = `.stocker` / `.trash` はスキップ)。`file.parent` が src_root になるのは「workspace 配下の全サブフォルダは管理フォルダ」という前提のため。
2. 件数を出して確認ダイアログ (空フォルダ用に別キー `dialog.delete_folder_empty_body`)。
3. **対象配下の全 DB をクローズ**してから削除に進む (リネームと同じく SQLite ロック対策)
4. アクティブがサブツリー配下なら `fs_watcher.watch(None)` + `paste_queue.set_target_root(None)`
5. `trash_svc.move_to_trash(ws, pairs)` で全ファイルをごみ箱へ。複数フォルダにまたがる場合は `origin_folder_rel` がそれぞれの親フォルダになるので、復元時に `trash.restore()` 内の `target_folder.mkdir(parents=True, exist_ok=True)` で消失したフォルダが再作成される。
6. `FolderManager.delete_folder()` で `shutil.rmtree()` (これにより各管理フォルダの `.stocker/` も含めて消える)
7. サイドバー再構築。アクティブが消えていれば `_activate_folder(workspace)` で復帰

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

### システムトレイ (最小化でトレイに格納)
`MainWindow.__init__` で `QSystemTrayIcon.isSystemTrayAvailable()` を判定し、利用可なら `QSystemTrayIcon` を生成 (アプリアイコン使用、メニューは「表示 / 終了」)。設定 `AppConfig.minimize_to_tray` (デフォルト OFF) と組み合わせ、ON の時のみトレイ常駐させる。

挙動:
- **× ボタンは通常終了** (closeEvent → クリーンアップ → quit)。トレイメニュー「終了」も `self.close()` 経由で同じ。
- **最小化 (`changeEvent` の `WindowStateChange` × `isMinimized()`)** で設定 ON のとき `QTimer.singleShot(0, self.hide)` で hide。changeEvent 内で直接 `hide()` を呼ぶと Windows のウィンドウステートが壊れるので必ず単発タイマー経由。
- **復元** はトレイアイコンの Trigger (シングルクリック) または DoubleClick → `_show_from_tray()` (`showNormal()` + `activateWindow()` + `raise_()`)。`showNormal()` が `Minimized` フラグも同時にクリアする。
- **設定 OFF への切替時** にウィンドウが隠れたままだとユーザーが見失うので `_on_minimize_to_tray_changed` 内で `_show_from_tray()` を呼んで強制復元。
- `closeEvent` で `self._tray.hide()` してからクリーンアップ (トレイアイコンが終了後に残らないように)。
- 起動時に `cfg.minimize_to_tray and tray_available` で `set_minimize_to_tray()` を初期化、`set_minimize_to_tray_available(tray_available)` でトレイ非対応プラットフォーム時にチェックボックス自体を無効化。`blockSignals(True)` 内で値設定するので初期化中の偽トグル発火はなし。

`setQuitOnLastWindowClosed(True)` (Qt デフォルト) を利用。トレイに隠れている間は「最後のウィンドウが閉じた」状態にならないのでアプリ継続、× で実際に閉じれば last window で quit。

### テーマ (ライト/ダーク)
追加依存なしで Qt 標準の Fusion + `QPalette` 切替のみで実現 (qdarkstyle 等は配布サイズが膨らむので不採用)。`src/stocker/ui/theme.py` の `apply_theme(app, name)` が `app.setStyle("Fusion")` + ライト用デフォルトパレット / 自前ダークパレットのどちらかを当てる。`main.py` で `cfg = load_config()` 直後に `apply_theme(app, cfg.theme)` を呼んで起動時から反映。

ツールバーのチェックボックス「ダークテーマ」(EN: "Dark theme") から `dark_theme_changed` シグナル → `MainWindow._on_dark_theme_changed()` で実行時に `apply_theme()` を再適用 + `cfg.theme` 永続化。`QApplication` の `paletteChanged` を受けてほとんどのウィジェットは自動再描画されるが、明示色を持つ View (Sidebar / ThumbnailDelegate) は念のため `viewport().update()` で強制再描画する。

明示色 (パレットでは賄えない箇所) は theme.py のヘルパー経由で取得し、テーマ依存に切替:
- `drop_highlight_color()` → サイドバーの D&D ハイライト (旧 `DROP_HIGHLIGHT_BRUSH` 定数を置換)。ライトはオレンジ `(255,165,0,180)`、ダークは少し明るい `(255,170,60,200)`
- `thumb_placeholder_color()` → サムネイル未ロード時のプレースホルダ (ライト `(40,40,40)` / ダーク `(60,60,60)`)
- HoverPreview の `QLabel` 背景色 `#1e1e1e` はもともとダーク基調なので両テーマ共通

PENDING バッジのオレンジ `(220,140,0,220)` と HoverPreview 背景は両テーマで違和感がないので据え置き。設定 `AppConfig.theme: str` (デフォルト `"light"`) で永続化。

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
| `src/stocker/core/folder_manager.py` | workspace + サブフォルダ管理 (作成 / リネーム / 削除) |
| `src/stocker/core/scanner.py` | 非再帰 diff スキャン + `count_image_files()` (サイドバー件数表示用) |
| `src/stocker/core/paste_queue.py` | クリップボード貼り付けキュー (核心) |
| `src/stocker/core/clipboard_watcher.py` | Ctrl+V のブリッジ + 自動取込 (フィンガープリント dedup) |
| `src/stocker/core/thumbnail_cache.py` | LRU + ディスクキャッシュ協調 |
| `src/stocker/core/move_service.py` | フォルダ間移動/コピー (跨 DB トランザクション) |
| `src/stocker/core/rename_service.py` | ファイル単体リネーム (ディスク + DB を整合) |
| `src/stocker/core/trash.py` | ごみ箱 + 復元 + auto_purge + `rewrite_origin_paths` (フォルダリネーム追従) |
| `src/stocker/utils/clipboard_files.py` | Explorer 互換のファイル/画像コピー (Preferred DropEffect) |
| `src/stocker/ui/main_window.py` | UI 統括ハブ (~960 行) |
| `src/stocker/ui/toolbar.py` | ツールバー (列数/ソート/貼り付け形式/自動取込/ホバー/アニメ再生/トレイ格納/ダークテーマ/ツリー字/ごみ箱/About) |
| `src/stocker/ui/sidebar.py` | ツリーサイドバー + D&D ハイライト + フォルダリネーム/削除 + フォルダ件数表示 |
| `src/stocker/ui/theme.py` | Fusion + `QPalette` ベースのライト/ダーク切替、明示色のヘルパー (`drop_highlight_color`, `thumb_placeholder_color`) |
| `src/stocker/ui/thumbnail_view.py` | 仮想化 IconMode QListView |
| `src/stocker/ui/thumbnail_model.py` | QAbstractListModel + dedupe + mime + ソート位置挿入 (`set_sort` / `_sorted_insert_position`) |
| `src/stocker/ui/hover_preview.py` | フローティングプレビュー (静止画 + アニメ GIF/WebP via QMovie) |
| `build/stocker.spec` | PyInstaller spec (icon 埋込・assets バンドル・15+ Qt サブモジュール除外) |
| `build/make_portable.ps1` | `pyinstaller` → `portable.flag` → `Compress-Archive` を一括実行 |

## テスト構成

`tests/` 配下、pytest-qt 使用。`conftest.py` が `src` を sys.path に注入。

- `test_metadata_db.py` (9): スキーマ、CRUD、bulk、ソート、日本語ファイル名
- `test_scanner.py` (6): 差分検出、非再帰、`.stocker` skip、`count_image_files` の走査範囲
- `test_thumbnail_cache.py` (6): LRU、500 件しきい値、SHA1 命名
- `test_thumbnail_model.py` (7): dedupe、PENDING → real リプレース、FS watcher 競合、ソート位置挿入 (name asc / mtime desc / paste 完了)
- `test_paste_queue.py` (4): 30 件連打損失ゼロ、衝突回避
- `test_clipboard_watcher.py` (9): フィンガープリント dedup、autocapture トグル、自己コピー抑制、起動シード
- `test_move_service.py` (7): 同一/異ボリューム、衝突採番、進捗キャンセル、日本語
- `test_trash.py` (12): origin tracking、復元 (衝突/フォルダ消失含む)、auto_purge、index 整合性、フォルダリネーム後の origin 追従
- `test_folder_manager.py` (14): workspace 設定、subfolder 作成、hidden 除外、リネーム (workspace 拒否/不正名/衝突/外部拒否)、削除 (basic/workspace 拒否/外部拒否/非存在)
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
- `hover_preview_animate` (bool, default True) — 拡大プレビューでアニメ GIF/WebP を再生するか
- `minimize_to_tray` (bool, default False) — 最小化時にウィンドウをタスクトレイに格納する (× ボタンは通常終了)
- `theme` ("light"|"dark", default "light") — Fusion + `QPalette` でライト/ダーク切替
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
