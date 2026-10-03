"""src/images.py のテスト。HTTPはモックし、ネットワークアクセスはしない。"""

from __future__ import annotations

import json
from pathlib import Path

import requests

from src import images

FIXTURE = Path(__file__).parent / "fixtures" / "sample_issue.json"


class FakeResp:
    def __init__(self, html: str, url: str = "https://example.com/a", status: int = 200):
        self._body = html.encode("utf-8")
        self.encoding = "utf-8"
        self.url = url
        self.status = status

    def iter_content(self, chunk_size=1024):
        yield self._body

    def raise_for_status(self):
        if self.status >= 400:
            raise requests.HTTPError(str(self.status))

    def close(self):
        pass


def test_extract_prefers_og_over_twitter():
    html = '<head><meta name="twitter:image" content="https://x.com/t.jpg"><meta property="og:image" content="https://x.com/o.jpg"></head>'
    assert images.extract_meta_image(html, "https://x.com/p") == "https://x.com/o.jpg"


def test_extract_falls_back_to_twitter_and_resolves_relative():
    html = '<meta name="twitter:image" content="/img/t.jpg">'
    assert images.extract_meta_image(html, "https://x.com/p/q") == "https://x.com/img/t.jpg"


def test_extract_rejects_http_and_missing():
    assert images.extract_meta_image('<meta property="og:image" content="http://x.com/o.jpg">', "https://x.com/") is None
    assert images.extract_meta_image("<html></html>", "https://x.com/") is None


def test_fetch_returns_none_on_error(monkeypatch):
    def boom(*a, **k):
        raise requests.Timeout("slow")

    monkeypatch.setattr(images.requests, "get", boom)
    assert images.fetch_image_url("https://example.com/a") is None


def test_fetch_returns_none_on_http_error(monkeypatch):
    monkeypatch.setattr(images.requests, "get", lambda *a, **k: FakeResp("", status=404))
    assert images.fetch_image_url("https://example.com/a") is None


def test_fetch_passes_timeout_and_user_agent(monkeypatch):
    seen = {}

    def fake_get(url, **kw):
        seen.update(kw)
        return FakeResp('<meta property="og:image" content="https://cdn.example.com/i.jpg">')

    monkeypatch.setattr(images.requests, "get", fake_get)
    assert images.fetch_image_url("https://example.com/a") == "https://cdn.example.com/i.jpg"
    assert seen["timeout"] == 8
    assert "User-Agent" in seen["headers"]


def test_enrich_issue_skips_existing_and_records_failures(monkeypatch):
    issue = {
        "articles": [
            {"source_url": "https://a.example/1", "source_name": "A", "image_url": "https://c.example/x.jpg"},
            {"source_url": "https://a.example/2", "source_name": "B"},
            {"source_url": "https://a.example/3", "source_name": "C"},
        ]
    }
    calls = []

    def fake_fetch(u):
        calls.append(u)
        return "https://c.example/2.jpg" if u.endswith("/2") else None

    monkeypatch.setattr(images, "fetch_image_url", fake_fetch)
    added, failed = images.enrich_issue(issue)
    assert calls == ["https://a.example/2", "https://a.example/3"]
    assert added == 1 and failed == ["https://a.example/3"]
    assert issue["articles"][0]["image_credit"] == "A"
    assert issue["articles"][1]["image_url"] == "https://c.example/2.jpg"
    assert issue["articles"][1]["image_credit"] == "B"
    assert "image_url" not in issue["articles"][2]


def test_main_preserves_format_and_key_order(tmp_path, monkeypatch):
    base = json.loads(FIXTURE.read_text(encoding="utf-8"))
    for a in base["articles"]:
        a.pop("image_url", None)
        a.pop("image_credit", None)
    p = tmp_path / "2026-09-29.json"
    original = json.dumps(base, ensure_ascii=False, indent=2) + "\n"
    p.write_text(original, encoding="utf-8")

    monkeypatch.setattr(images, "fetch_image_url", lambda u: None)
    assert images.main([str(p)]) == 0
    assert p.read_text(encoding="utf-8") == original  # 失敗のみなら内容は不変

    monkeypatch.setattr(images, "fetch_image_url", lambda u: "https://cdn.example.com/i.jpg")
    assert images.main([str(p)]) == 0
    text = p.read_text(encoding="utf-8")
    assert "日本語" not in text or "\\u" not in text  # ensure_ascii=False
    out = json.loads(text)
    assert list(out.keys()) == list(base.keys())
    assert list(out["articles"][0].keys())[-2:] == ["image_url", "image_credit"]
    assert text.endswith("}\n")
