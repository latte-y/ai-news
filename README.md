# AI新聞

毎朝 JST 7:00 頃に「影響が大きいAIニュース」を日本語の新聞形式で届けるアプリです。
スマホ・PC両対応のWebサイト（GitHub Pages）と、Gmail通知（トップ3見出し＋サイトへのリンク）の
2つの形で配信します。

サイトURL: https://latte-y.github.io/ai-news/

詳細な仕様は [`SPEC.md`](SPEC.md)、毎朝の号作成手順は [`ROUTINE.md`](ROUTINE.md) を参照してください。

## 概要・全体アーキテクチャ

```
[Claude Code 定期実行（クラウド routine, 毎朝 6:30 JST 頃）]  ← Claude API は使わない（プラン枠内）
  1. python -m src.collect           … RSS巡回 → data/candidates/YYYY-MM-DD.json
  2. ROUTINE.md の指示に従い候補を編集 … 選定・重要度判定・翻訳・要約
  3. data/issues/YYYY-MM-DD.json を書く
  4. python -m src.validate <file>   … スキーマ検証（失敗したら直して再検証）
  5. commit & push
        │ push（data/issues/** の変更）
        ▼
[GitHub Actions: publish.yml]
  1. python -m src.build   … data/issues/*.json → site/（静的HTML）
  2. actions/deploy-pages  … GitHub Pages へ公開
  3. python -m src.notify  … 新しく追加された号があれば Gmail 送信
        │
        ▼ （別スケジュール, 7:35 JST）
[GitHub Actions: watchdog.yml]
  当日の号が無ければ「未生成」アラートをGmailで送信
```

**このリポジトリのコードは LLM/Claude APIを一切呼び出しません。** 記事の選定・重要度判定・
翻訳・要約は、毎朝クラウドで実行されるClaude Codeのroutineセッション自身が対話的に行い、
その結果（`data/issues/YYYY-MM-DD.json`）だけがこのリポジトリに残ります。

## ディレクトリ構成

```
config/sources.yaml     情報源（RSS/Atomフィード）の定義
src/collect.py          RSS巡回 → data/candidates/YYYY-MM-DD.json
src/images.py           号データの画像補完（og:image / twitter:image）
src/validate.py         data/issues/YYYY-MM-DD.json のスキーマ検証
src/build.py            data/issues/*.json → site/ の静的サイト生成
src/notify.py           新規号のGmail通知・watchdogアラート
src/mailer.py           Gmail SMTP_SSL送信（stock-alertと同方式）
src/util.py             JST日時・URL正規化などの共通処理
templates/              Jinja2テンプレート（サイト・メール）
static/assets/          CSS等の静的ファイル
data/issues/            号データ本体（.gitkeepのみコミット、実データはroutineが追加）
data/candidates/        収集した候補（.gitkeepのみコミット、コミット対象外）
tests/                  pytest（fixtureのみ、ネットワークアクセス無し）
.github/workflows/      publish.yml（サイト公開・通知）, watchdog.yml（当日号チェック）
ROUTINE.md              毎朝のroutineセッションが従う作業手順書
```

## 号データのスキーマ

`data/issues/YYYY-MM-DD.json` の形式は [`SPEC.md`](SPEC.md) の「号データのスキーマ」節を参照してください。
`src/validate.py` が以下を検証します。

- 必須キーの有無、`section`/`original_lang` のenum値
- `articles` は8〜15件（`top` セクションは1〜3件、全て `importance: 5`）
- `date` がファイル名と一致していること、`source_url` がURL形式であること・号内で重複しないこと
- `headline`（25字以内）・`title`（40字以内）・`summary`（120字以内）の文字数制限
- 任意の `image_url`（httpsのみ）と `image_credit`（`image_url` があれば必須）

### 画像

記事のサムネイルは元サイトの画像URLを参照するだけで、画像ファイルは保存・複製しません
（`画像: 出典名` を必ず表示し、画像自体も元記事へのリンクです）。収集時にRSSから取れた画像URLが候補の
`image_url` に入り、足りない分は `python -m src.images data/issues/YYYY-MM-DD.json` が
元記事の og:image / twitter:image から補完します。画像が無い記事は画像枠を出しません。

## ローカル実行手順

Python 3.11を想定しています（開発環境の都合でPython 3.13でも動作確認済みです）。

```bash
cd ai-news
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 1. 候補収集

```bash
python -m src.collect
# data/candidates/<今日の日付>.json が生成される
```

`--date YYYY-MM-DD` で基準日時を指定でき、`--data-dir` で出力先を変更できます（テスト用）。

### 2. 号データの検証

```bash
python -m src.validate data/issues/2026-09-29.json
```

### 3. サイトのビルド

```bash
python -m src.build --data-dir data --out-dir site
open site/index.html   # macOSの場合。CSSの相対パスを正しく確認するには
python3 -m http.server 8000 --directory site  # 等でローカルサーバー越しに見るのを推奨
```

サンプルデータ（`tests/fixtures/sample_issue.json`）だけでビルドを試したい場合:

```bash
mkdir -p /tmp/ai-news-sample/issues
cp tests/fixtures/sample_issue.json /tmp/ai-news-sample/issues/2026-09-29.json
python -m src.build --data-dir /tmp/ai-news-sample --out-dir site
```

### 4. 通知メールのプレビュー（送信なし）

```bash
DRY_RUN=1 python -m src.notify --dry-run --data-dir data
# out/email_preview.html が生成される（ブラウザで開いて確認）
```

実際に送信する場合は `GMAIL_APP_PASSWORD` 環境変数が必要です（後述）。

### テストの実行

```bash
python -m pytest tests/ -q
```

## 情報源（config/sources.yaml）

候補として試し、実際にHTTP 200・feedparserでのエントリ取得（1件以上）を確認できたフィードのみ
採用しています。以下は検証時に除外した候補と理由です。

- **Anthropic公式RSS**: `anthropic.com/rss.xml` 等、複数のURLパターンを試しましたがいずれも404で、
  公式に一般公開されているRSS/Atomフィードが見当たりませんでした。スクレイピングは行わず、
  公式フィードが用意され次第 `config/sources.yaml` に追加してください
- **Microsoft AI Blog**（`blogs.microsoft.com/ai/feed/`）: HTTP 410（Gone）。ブログ自体が終了/移転した
  もようです。代わりに Azure AI Blog を採用しています

その他、The Verge・ITmedia AI+ は当初想定していたURLが404だったため、実際に存在する別パスの
フィードに差し替えています（詳細はコミット履歴・`config/sources.yaml` のコメント参照）。

## GitHub Pages・シークレットのセットアップ

### 1. リポジトリを作成してpush

```bash
gh repo create latte-y/ai-news --public --source=. --push
```

（このリポジトリの作成・commit・push自体はユーザー側で行う想定です。ROUTINE.md実行前に
一度手動でリポジトリを作成し、GitHub Pagesの設定まで済ませてください）

### 2. GitHub Pagesを有効化

リポジトリの `Settings` → `Pages` → `Build and deployment` の `Source` を
**GitHub Actions** に設定します（`publish.yml` が `actions/deploy-pages` で公開するため）。

### 3. Gmailアプリパスワードを発行する

1. [Googleアカウント → セキュリティ](https://myaccount.google.com/security) で2段階認証を有効化
2. [https://myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords) でアプリパスワードを発行
3. 表示された16桁のパスワードを控える

### 4. GitHubリポジトリにシークレットを登録する

| シークレット名 | 値 | 必須 |
|---|---|---|
| `GMAIL_APP_PASSWORD` | 手順3で発行した16桁のアプリパスワード | 必須 |
| `GMAIL_USER` | 送信元のGmailアドレス（publicリポジトリのためコードには書かない） | 必須 |
| `MAIL_TO` | 通知の送信先アドレス（省略時は `GMAIL_USER` と同じ） | 任意 |

```bash
gh secret set GMAIL_APP_PASSWORD --body "xxxxxxxxxxxxxxxx"
gh secret set MAIL_TO --body "your-address@example.com"   # 任意
```

### 5. 毎朝のroutineをセットアップする

[`ROUTINE.md`](ROUTINE.md) に記載した手順を、毎朝 JST 6:30 頃にClaude Codeのクラウド定期実行
（scheduled task / routine）として登録してください。routineは収集→編集→検証→push までを行い、
push後は `publish.yml`（サイト公開・通知）と `watchdog.yml`（当日号チェック、7:35 JST）が
自動で動きます。

### 6. 動作確認

- `Actions` タブから `サイト公開（AI新聞）` を `workflow_dispatch` で手動実行し、Pagesへの
  デプロイが通ることを確認する（この実行では新規号メール通知は行われません）
- `当日号の生成チェック（watchdog）` も手動実行し、正常時・当日号なし時それぞれで
  期待通りの挙動になることを確認する

## 著作権への配慮

各記事は出典名・元記事URL・原題を必ず表示し、全文翻訳や長文の引用は行わず、要約は自分の言葉で
短くまとめています（`src/validate.py` はこれを強制はしませんが、`ROUTINE.md` の編集方針に
明記しています）。
