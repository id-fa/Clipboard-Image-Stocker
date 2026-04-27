# Clipboard-Image-Stocker

軽量・高速な Eagle ライク画像管理ツール (Windows 11 / Python 3.12 + PySide6)。

## 主な機能

- **ワークスペースモデル**: 1 つの基点フォルダを選び、その配下のサブフォルダを管理対象とする（Eagle ライブラリ式）
- フォルダ内画像のサムネイルグリッド表示（仮想化リスト）
- 列数スライダー（**1〜16**）→ サムネイルサイズ自動調整
- Explorer 等からの D&D で取り込み
- **Ctrl+V で高速連続貼り付け**（メモリキューイング・取りこぼしゼロ）
- **クリップボード自動取込トグル**: ON にするとクリップボードに新規画像が来た瞬間に現在のフォルダへ自動保存（デフォルト OFF）
- 貼り付け保存形式の選択 (PNG / JPEG)
- アプリ外への D&D（Explorer 等）
- ファイル名 SQLite DB による起動高速化
- ファイル名 / 更新日時 / 追加日時ソート
- F2 リネーム
- ホバー (0.5 秒) で画面サイズフィットの拡大プレビュー（**ツールバーのトグルで ON/OFF**）
- ダブルクリックで関連付けビューア起動
- **サイドバーにワークスペース＋サブフォルダのツリー** + ごみ箱ノード
- ツリーフォントサイズ調整 (7〜28 pt)
- **管理フォルダ間で複数ファイル一括移動** (D&D + 右クリックメニュー)
- **D&D 中はターゲットフォルダがハイライト**されるので落下先が一目瞭然
- **ごみ箱フォルダ** (`<workspace>/.trash/`) と N 日経過後の自動削除（0 で無効）
- **ごみ箱からの復元** (削除元フォルダ情報を `.stocker/trash_index.json` に保持)
- 右クリック「画像をコピー」(QImage) / 「ファイルをコピー」(Explorer 互換、**Ctrl+C ショートカット**)
- Ctrl+V でクリップボード上のファイルも取り込み可能
- **Ctrl + ドラッグ&ドロップ**でフォルダ間コピー（デフォルトは移動）

## 開発セットアップ

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
python -m stocker
```

## テスト

```powershell
pytest
```

## ポータブル zip ビルド

```powershell
pyinstaller --clean build/stocker.spec
.\build\make_portable.ps1
```

## 既知の制約

### X (Twitter) への D&D は不可、Ctrl+C → Ctrl+V で代用

X (Twitter) の Web UI のドロップハンドラは `e.dataTransfer.files` だけでなく
`UniformResourceLocator` / `CF_HTML` 等の URL 系クリップボード形式も「添付候補」として
カウントするため、Stocker から複数枚を D&D すると 3 枚以上で
「添付できる画像は4枚までです」エラーが出てドロップ自体が失敗します。

これは Qt 6 が `setUrls()` 系 API 経由で複数の Windows クリップボード形式
(`CF_HDROP` + `UniformResourceLocator` + `UniformResourceLocatorW` + `CF_HTML`) を
自動登録する挙動と、Twitter のドロップハンドラの厳しいカウント方式が組み合わさった結果で、
`QMimeData` サブクラスの override では抑制できません (Qt の Windows 層は
内部データを直接見るため)。抜本対策には自前の `IDataObject` + `DoDragDrop`
実装が必要です。

**回避策**: グリッド上で画像を選択して **Ctrl+C** (= 「ファイルをコピー」) → Twitter の
投稿欄で **Ctrl+V**。クリップボード経路では同じ複数形式が登録されますが、Twitter の
ペーストハンドラは `e.clipboardData.files` (CF_HDROP) のみを使うので 4 枚まで正常に
添付できます。Discord / Slack / GitHub / Gmail 等 D&D で問題が出ない先では従来どおり
ドラッグ可能です。
