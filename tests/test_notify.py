"""src/notify.py のテスト。新規号判定ロジックとメールHTML生成を検証する（SMTP送信はモック）。"""

from __future__ import annotations

import json
from pathlib import Path

from src import notify

FIXTURE = Path(__file__).parent / "fixtures" / "sample_issue.json"


def _make_issue(date: str, headline: str = "見出し") -> dict:
    issue = json.loads(FIXTURE.read_text(encoding="utf-8"))
    issue["date"] = date
    issue["headline"] = headline
    return issue


def _prepare_data_dir(tmp_path: Path, dates: list[str]) -> Path:
    data_dir = tmp_path / "data"
    issues_dir = data_dir / "issues"
    issues_dir.mkdir(parents=True)
    for d in dates:
        issue = _make_issue(d)
        (issues_dir / f"{d}.json").write_text(json.dumps(issue, ensure_ascii=False), encoding="utf-8")
    return data_dir


# ---------- 新規号判定ロジック ----------


def test_determine_new_issues_without_request_returns_unnotified_only():
    all_dates = ["2026-09-27", "2026-09-28", "2026-09-29"]
    notified = {"2026-09-27", "2026-09-28"}
    result = notify.determine_new_issues(all_dates, notified, requested_dates=None, force=False)
    assert result == ["2026-09-29"]


def test_determine_new_issues_with_requested_dates_filters_to_existing():
    all_dates = ["2026-09-28", "2026-09-29"]
    result = notify.determine_new_issues(all_dates, set(), requested_dates=["2026-09-29", "2026-09-30"], force=False)
    # 2026-09-30はall_datesに無いので候補から除外される
    assert result == ["2026-09-29"]


def test_determine_new_issues_skips_already_notified():
    all_dates = ["2026-09-29"]
    result = notify.determine_new_issues(all_dates, {"2026-09-29"}, requested_dates=["2026-09-29"], force=False)
    assert result == []


def test_determine_new_issues_force_resends_already_notified():
    all_dates = ["2026-09-29"]
    result = notify.determine_new_issues(all_dates, {"2026-09-29"}, requested_dates=["2026-09-29"], force=True)
    assert result == ["2026-09-29"]


# ---------- メールHTML生成 ----------


def test_build_email_contains_top3_and_site_link():
    issue = _make_issue("2026-09-29", headline="今日を一言で表す見出し")
    subject, html = notify.build_email(issue, issue_no=3, site_url="https://latte-y.github.io/ai-news/")

    assert "9/29" in subject
    assert "今日を一言で表す見出し" in subject
    assert "今日を一言で表す見出し" in html
    assert "https://latte-y.github.io/ai-news/issues/2026-09-29.html" in html

    top_titles = [a["title"] for a in issue["articles"] if a["section"] == "top"]
    for t in top_titles:
        assert t in html


def test_run_notify_sends_only_new_issues_and_updates_state(tmp_path, monkeypatch):
    data_dir = _prepare_data_dir(tmp_path, ["2026-09-28", "2026-09-29"])
    (data_dir / notify.STATE_FILENAME).write_text(
        json.dumps({"notified_dates": ["2026-09-28"]}), encoding="utf-8"
    )

    sent = []
    monkeypatch.setattr(notify, "mailer_send", lambda html, subject: sent.append(subject) or True)

    rc = notify.run_notify(data_dir, requested_dates=None, force=False, site_url="https://example.com/", dry_run=False)

    assert rc == 0
    assert len(sent) == 1
    assert "9/29" in sent[0]

    state = json.loads((data_dir / notify.STATE_FILENAME).read_text(encoding="utf-8"))
    assert set(state["notified_dates"]) == {"2026-09-28", "2026-09-29"}


def test_run_notify_dry_run_writes_preview_and_does_not_send(tmp_path, monkeypatch):
    data_dir = _prepare_data_dir(tmp_path, ["2026-09-29"])
    called = []
    monkeypatch.setattr(notify, "mailer_send", lambda html, subject: called.append(1) or True)

    rc = notify.run_notify(data_dir, requested_dates=None, force=False, site_url="https://example.com/", dry_run=True)

    assert rc == 0
    assert called == []
    preview = notify.REPO_ROOT / "out" / "email_preview.html"
    assert preview.exists()
    # dry-runでは通知済み状態を更新しない
    assert not (data_dir / notify.STATE_FILENAME).exists()


def test_run_watchdog_sends_alert_when_missing(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    (data_dir / "issues").mkdir(parents=True)

    from src import util

    monkeypatch.setattr(util, "jst_today_str", lambda date_override=None: "2026-09-29")
    monkeypatch.setattr(notify, "jst_today_str", lambda date_override=None: "2026-09-29")

    sent = []
    monkeypatch.setattr(notify, "mailer_send", lambda html, subject: sent.append(subject) or True)

    rc = notify.run_watchdog(data_dir, site_url="https://example.com/", dry_run=False)

    assert rc == 0
    assert len(sent) == 1
    assert "未生成" in sent[0]


def test_run_watchdog_skips_when_issue_exists(tmp_path, monkeypatch):
    data_dir = _prepare_data_dir(tmp_path, ["2026-09-29"])
    monkeypatch.setattr(notify, "jst_today_str", lambda date_override=None: "2026-09-29")

    sent = []
    monkeypatch.setattr(notify, "mailer_send", lambda html, subject: sent.append(subject) or True)

    rc = notify.run_watchdog(data_dir, site_url="https://example.com/", dry_run=False)

    assert rc == 0
    assert sent == []
