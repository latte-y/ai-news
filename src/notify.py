"""新しく追加された号をGmailで通知する。

`publish.yml` からは、pushで新規追加された号データのファイル(git diff)を検出したうえで
`python -m src.notify --date YYYY-MM-DD ...` として呼び出される想定。
このモジュール自身も `data/.notified.json` に送信済み日付を記録し、二重送信を防ぐ
（`--force` で無視して再送できる）。

`watchdog.yml` からは `python -m src.notify --watchdog` として呼ばれ、
当日のJST日付の号がまだ無ければ「未生成」アラートメールを送る。
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from src.build import SECTION_ORDER, jp_date
from src.mailer import send as mailer_send
from src.util import jst_today_str

log = logging.getLogger("notify")

SITE_URL = "https://latte-y.github.io/ai-news/"
REPO_ROOT = Path(__file__).resolve().parent.parent
STATE_FILENAME = ".notified.json"


def _env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(REPO_ROOT / "templates")),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["jp_date"] = jp_date
    return env


def _load_state(data_dir: Path) -> set[str]:
    fp = data_dir / STATE_FILENAME
    if not fp.exists():
        return set()
    try:
        return set(json.loads(fp.read_text(encoding="utf-8")).get("notified_dates", []))
    except (json.JSONDecodeError, OSError):
        return set()


def _save_state(data_dir: Path, notified_dates: set[str]) -> None:
    fp = data_dir / STATE_FILENAME
    fp.write_text(json.dumps({"notified_dates": sorted(notified_dates)}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def list_issue_dates(data_dir: Path) -> list[str]:
    """data_dir/issues/*.json から日付(YYYY-MM-DD)のリストを昇順で返す。"""
    issues_dir = data_dir / "issues"
    if not issues_dir.exists():
        return []
    dates = [fp.stem for fp in issues_dir.glob("*.json") if re.match(r"^\d{4}-\d{2}-\d{2}$", fp.stem)]
    return sorted(dates)


def determine_new_issues(
    all_dates: list[str],
    notified_dates: set[str],
    requested_dates: list[str] | None,
    force: bool,
) -> list[str]:
    """通知すべき（＝新規追加とみなす）号の日付リストを決定する。

    requested_datesが指定された場合はそれを候補にする（workflowがgit diffで
    検出した「今回のpushで新規追加されたファイル」を渡す想定）。
    指定が無ければ、まだ通知していない全ての号を候補にする。
    forceが立っていれば、候補が既に通知済みでも再送する。
    """
    if requested_dates:
        candidates = [d for d in requested_dates if d in all_dates]
    else:
        candidates = list(all_dates)

    if force:
        return candidates
    return [d for d in candidates if d not in notified_dates]


def _load_issue(data_dir: Path, date: str) -> dict:
    fp = data_dir / "issues" / f"{date}.json"
    return json.loads(fp.read_text(encoding="utf-8"))


def _summary_one_line(summary: str, max_len: int = 80) -> str:
    """要約の最初の1文（「。」まで）、無ければ先頭max_len字を返す。"""
    m = re.search(r"^(.*?。)", summary)
    if m:
        return m.group(1)
    return summary if len(summary) <= max_len else summary[: max_len - 1] + "…"


def build_email(issue: dict, issue_no: int, site_url: str) -> tuple[str, str]:
    """号データからメール件名とHTML本文を生成する。"""
    # topセクションを優先しつつ、足りない分は重要度の高い順に補って常に最大3件にする
    top = sorted(
        issue.get("articles", []),
        key=lambda a: (a.get("section") != "top", -a.get("importance", 0)),
    )[:3]
    for a in top:
        a["summary_one_line"] = _summary_one_line(a.get("summary", ""))

    date = issue["date"]
    y, mo, d = date.split("-")
    subject = f"【AI新聞】{int(mo)}/{int(d)} {issue['headline']}"

    html = _env().get_template("email.html").render(
        issue=issue,
        issue_no=issue_no,
        top_articles=top,
        section_labels={"top": "トップ", **dict(SECTION_ORDER)},
        site_url=site_url,
    )
    return subject, html


def build_watchdog_email(date: str, site_url: str) -> tuple[str, str]:
    subject = f"【AI新聞】{date} の号が未生成です"
    html = (
        "<html><body style=\"font-family:-apple-system,sans-serif;\">"
        f"<p>AI新聞 {date} の号がまだ生成されていません。</p>"
        f"<p>routine（Claude Code定期実行）が失敗した可能性があります。ログを確認してください。</p>"
        f"<p><a href=\"{site_url}\">{site_url}</a></p>"
        "</body></html>"
    )
    return subject, html


def run_notify(data_dir: Path, requested_dates: list[str] | None, force: bool, site_url: str, dry_run: bool) -> int:
    all_dates = list_issue_dates(data_dir)
    notified = _load_state(data_dir)
    new_dates = determine_new_issues(all_dates, notified, requested_dates, force)

    if not new_dates:
        log.info("新規に通知すべき号はありません")
        return 0

    sent_count = 0
    for date in new_dates:
        issue = _load_issue(data_dir, date)
        issue_no = all_dates.index(date) + 1
        subject, html = build_email(issue, issue_no, site_url)

        if dry_run:
            out_dir = REPO_ROOT / "out"
            out_dir.mkdir(exist_ok=True)
            out_path = out_dir / "email_preview.html"
            out_path.write_text(html, encoding="utf-8")
            log.info("DRY RUN: %s を書き出しました（送信はしません）: %s", out_path, subject)
            sent_count += 1
            continue

        ok = mailer_send(html, subject)
        if ok:
            notified.add(date)
            sent_count += 1
        else:
            log.error("送信失敗のため %s は未通知のまま残します", date)

    if not dry_run:
        _save_state(data_dir, notified)
    return 0 if sent_count == len(new_dates) else 1


def run_watchdog(data_dir: Path, site_url: str, dry_run: bool) -> int:
    today = jst_today_str()
    fp = data_dir / "issues" / f"{today}.json"
    if fp.exists():
        log.info("本日(%s)の号は存在します。watchdogアラートは送信しません", today)
        return 0

    log.warning("本日(%s)の号が見つかりません。アラートを送信します", today)
    subject, html = build_watchdog_email(today, site_url)
    if dry_run:
        out_dir = REPO_ROOT / "out"
        out_dir.mkdir(exist_ok=True)
        (out_dir / "email_preview.html").write_text(html, encoding="utf-8")
        log.info("DRY RUN: watchdogアラートを out/email_preview.html に書き出しました")
        return 0
    ok = mailer_send(html, subject)
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="AI新聞: 新規号のメール通知")
    parser.add_argument("--date", action="append", dest="dates", help="通知対象の号の日付(YYYY-MM-DD)。複数指定可。省略時は未通知の全号")
    parser.add_argument("--data-dir", default="data", help="データディレクトリ（省略時 data/）")
    parser.add_argument("--site-url", default=SITE_URL, help="サイトのベースURL")
    parser.add_argument("--force", action="store_true", help="既に通知済みでも再送する")
    parser.add_argument("--watchdog", action="store_true", help="当日の号の存在確認のみ行い、無ければアラートを送る")
    parser.add_argument("--dry-run", action="store_true", help="送信せずout/email_preview.htmlに保存する（DRY_RUN環境変数でも可）")
    args = parser.parse_args(argv)

    dry_run = args.dry_run or bool(os.environ.get("DRY_RUN"))
    data_dir = Path(args.data_dir)

    if args.watchdog:
        return run_watchdog(data_dir, args.site_url, dry_run)
    return run_notify(data_dir, args.dates, args.force, args.site_url, dry_run)


if __name__ == "__main__":
    sys.exit(main())
