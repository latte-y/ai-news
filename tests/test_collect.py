"""src/collect.py のテスト。ネットワークアクセスはせず、ローカルのfixtureフィードのみ使う。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from src import collect
from src.util import normalize_url

FIXTURES = Path(__file__).parent / "fixtures" / "feeds"


def _write_sources_yaml(tmp_path: Path, sources: list[dict]) -> Path:
    p = tmp_path / "sources.yaml"
    p.write_text(yaml.safe_dump({"sources": sources}, allow_unicode=True), encoding="utf-8")
    return p


def test_normalize_url_strips_tracking_params_and_trailing_slash():
    assert normalize_url("https://example.com/post/?utm_source=a&utm_medium=b") == "https://example.com/post"
    assert normalize_url("https://example.com/post/") == "https://example.com/post"
    assert normalize_url("https://example.com/post") == "https://example.com/post"
    # トラッキング以外のクエリは保持される
    assert normalize_url("https://example.com/post?id=5&utm_campaign=x") == "https://example.com/post?id=5"


def test_collect_respects_36h_window(tmp_path):
    sources_path = _write_sources_yaml(
        tmp_path,
        [{"name": "Basic", "url": str(FIXTURES / "basic.xml"), "lang": "en", "kind": "media", "weight": 1.0}],
    )
    data_dir = tmp_path / "data"
    result = collect.collect(sources_path, data_dir, date_override="2026-01-10")

    titles = {c["title"] for c in result["candidates"]}
    assert titles == {"In Window Article"}
    assert result["candidate_count"] == 1


def test_collect_dedupes_against_past_issues(tmp_path):
    sources_path = _write_sources_yaml(
        tmp_path,
        [{"name": "Dedupe", "url": str(FIXTURES / "dedupe.xml"), "lang": "en", "kind": "media", "weight": 1.0}],
    )
    data_dir = tmp_path / "data"
    issues_dir = data_dir / "issues"
    issues_dir.mkdir(parents=True)
    past_issue = {
        "date": "2026-01-05",
        "generated_at": "2026-01-05T07:00:00+09:00",
        "headline": "past",
        "lead": "past issue",
        "articles": [
            {
                "section": "top",
                "importance": 5,
                "title": "past article",
                "summary": "s",
                "why_it_matters": "w",
                "tags": [],
                "source_name": "Dedupe",
                "source_url": "https://example.com/dup-article",  # collect側で正規化されたURLと一致させる
                "original_title": "past",
                "original_lang": "en",
                "published_at": "2026-01-05T00:00:00Z",
            }
        ],
    }
    (issues_dir / "2026-01-05.json").write_text(json.dumps(past_issue, ensure_ascii=False), encoding="utf-8")

    result = collect.collect(sources_path, data_dir, date_override="2026-01-10")
    urls = {c["url"] for c in result["candidates"]}

    assert "https://example.com/dup-article" not in urls
    assert "https://example.com/new-article" in urls


def test_collect_filters_hn_by_ai_keywords(tmp_path):
    sources_path = _write_sources_yaml(
        tmp_path,
        [{"name": "Hacker News", "url": str(FIXTURES / "hn.xml"), "lang": "en", "kind": "community", "weight": 0.9}],
    )
    data_dir = tmp_path / "data"
    result = collect.collect(sources_path, data_dir, date_override="2026-01-10")

    titles = {c["title"] for c in result["candidates"]}
    assert "New AI model beats benchmark records" in titles
    assert "Startup raises funding for logistics platform" not in titles


def test_collect_continues_when_one_feed_fails(tmp_path):
    sources_path = _write_sources_yaml(
        tmp_path,
        [
            {"name": "Broken", "url": "file:///nonexistent/path/does-not-exist.xml", "lang": "en", "kind": "media", "weight": 1.0},
            {"name": "Basic", "url": str(FIXTURES / "basic.xml"), "lang": "en", "kind": "media", "weight": 1.0},
        ],
    )
    data_dir = tmp_path / "data"
    result = collect.collect(sources_path, data_dir, date_override="2026-01-10")

    titles = {c["title"] for c in result["candidates"]}
    assert "In Window Article" in titles


def test_collect_extracts_image_url_from_various_feed_fields(tmp_path):
    sources_path = _write_sources_yaml(
        tmp_path,
        [{"name": "Images", "url": str(FIXTURES / "images.xml"), "lang": "en", "kind": "media", "weight": 1.0}],
    )
    result = collect.collect(sources_path, tmp_path / "data", date_override="2026-01-10")
    by_title = {c["title"]: c for c in result["candidates"]}

    # media:content が media:thumbnail より優先される
    assert by_title["Media Content"]["image_url"] == "https://cdn.example.com/mc.jpg"
    assert by_title["Media Thumbnail"]["image_url"] == "https://cdn.example.com/thumb.jpg"
    assert by_title["Enclosure Image"]["image_url"] == "https://cdn.example.com/enc.png"
    # 相対URLは記事URL基準で絶対化される
    assert by_title["Img In Summary Relative"]["image_url"] == "https://example.com/static/hero.jpg"
    assert by_title["Img In Content Encoded"]["image_url"] == "https://cdn.example.com/body.webp"
    # 音声enclosure・http画像・画像なしはimage_urlキー自体を出さない
    for t in ("Audio Enclosure Only", "Http Image Rejected", "No Image"):
        assert "image_url" not in by_title[t]
