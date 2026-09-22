"""오탐·미탐 피드백 루프 (docs/DESIGN.md 14.2)."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .models import Posting, Status
from .store import Store

LABELS = ("false_positive", "false_negative", "wrong_deadline", "correct")
FEEDBACK_FLAG = "피드백제외"


def feedback_path(data_dir: Path) -> Path:
    return Path(data_dir) / "feedback.jsonl"


def load_feedback(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def append_feedback(path: Path, posting_id: str, label: str, note: str | None, now: datetime) -> dict:
    if label not in LABELS:
        raise ValueError(f"label은 {LABELS} 중 하나")
    entry = {"id": posting_id, "label": label, "note": note or "", "at": now.isoformat()}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def apply_feedback(store: Store, entries: list[dict], now: datetime) -> int:
    """false_positive 로 표시된 공고를 숨기고 재수집을 막는다. 반환: 적용 건수."""
    by_id = {p.id: p for p in store.values()}
    applied = 0
    for e in entries:
        if e.get("label") != "false_positive":
            continue
        p: Posting | None = by_id.get(e.get("id", ""))
        if p is None or FEEDBACK_FLAG in p.flags:
            continue
        p.flags.append(FEEDBACK_FLAG)
        p.status = Status.expired
        for s in p.sources:
            store.mark_excluded(s.url, now)
        applied += 1
    return applied
