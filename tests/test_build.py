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


def test_build_renders_images_with_required_attributes(tmp_path):
    data_dir = _prepare_data_dir(tmp_path, ["2026-09-29"])
    out_dir = tmp_path / "site"
    build.build(data_dir, out_dir, date_cutoff=None)
    html = (out_dir / "issues" / "2026-09-29.html").read_text(encoding="utf-8")

    assert 'src="https://example.com/images/sample-0.jpg"' in html  # トップ記事
    assert 'src="https://example.com/images/sample-2.jpg"' in html  # セクションカード
    assert 'loading="lazy"' in html
    assert 'referrerpolicy="no-referrer"' in html
    assert 'decoding="async"' in html
    assert "画像: Example Source" in html
    # 画像リンクはタブ停止を重複させない
    assert 'aria-hidden="true" tabindex="-1"' in html
    # 画像のない記事の数だけ枠が減っている（5件に画像あり）
    assert html.count('class="media ') == 5


def test_build_without_image_renders_no_media_box(tmp_path):
    data_dir = _prepare_data_dir(tmp_path, ["2026-09-29"])
    p = data_dir / "issues" / "2026-09-29.json"
    issue = json.loads(p.read_text(encoding="utf-8"))
    for a in issue["articles"]:
        a.pop("image_url", None)
        a.pop("image_credit", None)
    p.write_text(json.dumps(issue, ensure_ascii=False), encoding="utf-8")
    out_dir = tmp_path / "site"
    build.build(data_dir, out_dir, date_cutoff=None)
    html = (out_dir / "issues" / "2026-09-29.html").read_text(encoding="utf-8")
    assert 'class="media ' not in html
    assert "<img" not in html


def test_build_card_uses_details_and_limits_tags_to_three(tmp_path):
    data_dir = _prepare_data_dir(tmp_path, ["2026-09-29"])
    out_dir = tmp_path / "site"
    build.build(data_dir, out_dir, date_cutoff=None)
    html = (out_dir / "issues" / "2026-09-29.html").read_text(encoding="utf-8")
    assert '<details class="article-card__why">' in html
    # 4タグ目はカードに出ない（Extraはmodels記事のみが持つ）
    assert "Pricing" in html
    assert ">Extra<" not in html


def test_jp_date_formats_weekday():
    assert build.jp_date("2026-10-03") == "2026年10月3日（土）"
    assert build.jp_date("bad") == "bad"
    assert build.jp_date(None) == ""


def test_build_masthead_shows_japanese_date_and_issue_no(tmp_path):
    data_dir = _prepare_data_dir(tmp_path, ["2026-10-03"])
    out_dir = tmp_path / "site"
    build.build(data_dir, out_dir, date_cutoff=None)
    html = (out_dir / "index.html").read_text(encoding="utf-8")
    assert "2026年10月3日（土）" in html
    assert "第1号" in html
    assert "prefers-color-scheme" not in (out_dir / "assets" / "style.css").read_text(encoding="utf-8")
