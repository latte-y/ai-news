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
- スマホ（375px）〜PC で崩れない。ライト/ダーク自動対応（※v2で「ライトのみ・新聞調」に変更、下記参照）。外部 JS なし
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

## v2: 画像と読みやすさ（2026-10-03 追加）

背景: 初号を見たユーザーから「文字ばかりで疲れる」。元記事のサムネイルを入れ、文字量を減らす。

### 画像
- 号スキーマに任意フィールドを追加: `image_url`（https のみ）, `image_credit`（画像の出どころのサイト名）
- 収集: `collect.py` が RSS から画像URLを取る（media:content / media:thumbnail / image系 enclosure / summary・content 内の最初の `<img>`）→ 候補に `image_url`
- 補完: 新規 `python -m src.images data/issues/YYYY-MM-DD.json` … `image_url` が無い記事について `source_url` の HTML から og:image → twitter:image の順で取得し、`image_url` と `image_credit`（=source_name）を書き込む。取得失敗は無視（画像なしのまま）。タイムアウト 8 秒/件、User-Agent 付き、相対URLは絶対化、https 以外は捨てる
- routine の手順: 記事採用時、候補に `image_url` があればコピーし `image_credit` に候補の source を入れる → 号を書いた後 `src.images` で残りを補完 → validate
- 著作権: 画像は複製・保存しない。元サイトから直接読み込む（リンクプレビューと同じ扱い）。必ず出典表示（`画像: {image_credit}`）を添え、画像自体も元記事へのリンクにする
- 表示: `loading="lazy"`, `referrerpolicy="no-referrer"`, `decoding="async"`, 固定アスペクト比（トップ 16:9、カード 1:1 の小サムネ）で読み込み時のレイアウトずれを防ぐ。読み込み失敗時は画像枠ごと消す（インライン onerror の最小 JS のみ許可）
- 画像のない記事はサムネ枠を出さない（プレースホルダ画像は使わない）

### 文字量を減らす
- `summary` は 1〜2 文・120 字以内（validate で上限チェック）。`title` は 40 字以内のまま
- セクション記事カードの「なぜ重要か」は `<details>` で折りたたみ（トップ記事は表示したまま）
- タグ表示はカードでは最大 3 個

### レイアウト
- トップ記事: 画像（16:9、カード幅いっぱい、上角丸）→ 見出し → 要約 → なぜ重要か → 出典
- セクション記事: 見出し＋要約の右に 88px 角のサムネ（スマホでも右配置、テキストは折り返す）
- メール: トップ3それぞれに画像（幅 100%、高さ自動、インライン CSS）。画像なしなら省略

### 新聞調デザイン（2026-10-03 追加）
- 白基調・ライトのみ（ダークモード対応は廃止）。影・色付きカード・大きな角丸は使わず、細罫/太罫/段罫で構造化。見出しはシステム明朝体、本文はシステムゴシック体（Webフォント不使用）。題字は中央「AI新聞」＋二重罫＋日付・第N号。トップは1位を大きく、2〜3位を右カラム（モバイルは下）に配置。メールも同じ白基調

## v3: 詳しい説明（2026-10-11 追加）

背景: 「もう少し記事の説明を増やしたい」。ただし v2 の「文字ばかりで疲れる」と両立させるため、一覧は短いまま、説明は折りたたみで足す。

- 号スキーマに必須フィールド `detail`（3〜6文・150〜400字）を追加。内容は 背景／何が新しいか（機能・数字・価格・提供範囲・時期）／使う側にとって何が変わるか。一次情報で確認できた事実のみ。`summary` の繰り返しにしない
- 表示: トップ記事は `detail` を常時表示。セクション記事は `<details>`「詳しく読む」の中に `detail` と「なぜ重要か」を入れる。`detail` の無い過去の号は従来どおり「なぜ重要か」のみ
- メールは変更なし（トップ3の見出し・要約1文・画像・リンク）
- routine の「今日」は必ず `TZ=Asia/Tokyo date +%Y-%m-%d`。routine は UTC 前日 21:30 頃に起動するため、UTC 日付で判断すると号を作らずに終わる（10/6・10/11 に実際に発生）
