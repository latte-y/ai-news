"""Gmail SMTP_SSL でHTMLメールを送信するモジュール。

stock-alert (~/work/stock-alert/src/mailer.py) と同じ方式:
smtplib.SMTP_SSL("smtp.gmail.com", 465) + GMAIL_APP_PASSWORD 環境変数。
"""

from __future__ import annotations

import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

log = logging.getLogger(__name__)

# publicリポジトリのためアドレスはコードに書かず、Actions Secrets（GMAIL_USER）から渡す
GMAIL_USER = os.environ.get("GMAIL_USER", "")  # 送信元・送信先とも。MAIL_TO 環境変数で上書き可
GMAIL_PASS = os.environ.get("GMAIL_APP_PASSWORD", "")
MAIL_TO = os.environ.get("MAIL_TO") or GMAIL_USER  # シークレット未設定だと空文字が入るため or で判定


def send(html: str, subject: str) -> bool:
    """HTMLメールを Gmail SMTP_SSL 経由で送信する。

    Args:
        html: メール本文（HTML）。
        subject: 件名。

    Returns:
        送信に成功した場合 True、失敗した場合 False。
    """
    if not GMAIL_USER or not GMAIL_PASS:
        log.error("GMAIL_USER または GMAIL_APP_PASSWORD が未設定")
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = GMAIL_USER
    msg["To"] = MAIL_TO
    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_USER, GMAIL_PASS)
            server.sendmail(GMAIL_USER, MAIL_TO, msg.as_string())
        log.info("メール送信完了: %s", subject)
        return True
    except Exception as e:  # noqa: BLE001 パイプライン全体を落とさないため広く捕捉
        log.error("メール送信失敗: %s", e)
        return False
