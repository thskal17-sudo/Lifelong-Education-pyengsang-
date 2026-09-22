"""이메일 발송 (SMTP). docs/DESIGN.md 10절."""
from __future__ import annotations

import smtplib
from dataclasses import dataclass, field
from email.message import EmailMessage
from typing import Callable


@dataclass
class SmtpConfig:
    host: str
    port: int = 587
    user: str | None = None
    password: str | None = None
    sender: str | None = None
    to: list[str] = field(default_factory=list)
    use_ssl: bool | None = None  # None이면 포트 465일 때 SSL

    @classmethod
    def from_env(cls, env: dict) -> "SmtpConfig | None":
        host = env.get("SMTP_HOST")
        to = [x.strip() for x in (env.get("EMAIL_TO") or "").split(",") if x.strip()]
        if not host or not to:
            return None
        return cls(
            host=host, port=int(env.get("SMTP_PORT") or 587), user=env.get("SMTP_USER"),
            password=env.get("SMTP_PASSWORD"), sender=env.get("EMAIL_FROM") or env.get("SMTP_USER"), to=to,
        )


def build_message(cfg: SmtpConfig, subject: str, html: str, text: str) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f"부울경 평생교육원 강사공고 알림 <{cfg.sender}>" if cfg.sender else "부울경 평생교육원 강사공고 알림"
    msg["To"] = ", ".join(cfg.to)
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    return msg


def send_email(cfg: SmtpConfig, subject: str, html: str, text: str, smtp_factory: Callable | None = None) -> int:
    """메일을 보내고 수신자 수를 돌려준다. smtp_factory는 테스트용 주입점."""
    msg = build_message(cfg, subject, html, text)
    use_ssl = cfg.use_ssl if cfg.use_ssl is not None else cfg.port == 465
    factory = smtp_factory or (smtplib.SMTP_SSL if use_ssl else smtplib.SMTP)
    with factory(cfg.host, cfg.port, timeout=30) as smtp:
        if not use_ssl and smtp_factory is None:
            smtp.starttls()
        if cfg.user and cfg.password:
            smtp.login(cfg.user, cfg.password)
        smtp.send_message(msg)
    return len(cfg.to)
