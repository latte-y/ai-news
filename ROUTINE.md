# ROUTINE — AI新聞 毎朝の号作成手順

このファイルは、毎朝 JST 6:30 頃にクラウドで自動実行される Claude Code セッション（routine）が
そのまま従うための完全な作業指示書です。人間の介入なしに、この手順だけで
`data/issues/YYYY-MM-DD.json` を作成し、検証を通し、コミット・pushするところまで完結させてください。

**重要な制約**: このリポジトリのコードに LLM/Claude API を呼び出す処理を追加してはいけません。
記事の選定・重要度判定・翻訳・要約は、このroutineセッション自身（あなた自身の読解・判断）が
対話的に行います。`src/` 配下のPythonスクリプトは収集・検証・ビルド・通知だけを行う既存のツールで、
変更しないでください（バグを見つけた場合を除く）。

## 0. 前提確認

- 作業ディレクトリはこのリポジトリのルート（`SPEC.md`, `ROUTINE.md` がある場所）
- Python仮想環境: `venv/` が無ければ作成し、`requirements.txt` をインストール
  ```bash
  test -d venv || python3 -m venv venv
  source venv/bin/activate
  pip install -q -r requirements.txt
  ```
- 現在のJST日付を確認する（`date -u -d '+9 hours' +%Y-%m-%d` 等。以下 `TODAY` と呼ぶ）
- `git pull` して最新のmainを取得しておく

## 1. 候補収集

```bash
source venv/bin/activate
python -m src.collect
```

- `data/candidates/TODAY.json` が生成される。標準出力に情報源ごとの件数が出るので確認する
- あるフィードの取得に失敗していても（警告ログが出るだけ）処理は止まらない。全体の候補件数が
  極端に少ない（0件など）場合のみ、`config/sources.yaml` のURLが生きているか手動で疑う

## 2. 候補を読み、編集方針に沿って選定する

`data/candidates/TODAY.json` の `candidates` 配列を全て読む。各候補は
`{title, url, source, lang, published_at, summary}` を持つ（summaryはRSSのdescriptionを
機械的に切り詰めただけの粗い要約なので、これだけで採否や重要度を断定しない）。

### 編集方針（SPEC.mdより）

- **程よいバランスで、影響が大きいものを優先する。** 特定テーマ（例: 1社のリリースばかり）に
  偏らないよう、セクション（top/models/tools/cloud/industry/research/japan）に目を配る
- **同一話題は1件に統合する。** 複数の情報源が同じニュースを報じている場合は、最も一次情報に
  近いもの（公式ブログ・リリースノート本体）を `source_name`/`source_url` に採用し、他は捨てる
- **一次情報を優先する。** 公式ブログやリリースノートが取れるなら、それを取材した二次記事より
  優先する。候補の `summary` だけで内容や重要度を判断できない場合は、`source_url`（または
  そのニュースの一次情報のURL）を実際に取得して確認してから記事を書く。取得方法は
  WebFetchツールや `curl` 等、その時点で使える手段でよい
- **事実と推測を区別する。** `why_it_matters` で推測を書く場合は「〜と考えられる」「〜の可能性がある」
  など推測とわかる表現にする。未確認の情報を断定的に書かない
- **無理に水増ししない。** 重要な記事が少ない日は、最低5件まで減らしてよい（無理に埋めない）

### 記事ごとに作成する情報

各採用記事について、日本語で以下を作成する（自分の言葉で書く。原文の直訳・全文転載はしない。
著作権配慮のため要約は短く、必ず出典名と元URLを明記する）:

- `section`: `top | models | tools | cloud | industry | research | japan` のいずれか
- `importance`: 1〜5の整数。`section: top` の記事は必ず `importance: 5`
- `title`: 日本語見出し（40字以内）
- `summary`: 日本語要約（2〜4文、事実のみ。推測を混ぜない）
- `why_it_matters`: なぜ重要かを1文で（推測は推測とわかる表現で）
- `tags`: 短いタグの配列（例: `["Claude", "API"]`）
- `source_name`: 出典名（例: `"Anthropic"`）
- `source_url`: 元記事の正規URL
- `original_title`: 元記事のタイトル（原文のまま、翻訳しない）
- `original_lang`: `en | ja`
- `published_at`: ISO8601（例: `"2026-09-29T17:00:00Z"`）。候補データの `published_at` を使う

### 号全体の情報

- `date`: `TODAY`（`YYYY-MM-DD`）
- `generated_at`: 作業完了時点のJST時刻をISO8601で（例: `"2026-09-30T06:41:00+09:00"`）
- `headline`: 今日を一言で表す見出し（25字以内）
- `lead`: 今日の総括（2〜3文）
- `articles`: 上記の記事オブジェクトの配列。**8〜15件**（`top` は **1〜3件**、全て `importance: 5`）。
  やむを得ない場合は最低5件まで減らしてよい

## 3. 号データを書く

`data/issues/TODAY.json` に、SPEC.mdのスキーマ通りのJSONを書く。既存の号
（`data/issues/*.json`）を1つ開いて構造を参考にしてよい（最初の号の場合は
`tests/fixtures/sample_issue.json` を参考にする。ただしこれはサンプルなので中身はコピーしない）。

## 4. 検証する

```bash
python -m src.validate data/issues/TODAY.json
```

- 失敗したら、出力されたエラーメッセージ（不足キー・enum不正・件数不正・URL形式不正など）に従って
  `data/issues/TODAY.json` を直し、再度検証する。**これが通るまで次のステップに進まない**

## 5. ローカルで見た目を確認する（任意だが推奨）

```bash
python -m src.build --data-dir data --out-dir /tmp/ai-news-preview
```

生成された `/tmp/ai-news-preview/index.html` 等を見て、見出し・要約・リンクに明らかな崩れが
無いか確認する（このディレクトリはリポジトリ外なのでコミット対象にはならない）。

## 6. コミット・push

```bash
git add data/issues/TODAY.json
git commit -m "issue: TODAY"
git push origin main
```

- `TODAY` は実際の日付（例: `issue: 2026-09-30`）に置き換える
- `data/candidates/TODAY.json` はコミットしない（`.gitignore` 対象。手元の作業用データ）
- pushすると `.github/workflows/publish.yml` が起動し、サイトのビルド・公開・新規号メール通知が
  自動で行われる（このroutine自身はメール送信やビルドを行わない）

## 7. 失敗時の扱い

- 手順1〜4のいずれかで解決できない問題が起きた場合、無理に号を作らず、そこで作業を終えてよい
  （何もpushしない）。号が出ない日があっても、`.github/workflows/watchdog.yml` が
  7:30 JST に当日号の有無を確認し、無ければアラートメールを送るので、無理は禁物
- 絶対にやってはいけないこと: スキーマを満たすためだけに事実と異なる内容を書く、
  出典URLを実在しないものにする、`src/validate.py` の検証ロジックを緩めて通す
