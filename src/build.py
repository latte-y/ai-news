"""号データ（data/issues/*.json）から静的サイト（site/）を生成する。

- index.html      = 最新号
- issues/<date>.html = 各号
- archive.html    = バックナンバー一覧
- assets/         = CSS等の静的ファイル
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

SITE_URL = "https://latte-y.github.io/ai-news/"

SECTION_ORDER = [
    ("models", "モデル・API"),
    ("tools", "開発ツール"),
    ("cloud", "クラウド・データ基盤"),
    ("industry", "業界・政策"),
    ("research", "研究"),
    ("japan", "国内"),
]

REPO_ROOT = Path(__file__).resolve().parent.parent

_WEEKDAYS_JA = "月火水木金土日"


def jp_date(date_str: str | None) -> str:
    """YYYY-MM-DD を「2026年10月3日（土）」形式にする。解釈できなければそのまま返す。"""
    if not date_str:
        return ""
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return date_str
    return f"{d.year}年{d.month}月{d.day}日（{_WEEKDAYS_JA[d.weekday()]}）"


def load_issues(issues_dir: Path, date_cutoff: str | None = None) -> list[dict]:
    """issues_dir配下の号データを日付昇順で読み込む。破損ファイルは警告してスキップする。"""
    issues = []
    if not issues_dir.exists():
        return issues
    for fp in sorted(issues_dir.glob("*.json")):
        try:
            issue = json.loads(fp.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            print(f"警告: 号データの読み込みに失敗、スキップします: {fp} ({e})", file=sys.stderr)
            continue
        if date_cutoff and issue.get("date", "") > date_cutoff:
            continue
        issues.append(issue)
    issues.sort(key=lambda i: i.get("date", ""))
    return issues


def group_articles(issue: dict) -> tuple[list[dict], dict[str, list[dict]]]:
    """記事をトップとセクション別にグルーピングし、importance降順で整列する。"""
    articles = issue.get("articles", [])
    top = sorted([a for a in articles if a.get("section") == "top"], key=lambda a: -a.get("importance", 0))
    grouped: dict[str, list[dict]] = {key: [] for key, _ in SECTION_ORDER}
    for a in articles:
        sec = a.get("section")
        if sec in grouped:
            grouped[sec].append(a)
    for key in grouped:
        grouped[key].sort(key=lambda a: -a.get("importance", 0))
    return top, grouped


def build(data_dir: Path, out_dir: Path, date_cutoff: str | None, site_url: str = SITE_URL) -> list[dict]:
    """サイト全体をビルドする。書き出した号のリスト（日付昇順）を返す。"""
    env = Environment(
        loader=FileSystemLoader(str(REPO_ROOT / "templates")),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["jp_date"] = jp_date

    issues = load_issues(data_dir / "issues", date_cutoff)

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "issues").mkdir(exist_ok=True)

    assets_src = REPO_ROOT / "static" / "assets"
    assets_dst = out_dir / "assets"
    if assets_src.exists():
        shutil.copytree(assets_src, assets_dst, dirs_exist_ok=True)

    issue_tpl = env.get_template("issue.html")
    archive_tpl = env.get_template("archive.html")

    archive_entries = []
    for idx, issue in enumerate(issues, start=1):
        top_articles, grouped = group_articles(issue)
        ctx = {
            "issue": issue,
            "issue_no": idx,
            "top_articles": top_articles,
            "grouped": grouped,
            "section_order": SECTION_ORDER,
            "site_url": site_url,
            "display_date": issue["date"],
        }
        # 各号のページ（issues/YYYY-MM-DD.html）
        html = issue_tpl.render(**ctx, root_path="../", is_index=False)
        (out_dir / "issues" / f"{issue['date']}.html").write_text(html, encoding="utf-8")
        archive_entries.append({"date": issue["date"], "headline": issue["headline"], "issue_no": idx})

    if issues:
        latest = issues[-1]
        latest_no = len(issues)
        top_articles, grouped = group_articles(latest)
        ctx = {
            "issue": latest,
            "issue_no": latest_no,
            "top_articles": top_articles,
            "grouped": grouped,
            "section_order": SECTION_ORDER,
            "site_url": site_url,
            "display_date": latest["date"],
        }
        html = issue_tpl.render(**ctx, root_path="", is_index=True)
        (out_dir / "index.html").write_text(html, encoding="utf-8")
    else:
        # 号がまだ無い場合の簡易トップページ
        empty_ctx = {
            "issue": {"headline": "まだ号がありません", "lead": "最初の号をお待ちください。", "date": "", "articles": []},
            "issue_no": None,
            "top_articles": [],
            "grouped": {k: [] for k, _ in SECTION_ORDER},
            "section_order": SECTION_ORDER,
            "site_url": site_url,
            "display_date": None,
        }
        html = issue_tpl.render(**empty_ctx, root_path="", is_index=True)
        (out_dir / "index.html").write_text(html, encoding="utf-8")

    archive_html = archive_tpl.render(
        issues=list(reversed(archive_entries)),
        site_url=site_url,
        root_path="",
        display_date=None,
        issue_no=None,
    )
    (out_dir / "archive.html").write_text(archive_html, encoding="utf-8")

    return issues


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AI新聞: 静的サイトビルド")
    parser.add_argument("--date", help="この日付以前の号のみを対象にする（テスト用、省略時は全号）")
    parser.add_argument("--data-dir", default="data", help="データディレクトリ（省略時 data/）")
    parser.add_argument("--out-dir", default="site", help="出力ディレクトリ（省略時 site/）")
    parser.add_argument("--site-url", default=SITE_URL, help="サイトのベースURL")
    args = parser.parse_args(argv)

    issues = build(Path(args.data_dir), Path(args.out_dir), args.date, args.site_url)
    print(f"ビルド完了: {len(issues)}号を {args.out_dir}/ に出力")
    return 0


if __name__ == "__main__":
    sys.exit(main())
