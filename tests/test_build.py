"""src/build.py のテスト。fixtureの号データからサイトをビルドして検証する。"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from src import build

FIXTURE = Path(__file__).parent / "fixtures" / "sample_issue.json"


def _prepare_data_dir(tmp_path: Path, dates: list[str]) -> Path:
    """fixtureの号データを、指定した日付ぶんコピーしたdata_dirを作る。"""
    data_dir = tmp_path / "data"
    issues_dir = data_dir / "issues"
    issues_dir.mkdir(parents=True)
    base = json.loads(FIXTURE.read_text(encoding="utf-8"))
    for d in dates:
        issue = dict(base)
        issue["date"] = d
        issue["headline"] = f"見出し({d})"
        (issues_dir / f"{d}.json").write_text(json.dumps(issue, ensure_ascii=False), encoding="utf-8")
    return data_dir


def test_build_renders_index_issue_and_archive_pages(tmp_path):
    data_dir = _prepare_data_dir(tmp_path, ["2026-09-28", "2026-09-29"])
    out_dir = tmp_path / "site"

    issues = build.build(data_dir, out_dir, date_cutoff=None)

    assert len(issues) == 2
    assert (out_dir / "index.html").exists()
    assert (out_dir / "archive.html").exists()
    assert (out_dir / "issues" / "2026-09-28.html").exists()
    assert (out_dir / "issues" / "2026-09-29.html").exists()
    assert (out_dir / "assets" / "style.css").exists()


def test_build_index_shows_latest_issue(tmp_path):
    data_dir = _prepare_data_dir(tmp_path, ["2026-09-28", "2026-09-29"])
    out_dir = tmp_path / "site"
    build.build(data_dir, out_dir, date_cutoff=None)

    index_html = (out_dir / "index.html").read_text(encoding="utf-8")
    assert "見出し(2026-09-29)" in index_html
    assert "第2号" in index_html


def test_build_pages_include_source_links(tmp_path):
    data_dir = _prepare_data_dir(tmp_path, ["2026-09-29"])
    out_dir = tmp_path / "site"
    build.build(data_dir, out_dir, date_cutoff=None)

    issue_html = (out_dir / "issues" / "2026-09-29.html").read_text(encoding="utf-8")
    assert "example.com/articles/sample-model-announcement" in issue_html
    assert "出典" in issue_html


def test_build_archive_lists_all_issues(tmp_path):
    data_dir = _prepare_data_dir(tmp_path, ["2026-09-27", "2026-09-28", "2026-09-29"])
    out_dir = tmp_path / "site"
    build.build(data_dir, out_dir, date_cutoff=None)

    archive_html = (out_dir / "archive.html").read_text(encoding="utf-8")
    for d in ("2026-09-27", "2026-09-28", "2026-09-29"):
        assert d in archive_html


def test_build_date_cutoff_excludes_future_issues(tmp_path):
    data_dir = _prepare_data_dir(tmp_path, ["2026-09-28", "2026-09-29"])
    out_dir = tmp_path / "site"

    issues = build.build(data_dir, out_dir, date_cutoff="2026-09-28")

    assert [i["date"] for i in issues] == ["2026-09-28"]
    assert not (out_dir / "issues" / "2026-09-29.html").exists()


def test_build_with_no_issues_does_not_crash(tmp_path):
    data_dir = tmp_path / "data"
    (data_dir / "issues").mkdir(parents=True)
    out_dir = tmp_path / "site"

    issues = build.build(data_dir, out_dir, date_cutoff=None)

    assert issues == []
    assert (out_dir / "index.html").exists()
