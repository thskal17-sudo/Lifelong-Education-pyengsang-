"""텔레그램 봇 발송 (docs/DESIGN.md 10절)."""
from __future__ import annotations

import httpx

TELEGRAM_LIMIT = 4000


def split_message(text: str, limit: int = TELEGRAM_LIMIT) -> list[str]:
    """빈 줄(섹션 경계) 우선, 그다음 줄 단위로 나눈다."""
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    cur = ""
    for para in text.split("\n\n"):
        piece = para if not cur else "\n\n" + para
        if len(cur) + len(piece) <= limit:
            cur += piece
            continue
        if cur:
            chunks.append(cur)
            cur = ""
        if len(para) <= limit:
            cur = para
            continue
        for line in para.split("\n"):
            piece = line if not cur else "\n" + line
            if len(cur) + len(piece) > limit:
                chunks.append(cur)
                cur = line[:limit]
            else:
                cur += piece
    if cur:
        chunks.append(cur)
    return chunks


def send_telegram(token: str, chat_id: str, html: str, client: httpx.Client | None = None) -> int:
    """메시지를 보내고 전송한 조각 수를 돌려준다."""
    own = client is None
    client = client or httpx.Client(timeout=20)
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    sent = 0
    try:
        for chunk in split_message(html):
            r = client.post(url, json={"chat_id": chat_id, "text": chunk, "parse_mode": "HTML", "disable_web_page_preview": True})
            if r.status_code >= 400:
                raise RuntimeError(f"텔레그램 전송 실패 HTTP {r.status_code}: {r.text[:200]}")
            sent += 1
    finally:
        if own:
            client.close()
    return sent
