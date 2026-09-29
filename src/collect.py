"""RSS/Atomフィードを巡回して当日の候補記事を集める。

`config/sources.yaml` に列挙された情報源を取得し、直近36時間の記事のうち
過去7日分の号（data/issues/*.json）にまだ載っていないものを
`data/candidates/YYYY-MM-DD.json` に書き出す。

このモジュールはLLM/Claude APIを一切呼び出さない。記事の選定・翻訳・要約は
ROUTINE.mdに従ってClaude Codeのroutineが行う。
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from calendar import timegm
from datetime import datetime, timedelta, timezone
from pathlib import Path

import feedparser
import yaml

from src.util import JST, jst_now, jst_today_str, normalize_url, parse_date_arg, strip_html

log = logging.getLogger("collect")

COLLECT_WINDOW_HOURS = 36
DEDUPE_WINDOW_DAYS = 7
MAX_CANDIDATES = 150
FEED_TIMEOUT_SEC = 15

#: Hacker Newsのfrontpageは話題全般が流れてくるため、AI関連キーワードでの絞り込みが必須
HN_AI_KEYWORDS = [
    "ai", "llm", "gpt", "claude", "gemini", "openai", "anthropic", "deepmind",
    "chatgpt", "transformer", "neural", "machine learning", "artificial intelligence",
    "diffusion", "agent", "copilot", "mistral", "llama", "genai", "generative",
]
_HN_KEYWORD_RE = re.compile(r"(?i)\b(" + "|".join(re.escape(k) for k in HN_AI_KEYWORDS) + r")\b")


def load_sources(path: Path) -> list[dict]:
    """config/sources.yaml を読み込んで情報源のリストを返す。"""
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("sources", [])


def _entry_published(entry: dict) -> datetime | None:
    """feedparserエントリから発行日時（UTC aware datetime）を取り出す。取れなければNone。"""
    for key in ("published_parsed", "updated_parsed"):
        t = entry.get(key)
        if t:
            return datetime.fromtimestamp(timegm(t), tz=timezone.utc)
    return None


def _is_hn_relevant(title: str) -> bool:
    return bool(_HN_KEYWORD_RE.search(title or ""))


def _load_recent_issue_urls(issues_dir: Path, reference: datetime, days: int) -> set[str]:
    """過去days日分の号に載っているURL（正規化済み）の集合を返す。"""
    urls: set[str] = set()
    if not issues_dir.exists():
        return urls
    cutoff = reference - timedelta(days=days)
    for fp in issues_dir.glob("*.json"):
        try:
            file_date = datetime.strptime(fp.stem, "%Y-%m-%d").replace(tzinfo=JST)
        except ValueError:
            continue
        if file_date < cutoff - timedelta(days=1):  # 念のため1日の余裕を持たせる
            continue
        try:
            issue = json.loads(fp.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            log.warning("過去号の読み込みに失敗: %s (%s)", fp, e)
            continue
        for art in issue.get("articles", []):
            u = art.get("source_url")
            if u:
                urls.add(normalize_url(u))
    return urls


def fetch_feed(source: dict) -> list[dict]:
    """1つの情報源からエントリを取得する。失敗しても例外を投げず空リストを返す。"""
    name = source.get("name", source.get("url", "?"))
    url = source["url"]
    try:
        parsed = feedparser.parse(url, agent="ai-news-collector/0.1")
    except Exception as e:  # noqa: BLE001 1フィードの失敗で全体を止めない
        log.warning("フィード取得失敗: %s (%s) - %s", name, url, e)
        return []
    if parsed.bozo and not parsed.entries:
        log.warning("フィード解析失敗（entries=0）: %s (%s) - %s", name, url, parsed.get("bozo_exception"))
        return []
    return parsed.entries


def collect(
    sources_path: Path,
    data_dir: Path,
    date_override: str | None,
) -> dict:
    """収集処理本体。結果の候補dictを返す（呼び出し側でファイルに書く）。"""
    sources = load_sources(sources_path)
    reference = parse_date_arg(date_override) if date_override else jst_now()
    window_start = reference - timedelta(hours=COLLECT_WINDOW_HOURS)

    issues_dir = data_dir / "issues"
    seen_urls = _load_recent_issue_urls(issues_dir, reference, DEDUPE_WINDOW_DAYS)

    candidates: list[dict] = []
    per_source_count: dict[str, int] = {}

    for source in sources:
        name = source.get("name", "?")
        weight = float(source.get("weight", 1.0))
        lang = source.get("lang", "en")
        entries = fetch_feed(source)
        kept_here = 0
        for entry in entries:
            title = (entry.get("title") or "").strip()
            link = entry.get("link") or ""
            if not title or not link:
                continue
            published = _entry_published(entry)
            if published is None:
                # 発行日時不明の記事は「今」扱いにはせず除外する（誤って毎回候補に出るのを防ぐ）
                continue
            if published < window_start.astimezone(timezone.utc) or published > reference.astimezone(timezone.utc):
                continue
            if name == "Hacker News" and not _is_hn_relevant(title):
                continue

            norm_url = normalize_url(link)
            if norm_url in seen_urls:
                continue

            summary_src = entry.get("summary") or entry.get("description") or ""
            candidates.append(
                {
                    "title": title,
                    "url": norm_url,
                    "source": name,
                    "lang": lang,
                    "published_at": published.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "summary": strip_html(summary_src, 600),
                    "_weight": weight,
                }
            )
            seen_urls.add(norm_url)  # 同一実行内での重複（複数フィードが同じ記事を配信）も除去
            kept_here += 1
        per_source_count[name] = kept_here
        log.info("収集: %s -> %d件", name, kept_here)

    # 新しい順・weight考慮でソートし、最大150件に絞る
    candidates.sort(key=lambda c: (c["_weight"], c["published_at"]), reverse=True)
    candidates = candidates[:MAX_CANDIDATES]
    for c in candidates:
        c.pop("_weight", None)

    result = {
        "date": jst_today_str(date_override),
        "generated_at": jst_now().isoformat(timespec="seconds"),
        "window_hours": COLLECT_WINDOW_HOURS,
        "candidate_count": len(candidates),
        "per_source_count": per_source_count,
        "candidates": candidates,
    }
    return result


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="AI新聞: RSS候補収集")
    parser.add_argument("--date", help="JST日付(YYYY-MM-DD)。省略時は現在時刻を使う（テスト用）")
    parser.add_argument("--data-dir", default="data", help="データディレクトリ（省略時 data/）")
    parser.add_argument("--sources", default="config/sources.yaml", help="情報源定義YAML")
    args = parser.parse_args(argv)

    data_dir = Path(args.data_dir)
    candidates_dir = data_dir / "candidates"
    candidates_dir.mkdir(parents=True, exist_ok=True)

    result = collect(Path(args.sources), data_dir, args.date)

    out_path = candidates_dir / f"{result['date']}.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    log.info("候補 %d 件を書き出し: %s", result["candidate_count"], out_path)
    for name, n in result["per_source_count"].items():
        print(f"  {name}: {n}件")
    return 0


if __name__ == "__main__":
    sys.exit(main())
