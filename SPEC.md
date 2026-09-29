# AI新聞 — 仕様

毎朝 7:00 JST に「影響が大きいAIニュース」を日本語の新聞形式で届ける。
スマホ・PC両対応のWebサイト（GitHub Pages）＋ Gmail 通知（トップ3＋サイトへのリンク）。

## アーキテクチャ

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
```

- リポジトリ: `latte-y/ai-news`（public）。秘密情報は Actions Secrets のみ（`GMAIL_APP_PASSWORD`, 任意で `MAIL_TO`）
- Python 3.11、依存は最小（feedparser, Jinja2, PyYAML, requests, pytest）
- LLM呼び出しコードはリポジトリに一切含めない。翻訳・要約は routine 内の Claude Code が行う

## 収集（src/collect.py）

- 情報源は `config/sources.yaml` に集約（name, url, lang, kind: official|media|community|japan, weight）
- 直近 36 時間の記事を取得。過去 7 日分の `data/issues/*.json` に載った URL は除外（重複配信防止）
- URL正規化（utm_* 等のクエリ除去、末尾スラッシュ統一）で重複排除
- 候補ごとに title, url, source, lang, published_at, summary（RSS の description をタグ除去して最大 600 字）を出力
- 1フィードの失敗で全体を止めない（ログに警告を出して続行）。候補は最大 150 件（新しい順・weight 考慮）
- Hacker News はポイント閾値つき（例: hnrss の points>=150）で AI 関連キーワードを含むものに限定

## 号データのスキーマ（data/issues/YYYY-MM-DD.json）

```json
{
  "date": "2026-09-30",
  "generated_at": "2026-09-30T06:41:00+09:00",
  "headline": "今日を一言で表す見出し（25字以内）",
  "lead": "今日の総括（2〜3文）",
  "articles": [
    {
      "section": "top | models | tools | cloud | industry | research | japan",
      "importance": 5,
      "title": "日本語見出し（40字以内）",
      "summary": "日本語要約（2〜4文、事実のみ）",
      "why_it_matters": "なぜ重要か（1文。推測は推測と分かる表現で）",
      "tags": ["Claude", "API"],
      "source_name": "Anthropic",
      "source_url": "https://...",
      "original_title": "元記事タイトル（原文のまま）",
      "original_lang": "en | ja",
      "published_at": "2026-09-29T17:00:00Z"
    }
  ]
}
```

- セクション表示名: top=トップ / models=モデル・API / tools=開発ツール / cloud=クラウド・データ基盤 / industry=業界・政策 / research=研究 / japan=国内
- 記事数 8〜15。`top` は 1〜3 件（importance 5 のもの）
- `src/validate.py` が上記を検証（必須キー、enum、件数、URL形式、日付＝ファイル名）
- 著作権配慮: 全文翻訳は載せない。要約は自分の言葉で短く、必ず出典名と元URLを表示

## 編集方針（ROUTINE.md に記述、routine が従う）

- 「程よいバランスで、影響が大きいものを優先」。テーマの偏りを避け、同一話題は1件に統合（複数出典があれば最も一次に近いものを source に）
- 一次情報（公式ブログ・リリースノート）を優先。候補の summary だけで判断できないものは元記事を取得して確認
- 事実と推測を区別する。未確認情報を断定しない
- 重要な記事がない日は無理に水増ししない（最低 5 件まで減らしてよい）

## サイト（src/build.py → site/）

- `index.html` = 最新号、`issues/YYYY-MM-DD.html` = 各号、`archive.html` = バックナンバー一覧
- 新聞的レイアウト: 題字（AI新聞＋日付）→ 見出し＋リード → トップ記事（大）→ セクション別記事
- デザイン: Apple 的（システムフォント `-apple-system, BlinkMacSystemFont, "Hiragino Sans", "Noto Sans JP", sans-serif`、控えめな装飾、大きめ角丸、柔らかい影）。個性的な Web フォントは使わない
- スマホ（375px）〜PC で崩れない。ライト/ダーク自動対応。外部 JS なし
- 各記事: 重要度、セクション、見出し、要約、なぜ重要か、タグ、出典（出典名＋元記事リンク＋原題）
- OGP/タイトル/ favicon（絵文字 SVG で可）

## 通知（src/notify.py）

- その push で新規追加された号がある場合のみ送信（手動再ビルドでは送らない。`--force` で強制）
- 件名: `【AI新聞】M/D 見出し`
- 本文: HTMLメール（インライン CSS、テーブルレイアウトでGmail/スマホ対応）。見出し・リード・トップ3（見出し＋要約1文＋出典リンク）＋「紙面を読む」ボタン（サイトURL）
- 送信方式は stock-alert と同じ Gmail SMTP_SSL 465

## 運用

- routine 失敗時は号が出ないだけ（Actions は何もしない）。7:30 に `watchdog` ジョブで当日号がなければ「今日の号は未生成」とメール通知
- サイト URL: `https://latte-y.github.io/ai-news/`
