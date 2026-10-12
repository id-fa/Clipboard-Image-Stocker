# Clipboard Image Stocker — 開発メモ

軽量 Eagle ライクの画像ストッカー (Windows / Python 3.12 + PySide6)。Eagle が重いので「眺める・貯める・取り出す」の最小機能に絞ったローカルアプリ。

## 開発環境

- Python: **3.13.16** (python.org 公式ビルド、`C:\_BIN\python-3.13`、`py` のデフォルト)。`.venv/` がプロジェクト直下にある (`py -3.13 -m venv .venv` → `.venv/Scripts/python.exe -m pip install -r requirements-dev.txt` で再作成可)。`requires-python >= 3.12` / ruff・black・pyright の target は 3.12 のまま (下限互換を維持)
- 依存: `requirements.txt` (PySide6, Pillow) + `requirements-dev.txt` (pytest, pytest-qt, pyinstaller, ruff, black)
- `src` レイアウト: ランタイムは `pyproject.toml` の `[tool.pytest.ini_options].pythonpath = ["src"]`、IDE は `pyrightconfig.json` の `extraPaths`、テストは `tests/conftest.py` で sys.path 注入
- 凍結中は `os.environ.setdefault("PYTHONUTF8", "1")` を `main.py` 先頭で設定済 (日本語パス対策)

## 主要コマンド

```sh
# 開発起動
./.venv/Scripts/python.exe -m stocker

# テスト (156 件)
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

### サムネイルセルのアスペクト比
ツールバーのコンボボックスで `1:1 | 4:3 | 16:9 | 3:4 | 9:16` から選択。`ThumbnailView._aspect_w/h` を保持し、`_apply_size()` で `thumb_w` を columns/viewport から決め、`thumb_h = round(thumb_w * ah / aw)` を `model.set_cell_size(w, h)` に渡す。`ThumbnailModel` は従来の正方形固定 `_target_size` から `_thumb_w / _thumb_h` の長方形対応に拡張、`SizeHintRole` も `QSize(thumb_w + 16, thumb_h + 32)` を返す。

サムネキャッシュキーの `target_size` は `max(thumb_w, thumb_h)` で派生 (= 長辺)。これにより:
- 横長アスペクト同士 (1:1 ↔ 16:9 ↔ 4:3) は同じ longest-side でキャッシュを使い回せる
- 縦長アスペクト (3:4 / 9:16) は cell_h が cell_w を上回るので longest-side が増え再生成、解像度が確保される

`set_target_size(size)` は後方互換のシムとして `set_cell_size(size, size)` に委譲。設定 `AppConfig.thumbnail_aspect: str` (デフォルト `"1:1"`)。

選択した比率と画像本来の比率が一致する場合のみセル全体が埋まる (Delegate 側は従来どおり `KeepAspectRatio` で描画)。混在時は元の比率を保ったまま余白が出る。

### 列数とセルサイズの計算 (`ThumbnailView._apply_size`)

指定した列数どおりに並べるため、**明示的な `setGridSize()`** でレイアウトを固定する。sizeHint + spacing 任せにすると Qt が自前で列数を決めてしまい、10 列指定なのに 11 個並ぶ、といったズレが出る。

Qt の折り返し規則 (グリッド有効時、実測):

```
1 行に入る個数 = (viewport_w - 1) // grid_w      # spacing は無関係
```

`- 1` は「右端にちょうど届くセルは折り返す」ため。したがって逆算は `stride_w = (viewport_w - 1) // columns` になる (下限は `MIN_THUMB + ITEM_MARGIN_W + CELL_GAP` = 68px。これを下回る幅では要求列数を満たせず自動的に列が減る)。

サイズの内訳:
- `stride_w` = グリッド幅 (セル間の刻み)
- `thumb_w = stride_w - ITEM_MARGIN_W(16) - CELL_GAP(4)`、`thumb_h = round(thumb_w * ah / aw)`
- 各アイテムの `SizeHintRole` は `QSize(thumb_w + 16, thumb_h + 32)` (= `stride - CELL_GAP`) なので、`CELL_GAP` の分だけセル同士が離れる

**垂直スクロールバーは常に幅を確保する** (`_layout_width()`)。バーの出現/消滅で viewport 幅が変わると stride が 1px ずれて列が 1 つ増減し、さらにセルサイズ変化がバーの出現条件を変えて発振する。隠れている間もバー幅を差し引くことで、どちらの状態でも同じ実効幅になり安定する。

回帰テストは `tests/test_thumbnail_view.py`。

### 列数のフォルダ別記憶
列数スライダーの値は **フォルダ単位で記憶**される。`AppConfig.folder_columns: dict[str, int]` にワークスペース相対パス (forward-slash、ワークスペース基点は `"."`、ごみ箱は `".trash"`) をキーとして保持。純粋ロジックは `core/folder_columns.py` (`folder_key` / `lookup` / `remember` / `rename_subtree` / `drop_subtree`) に分離し Qt なしでテスト可能。

- `MainWindow._on_columns_changed(n)` はグローバル `cfg.columns` (= 最後に使った値) に加えて `folder_columns[active_key] = n` を記録
- `_activate_folder()` 先頭の `_apply_folder_columns(root)` が記憶値を復元。**記憶がないフォルダは直前の表示列数を引き継ぐ** (`cfg.columns` フォールバック) ので、スライダーは記憶を持つフォルダに入ったときだけ動く。プログラム的なスライダー移動は `toolbar.blockSignals(True)` で囲み、復元値が「ユーザー操作」として再記録されるのを防ぐ
- フォルダリネーム時は `rename_subtree(old_rel, new_rel)` でサブツリーのキーを付け替え (trash_index の `rewrite_origin_paths` と同じ流儀)、フォルダ削除時は `drop_subtree(rel)` で掃除
- 相対キーなのでワークスペースをディスク上で移動しても記憶は生きる。別ワークスペースに切り替えた場合は同名相対パスがあれば流用される (意図的、害はない)
- `AppConfig.from_json` は壊れた形 (list / 非 int 値 / bool) を黙って捨てる
- テスト: `tests/test_folder_columns.py`

### ファイル名フィルタ (インクリメンタルサーチ)
ツールバーの「絞り込み」`QLineEdit` (180px 固定、clear ボタン付き) に文字を入れるたび `textChanged` → `_on_filter_changed()` → `proxy.setFilterFixedString(text)`。`Ctrl+F` で `_toolbar.focus_filter()` (フォーカス + selectAll)。

実装は `ThumbnailFilterProxy(QSortFilterProxyModel)` をビューとモデルの間に挟む方式 (`thumbnail_model.py` 末尾)。
- `setFilterCaseSensitivity(CaseInsensitive)` × `setFilterRole(DisplayRole)` で `FileItem.name` に対する大小無視の部分一致
- `sort(-1)` でソース順 (= `ThumbnailModel` のソート挿入結果) を維持。proxy 自前のソートは無効化
- `set_cell_size(w, h)` をソースに転送する override を持つので、`ThumbnailView._apply_size()` は proxy/source の差を意識せずそのまま `model.set_cell_size()` を呼べる

サブフォルダは構造的に対象外 ─ `ThumbnailModel` は元々 active root のアイテムしか持たない (非再帰スキャン由来)。フィルタは proxy なので、貼り付け完了 / FS Watcher / 移動 / 削除 / トラッシュ復元など全ての行追加・削除がフィルタを通して即時反映される (条件不一致なら自動的に非表示)。

フィルタ文字列は **永続化しない** (起動時に意図しない非表示状態が残るのを避けるため)。MainWindow は `self._model` (source) と `self._proxy` の両方を保持し、ビューには proxy をセット、それ以外の `_model.append_item()` 等は従来どおりソースに直接呼ぶ。`idx.data(ITEM_ROLE)` 経由の FileItem 取得・`mimeData()` での D&D・選択・コンテキストメニューはすべて proxy を透過して動作する。

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

### サイドバーのサブツリー一括展開/折りたたみ
フォルダ／ワークスペースノードの右クリックメニューに「ここからツリーを全て展開」「ここからツリーを全て閉じる」を追加 (子を持つノード限定で表示)。展開は Qt 標準の `QTreeView.expandRecursively(idx)` を使用、折りたたみは Qt に対応 API が無いので `Sidebar._collapse_recursively(idx)` を自前実装 (深さ優先で子→親の順に `collapse()`)。ごみ箱ノードは `kind != "folder"` かつ子無しなので自然に対象外。

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

### ログ表示行 (ステータスバー上)
ステータスバーの上に独立行として常設のログパネル (`src/stocker/ui/log_panel.py`) を追加。`MainWindow` のセントラルウィジェットを `QSplitter` 単体から `QVBoxLayout(QSplitter + LogPanel)` 包みに差し替えて挿入する (`setCentralWidget(center)`)。

- 折り畳み状態: 1 行表示で最新エントリ (`[HH:MM:SS] message`) のみ
- 展開状態: クリック (▸/▾ シェブロン or 行本体) で `QPlainTextEdit` を高さ 160px で開き、`deque[(ts, msg)]` (`MAX_HISTORY=500`) を上から下に流し込む。アプリ終了で消える (永続化なし)
- ON/OFF: ツールバー「ログ表示」チェックボックス (`AppConfig.log_panel_enabled`, default True)。OFF のときは `setVisible(False)` で隠すだけで `append()` は機能し続ける (再 ON で最新行から見える)
- ログ書式は i18n カタログの `log.move` / `log.copy` / `log.trash_op` / `log.undo_*` / `log.redo_*` を使用。フォルダ表示名は `_folder_log_label(p)` がワークスペース基点で正規化し、ワークスペース基点フォルダ自体は `tr("log.workspace_root")` (= "(ワークスペース)") に置換

### Undo / Redo (Ctrl+Z / Ctrl+Y)
`src/stocker/core/undo_manager.py` の `UndoManager` がスタック深さ 1 で `UndoEntry` を保持。新規 op の `record()` は redo を必ずクリアする (標準エディタ流儀)。Undo/Redo 対象は **移動・コピー・ごみ箱削除のみ**。貼り付け・リネーム・取り込みは undo 状態を触らない (= スタックを温存)。

`UndoEntry` は kind ごとに使うフィールドが異なる:
- `MOVE` / `COPY`: `src_root`, `dst_root`, `pairs: list[(src_rel, dst_rel)]`
- `TRASH`: `workspace`, `trashed_basenames` (undo 方向用) または `trash_sources: list[(file_abs, src_root)]` (redo 方向用)

undo/redo 実行時は `_perform_move_silently()` で perform_move + DB/モデル更新をプログレスダイアログ無しで回す (元の操作で既にダイアログを見ているため)。実行が成功した場合のみ inverse の entry を反対側に push する。

操作別の Undo の中身:
- **MOVE undo**: `dst_root/dst_rel` のファイルを `src_root` へ MOVE で戻す。avoid_collision で着地名が変わる可能性があるので `new_item.rel_path` を redo 用に保持
- **COPY undo**: ユーザー確認ダイアログ (`dialog.confirm_undo_copy_*`) を経て `dst_root/dst_rel` の**コピー側のみ**を `trash.move_to_trash` で削除。元ファイルは `src_root` に残るので redo は単純に再 COPY
- **TRASH undo**: `trash.restore(workspace, basenames)` で復元。`origin_folder_rel` から復元先を再構築 → 各 dst の DB 再 upsert + (active なら) モデル追加 + サイドバー件数更新。redo 用に `(restored_abs, origin_folder)` を保持
- **TRASH undo 失敗時のフォールバック**: ワークスペース未設定なら `dialog.undo_trash_no_workspace_*` でユーザーに「手動で復元してください」と案内。一部失敗時は `dialog.undo_trash_failed_*` で詳細を出す

複数 src フォルダにまたがる移動・コピーは単一 entry に符号化できないので `_undo_mgr.clear()` で undo を放棄する (ログだけは「(multiple) → B」で出る)。トラッシュは origin が個別記録されるので multi-source でも 1 entry にまとめられる。

ショートカット (`QShortcut(QKeySequence.StandardKey.Undo/Redo, self)`) はウィンドウスコープ。リネーム入力欄など子ウィジェット内では Qt が自前の Undo/Redo を優先するので衝突しない。

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
| `src/stocker/core/folder_columns.py` | 列数のフォルダ別記憶 (ワークスペース相対キー、リネーム/削除追従) |
| `src/stocker/core/paste_queue.py` | クリップボード貼り付けキュー (核心) |
| `src/stocker/core/clipboard_watcher.py` | Ctrl+V のブリッジ + 自動取込 (フィンガープリント dedup) |
| `src/stocker/core/thumbnail_cache.py` | LRU + ディスクキャッシュ協調 |
| `src/stocker/core/move_service.py` | フォルダ間移動/コピー (跨 DB トランザクション) |
| `src/stocker/core/undo_manager.py` | 1 世代のみの Undo/Redo コンテナ (移動・コピー・ごみ箱削除) |
| `src/stocker/core/rename_service.py` | ファイル単体リネーム (ディスク + DB を整合) |
| `src/stocker/core/trash.py` | ごみ箱 + 復元 + auto_purge + `rewrite_origin_paths` (フォルダリネーム追従) |
| `src/stocker/utils/clipboard_files.py` | Explorer 互換のファイル/画像コピー (Preferred DropEffect) |
| `src/stocker/ui/main_window.py` | UI 統括ハブ (~960 行) |
| `src/stocker/ui/toolbar.py` | ツールバー (列数/比率/ソート/絞り込み/貼り付け形式/自動取込/ホバー/アニメ再生/トレイ格納/ダークテーマ/ツリー字/ごみ箱/About) |
| `src/stocker/ui/sidebar.py` | ツリーサイドバー + D&D ハイライト + フォルダリネーム/削除 + フォルダ件数表示 + サブツリー一括展開/折りたたみ |
| `src/stocker/ui/theme.py` | Fusion + `QPalette` ベースのライト/ダーク切替、明示色のヘルパー (`drop_highlight_color`, `thumb_placeholder_color`) |
| `src/stocker/ui/thumbnail_view.py` | 仮想化 IconMode QListView |
| `src/stocker/ui/thumbnail_model.py` | QAbstractListModel + dedupe + mime + ソート位置挿入 (`set_sort` / `_sorted_insert_position`) + 長方形セル (`set_cell_size`) + ファイル名フィルタ proxy (`ThumbnailFilterProxy`) |
| `src/stocker/ui/hover_preview.py` | フローティングプレビュー (静止画 + アニメ GIF/WebP via QMovie) |
| `src/stocker/ui/log_panel.py` | ステータスバー上のログ行 (1 行表示 / クリックで履歴展開、メモリのみ) |
| `build/stocker.spec` | PyInstaller spec (icon 埋込・assets バンドル・15+ Qt サブモジュール除外) |
| `build/make_portable.ps1` | `pyinstaller` → `portable.flag` → `Compress-Archive` を一括実行 |

## テスト構成

`tests/` 配下、pytest-qt 使用。`conftest.py` が `src` を sys.path に注入。

- `test_metadata_db.py` (9): スキーマ、CRUD、bulk、ソート、日本語ファイル名
- `test_scanner.py` (6): 差分検出、非再帰、`.stocker` skip、`count_image_files` の走査範囲
- `test_thumbnail_cache.py` (6): LRU、500 件しきい値、SHA1 命名
- `test_thumbnail_model.py` (7): dedupe、PENDING → real リプレース、FS watcher 競合、ソート位置挿入 (name asc / mtime desc / paste 完了)
- `test_thumbnail_view.py` (55): 列数 × ビューポート幅の総当たりで 1 行の個数が指定列数と一致すること、グリッド stride が余分な列を許さないこと
- `test_paste_queue.py` (4): 30 件連打損失ゼロ、衝突回避
- `test_clipboard_watcher.py` (9): フィンガープリント dedup、autocapture トグル、自己コピー抑制、起動シード
- `test_move_service.py` (7): 同一/異ボリューム、衝突採番、進捗キャンセル、日本語
- `test_trash.py` (12): origin tracking、復元 (衝突/フォルダ消失含む)、auto_purge、index 整合性、フォルダリネーム後の origin 追従
- `test_folder_manager.py` (14): workspace 設定、subfolder 作成、hidden 除外、リネーム (workspace 拒否/不正名/衝突/外部拒否)、削除 (basic/workspace 拒否/外部拒否/非存在)
- `test_clipboard_files.py` (5): URL roundtrip、DropEffect バイト列確認、画像コピー
- `test_i18n.py` (8): ja/en 切替、format kwargs、未知キーフォールバック、`detect_language()` ホスト非依存
- `test_undo_manager.py` (7): 初期空、record で redo クリア、roundtrip、新 op で redo クリア、1 世代のみ、clear、count フィールド整合
- `test_folder_columns.py` (7): キー導出 (root/サブ/trash/外部)、clamp、リネーム prefix 付け替え、サブツリー削除、config roundtrip + 壊れた JSON の無害化

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
- `workspace_root`, `last_active_root`, `columns` (1〜16, 最後に使った値 = 記憶のないフォルダの初期値), `sort_key/dir`
- `folder_columns` (dict[str, int]) — フォルダ別の列数。キーはワークスペース相対パス (`"."` = 基点)
- `thumbnail_aspect` ("1:1"|"4:3"|"16:9"|"3:4"|"9:16", default "1:1") — サムネイルセルのアスペクト比
- `sidebar_font_size` (7〜28pt)
- `paste_format` ("png"|"jpeg"), `paste_jpeg_quality`
- `clipboard_autocapture` (bool, default False) — クリップボード自動取込の ON/OFF
- `hover_preview_enabled` (bool, default True) — ホバー拡大プレビューの ON/OFF
- `hover_preview_animate` (bool, default True) — 拡大プレビューでアニメ GIF/WebP を再生するか
- `minimize_to_tray` (bool, default False) — 最小化時にウィンドウをタスクトレイに格納する (× ボタンは通常終了)
- `theme` ("light"|"dark", default "light") — Fusion + `QPalette` でライト/ダーク切替
- `log_panel_enabled` (bool, default True) — ステータスバー上のログ行を表示するか
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
