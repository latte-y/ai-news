"""src/validate.py のテスト。良いfixtureと壊れたfixtureの両方を検証する。"""

from __future__ import annotations

import copy
import json
from pathlib import Path

from src import validate

FIXTURE = Path(__file__).parent / "fixtures" / "sample_issue.json"


def _load_sample() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_sample_issue_is_valid():
    issue = _load_sample()
    errors = validate.validate_issue(issue, expected_date="2026-09-29")
    assert errors == []


def test_sample_issue_file_validates_via_validate_file(tmp_path):
    issue = _load_sample()
    p = tmp_path / "2026-09-29.json"
    p.write_text(json.dumps(issue, ensure_ascii=False), encoding="utf-8")
    errors = validate.validate_file(p)
    assert errors == []


def test_missing_required_key_is_rejected():
    issue = _load_sample()
    del issue["headline"]
    errors = validate.validate_issue(issue)
    assert any("必須キー" in e for e in errors)


def test_bad_section_enum_is_rejected():
    issue = _load_sample()
    issue["articles"][2]["section"] = "not-a-real-section"
    errors = validate.validate_issue(issue)
    assert any("section不正" in e for e in errors)


def test_too_few_articles_is_rejected():
    issue = _load_sample()
    issue["articles"] = issue["articles"][:2]  # 5件未満にする
    errors = validate.validate_issue(issue)
    assert any("articles件数" in e for e in errors)


def test_too_many_top_articles_is_rejected():
    issue = _load_sample()
    for a in issue["articles"]:
        a["section"] = "top"
        a["importance"] = 5
    errors = validate.validate_issue(issue)
    assert any("topセクション" in e for e in errors)


def test_bad_source_url_is_rejected():
    issue = _load_sample()
    issue["articles"][0]["source_url"] = "not a url"
    errors = validate.validate_issue(issue)
    assert any("source_urlがURL形式ではない" in e for e in errors)


def test_date_mismatch_with_filename_is_rejected():
    issue = _load_sample()
    errors = validate.validate_issue(issue, expected_date="2099-01-01")
    assert any("dateがファイル名と不一致" in e for e in errors)


def test_headline_too_long_is_rejected():
    issue = _load_sample()
    issue["headline"] = "あ" * 30
    errors = validate.validate_issue(issue)
    assert any("headlineが" in e and "超過" in e for e in errors)


def test_duplicate_source_url_within_issue_is_rejected():
    issue = _load_sample()
    issue["articles"][1] = copy.deepcopy(issue["articles"][0])
    issue["articles"][1]["section"] = "models"
    issue["articles"][1]["importance"] = 3
    errors = validate.validate_issue(issue)
    assert any("重複" in e for e in errors)
