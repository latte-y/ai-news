"""号データの画像を補完する。

`python -m src.images data/issues/YYYY-MM-DD.json` で実行する。
`image_url` が無い記事について `source_url` のHTMLから og:image → twitter:image の順で
画像URLを取得し、`image_url` と `image_credit`（=source_name）を書き込む。

- 画像そのものは複製・保存しない（URLだけを記録し、表示時に元サイトから直接読み込む）
- 取得失敗は無視する（画像なしのまま）。タイムアウトは1件あたり8秒
- https以外の画像URLは捨てる。相対URLは絶対化する

このモジュールはLLM/Claude APIを一切呼び出さない。
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from html.parser import HTMLParser
from pathlib import Path

import requests

from src.util import to_https_image_url

log = logging.getLogger("images")

FETCH_TIMEOUT_SEC = 8
USER_AGENT = "Mozilla/5.0 (compatible; ai-news-bot/0.1; +https://latte-y.github.io/ai-news/)"
#: <head>内のmetaだけ読めればよいので、巨大なページは先頭のみ読む
MAX_HTML_BYTES = 512 * 1024

#: 優先順（先に書いたものが優先）
_META_KEYS = ["og:image", "og:image:secure_url", "og:image:url", "twitter:image", "twitter:image:src"]


class _MetaImageParser(HTMLParser):
    """<meta property|name=... content=...> を集める簡易パーサ。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.metas: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "meta":
            return
        a = {k.lower(): (v or "") for k, v in attrs}
        key = (a.get("property") or a.get("name") or "").strip().lower()
        content = a.get("content", "").strip()
        if key in _META_KEYS and content and key not in self.metas:
            self.metas[key] = content


def extract_meta_image(html: str, base_url: str) -> str | None:
    """HTML文字列から og:image → twitter:image の順で画像URL（httpsのみ）を返す。"""
    parser = _MetaImageParser()
    try:
        parser.feed(html)
    except Exception:  # noqa: BLE001 壊れたHTMLでも取れた分だけ使う
        pass
    for key in _META_KEYS:
        u = to_https_image_url(parser.metas.get(key), base_url)
        if u:
            return u
    return None


def fetch_image_url(source_url: str) -> str | None:
    """source_urlのHTMLを取得して画像URLを返す。失敗時はNone（例外は投げない）。"""
    try:
        resp = requests.get(
            source_url,
            headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
            timeout=FETCH_TIMEOUT_SEC,
            stream=True,
        )
        try:
            resp.raise_for_status()
            chunks: list[bytes] = []
            size = 0
            for chunk in resp.iter_content(chunk_size=16384):
                chunks.append(chunk)
                size += len(chunk)
                if size >= MAX_HTML_BYTES:
                    break
            raw = b"".join(chunks)
            encoding = resp.encoding or "utf-8"
            html = raw.decode(encoding, errors="replace")
            return extract_meta_image(html, resp.url or source_url)
        finally:
            resp.close()
    except Exception as e:  # noqa: BLE001 1件の失敗で全体を止めない
        log.warning("画像取得失敗: %s (%s)", source_url, e)
        return None


def enrich_issue(issue: dict) -> tuple[int, list[str]]:
    """号データのimage_urlを補完する（in-place）。(新規に付与した件数, 失敗したsource_urlのリスト)を返す。"""
    added = 0
    failed: list[str] = []
    for art in issue.get("articles", []):
        if art.get("image_url"):
            # 候補由来でimage_urlはあるがcreditが無い場合だけ補う
            if not art.get("image_credit") and art.get("source_name"):
                art["image_credit"] = art["source_name"]
            continue
        url = art.get("source_url")
        if not url:
            continue
        img = fetch_image_url(url)
        if img:
            art["image_url"] = img
            art["image_credit"] = art.get("source_name", "")
            added += 1
        else:
            failed.append(url)
    return added, failed


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="AI新聞: 号データの画像補完（og:image/twitter:image）")
    parser.add_argument("file", help="data/issues/YYYY-MM-DD.json のパス")
    args = parser.parse_args(argv)

    path = Path(args.file)
    if not path.exists():
        print(f"エラー: ファイルが存在しません: {path}", file=sys.stderr)
        return 1
    issue = json.loads(path.read_text(encoding="utf-8"))
    added, failed = enrich_issue(issue)
    path.write_text(json.dumps(issue, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    total = len(issue.get("articles", []))
    with_img = sum(1 for a in issue.get("articles", []) if a.get("image_url"))
    print(f"画像補完: 今回 {added} 件追加 / 画像あり {with_img}/{total} 件")
    for u in failed:
        print(f"  画像なし: {u}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
