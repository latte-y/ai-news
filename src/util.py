"""collect / validate / build / notify から共通で使う小さなユーティリティ群。

日本時間(JST)の日付計算、URL正規化、HTMLタグ除去をまとめている。
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin, urlsplit, urlunsplit, parse_qsl, urlencode

JST = timezone(timedelta(hours=9))

#: RSSのdescriptionからHTMLタグを取り除くための簡易パターン（依存を増やさないため正規表現で処理）
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")

#: 重複配信除去・トラッキング目的でよく付与されるクエリパラメータ
_TRACKING_PREFIXES = ("utm_", "ref_", "icid")
_TRACKING_EXACT = {"ref", "source", "spm", "fbclid", "gclid", "mc_cid", "mc_eid"}


def jst_now() -> datetime:
    """現在時刻をJSTで返す。"""
    return datetime.now(JST)


def jst_today_str(date_override: str | None = None) -> str:
    """JSTの日付文字列（YYYY-MM-DD）を返す。--date指定があればそれをそのまま使う。"""
    if date_override:
        # 形式チェック（不正なら例外を上げてCLI側でエラーにする）
        datetime.strptime(date_override, "%Y-%m-%d")
        return date_override
    return jst_now().strftime("%Y-%m-%d")


def parse_date_arg(date_str: str) -> datetime:
    """YYYY-MM-DD文字列をJST 07:00のdatetimeに変換する（collectの基準時刻用）。"""
    d = datetime.strptime(date_str, "%Y-%m-%d")
    return d.replace(hour=7, minute=0, second=0, tzinfo=JST)


def normalize_url(url: str) -> str:
    """URLを正規化する（トラッキングクエリ除去・末尾スラッシュ統一・フラグメント除去）。

    重複記事の判定に使う。スキーム・ホストは小文字化しない
    （大文字小文字を区別するパスを持つサイトが稀にあるため）。
    """
    parts = urlsplit(url.strip())
    kept = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith(_TRACKING_PREFIXES) and k.lower() not in _TRACKING_EXACT
    ]
    query = urlencode(kept)
    path = parts.path
    if path.endswith("/") and path != "/":
        path = path[:-1]
    return urlunsplit((parts.scheme, parts.netloc, path, query, ""))


def strip_html(text: str, max_len: int = 600) -> str:
    """HTMLタグを除去し、空白を1つに畳んで、最大max_len字に切り詰める。"""
    if not text:
        return ""
    plain = _TAG_RE.sub(" ", text)
    plain = plain.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"').replace("&#39;", "'")
    plain = _WS_RE.sub(" ", plain).strip()
    if len(plain) > max_len:
        plain = plain[: max_len - 1].rstrip() + "…"
    return plain


def to_https_image_url(url: str | None, base_url: str = "") -> str | None:
    """画像URLを絶対URL化し、httpsのものだけ返す（それ以外はNone）。

    相対URL・プロトコル相対URL（//host/...）は base_url を基準に絶対化する。
    """
    if not url or not isinstance(url, str):
        return None
    url = url.strip().replace("&amp;", "&")
    if not url or url.startswith("data:"):
        return None
    absolute = urljoin(base_url, url) if base_url else url
    parts = urlsplit(absolute)
    if parts.scheme != "https" or not parts.netloc:
        return None
    return absolute
