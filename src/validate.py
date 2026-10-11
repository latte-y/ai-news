"""号データ（data/issues/YYYY-MM-DD.json）のスキーマ検証。

`python -m src.validate <file>` で実行する。問題があれば標準エラーに列挙して
終了コード1を返す。ROUTINE.mdはこれが通るまで号データを直す。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

SECTIONS = {"top", "models", "tools", "cloud", "industry", "research", "japan"}
LANGS = {"en", "ja"}
REQUIRED_ISSUE_KEYS = {"date", "generated_at", "headline", "lead", "articles"}
REQUIRED_ARTICLE_KEYS = {
    "section",
    "importance",
    "title",
    "summary",
    "why_it_matters",
    "detail",
    "tags",
    "source_name",
    "source_url",
    "original_title",
    "original_lang",
    "published_at",
}
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
ISO_DATETIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:?\d{2})$")

MIN_ARTICLES = 5
MAX_ARTICLES = 15
MAX_HEADLINE_LEN = 25
MAX_TITLE_LEN = 40
MAX_SUMMARY_LEN = 120
#: 詳しい説明（detail）の字数範囲。一覧では折りたたみ表示
MIN_DETAIL_LEN = 150
MAX_DETAIL_LEN = 400
MIN_TOP = 1
MAX_TOP = 3


def validate_issue(issue: dict, expected_date: str | None = None) -> list[str]:
    """号データの内容を検証し、エラーメッセージのリストを返す（空なら合格）。"""
    errors: list[str] = []

    missing = REQUIRED_ISSUE_KEYS - issue.keys()
    if missing:
        errors.append(f"号データの必須キーが不足: {sorted(missing)}")
        return errors  # 以降の検証が意味を成さないためここで打ち切る

    date = issue["date"]
    if not isinstance(date, str) or not DATE_RE.match(date):
        errors.append(f"date形式が不正: {date!r}（YYYY-MM-DD形式で指定）")
    elif expected_date and date != expected_date:
        errors.append(f"dateがファイル名と不一致: date={date!r} だがファイル名は {expected_date!r}")

    generated_at = issue["generated_at"]
    if not isinstance(generated_at, str) or not ISO_DATETIME_RE.match(generated_at):
        errors.append(f"generated_at がISO8601形式ではない: {generated_at!r}")

    headline = issue["headline"]
    if not isinstance(headline, str) or not headline.strip():
        errors.append("headlineが空")
    elif len(headline) > MAX_HEADLINE_LEN:
        errors.append(f"headlineが{MAX_HEADLINE_LEN}字を超過（{len(headline)}字）: {headline!r}")

    lead = issue["lead"]
    if not isinstance(lead, str) or not lead.strip():
        errors.append("leadが空")

    articles = issue["articles"]
    if not isinstance(articles, list):
        errors.append("articlesがリストではない")
        return errors

    n = len(articles)
    if not (MIN_ARTICLES <= n <= MAX_ARTICLES):
        errors.append(f"articles件数が範囲外: {n}件（{MIN_ARTICLES}〜{MAX_ARTICLES}件が必要）")

    top_count = 0
    seen_urls: set[str] = set()
    for i, art in enumerate(articles):
        prefix = f"articles[{i}]"
        if not isinstance(art, dict):
            errors.append(f"{prefix}: dictではない")
            continue
        art_missing = REQUIRED_ARTICLE_KEYS - art.keys()
        if art_missing:
            errors.append(f"{prefix}: 必須キー不足 {sorted(art_missing)}")
            continue

        section = art["section"]
        if section not in SECTIONS:
            errors.append(f"{prefix}: section不正 {section!r}（{sorted(SECTIONS)}のいずれか）")
        if section == "top":
            top_count += 1

        importance = art["importance"]
        if not isinstance(importance, int) or not (1 <= importance <= 5):
            errors.append(f"{prefix}: importanceは1〜5の整数である必要がある: {importance!r}")
        if section == "top" and importance != 5:
            errors.append(f"{prefix}: sectionがtopならimportanceは5である必要がある: {importance!r}")

        title = art["title"]
        if not isinstance(title, str) or not title.strip():
            errors.append(f"{prefix}: titleが空")
        elif len(title) > MAX_TITLE_LEN:
            errors.append(f"{prefix}: titleが{MAX_TITLE_LEN}字を超過（{len(title)}字）: {title!r}")

        for key in ("summary", "detail", "why_it_matters", "source_name", "original_title"):
            if not isinstance(art.get(key), str) or not art[key].strip():
                errors.append(f"{prefix}: {key}が空")
        summary = art["summary"]
        if isinstance(summary, str) and len(summary) > MAX_SUMMARY_LEN:
            errors.append(f"{prefix}: summaryが{MAX_SUMMARY_LEN}字を超過（{len(summary)}字）: {summary!r}")
        detail = art.get("detail")
        if isinstance(detail, str) and detail.strip() and not (MIN_DETAIL_LEN <= len(detail) <= MAX_DETAIL_LEN):
            errors.append(f"{prefix}: detailは{MIN_DETAIL_LEN}〜{MAX_DETAIL_LEN}字にする（現在{len(detail)}字）")

        # 画像（任意）: image_urlはhttpsのみ、image_urlがあればimage_creditも必須
        if "image_url" in art:
            image_url = art["image_url"]
            iparsed = urlparse(image_url) if isinstance(image_url, str) else None
            if not iparsed or iparsed.scheme != "https" or not iparsed.netloc:
                errors.append(f"{prefix}: image_urlはhttpsのURLである必要がある: {image_url!r}")
            credit = art.get("image_credit")
            if not isinstance(credit, str) or not credit.strip():
                errors.append(f"{prefix}: image_urlがある場合はimage_credit（空でない文字列）が必要")
        elif "image_credit" in art:
            credit = art["image_credit"]
            if not isinstance(credit, str) or not credit.strip():
                errors.append(f"{prefix}: image_creditが空")

        tags = art["tags"]
        if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
            errors.append(f"{prefix}: tagsは文字列のリストである必要がある: {tags!r}")

        source_url = art["source_url"]
        parsed = urlparse(source_url) if isinstance(source_url, str) else None
        if not parsed or parsed.scheme not in ("http", "https") or not parsed.netloc:
            errors.append(f"{prefix}: source_urlがURL形式ではない: {source_url!r}")
        elif source_url in seen_urls:
            errors.append(f"{prefix}: source_urlが号内で重複: {source_url!r}")
        else:
            seen_urls.add(source_url)

        original_lang = art["original_lang"]
        if original_lang not in LANGS:
            errors.append(f"{prefix}: original_lang不正 {original_lang!r}（en/ja）")

        published_at = art["published_at"]
        if not isinstance(published_at, str) or not ISO_DATETIME_RE.match(published_at):
            errors.append(f"{prefix}: published_atがISO8601形式ではない: {published_at!r}")

    if not (MIN_TOP <= top_count <= MAX_TOP):
        errors.append(f"topセクションの件数が範囲外: {top_count}件（{MIN_TOP}〜{MAX_TOP}件が必要）")

    return errors


def validate_file(path: Path) -> list[str]:
    """ファイルを読み込んで検証する。JSON自体が壊れている場合もエラーを返す。"""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as e:
        return [f"ファイルを読み込めない: {e}"]
    try:
        issue = json.loads(raw)
    except json.JSONDecodeError as e:
        return [f"JSONとして不正: {e}"]

    expected_date = None
    m = DATE_RE.match(path.stem)
    if m:
        expected_date = path.stem
    return validate_issue(issue, expected_date=expected_date)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AI新聞: 号データのスキーマ検証")
    parser.add_argument("file", help="検証するdata/issues/YYYY-MM-DD.jsonのパス")
    args = parser.parse_args(argv)

    path = Path(args.file)
    if not path.exists():
        print(f"エラー: ファイルが存在しません: {path}", file=sys.stderr)
        return 1

    errors = validate_file(path)
    if errors:
        print(f"検証失敗: {path}（{len(errors)}件のエラー）", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1

    print(f"検証OK: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
