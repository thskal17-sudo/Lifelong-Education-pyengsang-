"""주간 통계 (docs/DESIGN.md F-11)."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .models import FIELD_NAMES, Posting, Status

ORG_TYPE_NAMES = {
    "local_gov": "지자체", "edu_office": "교육청", "local_public": "지방 출자출연", "central_public": "중앙 산하",
    "university": "대학", "private": "민간", "portal": "포털",
}


@dataclass
class Stats:
    days: int
    since: datetime
    total: int = 0
    by_org_type: Counter = field(default_factory=Counter)
    by_field: Counter = field(default_factory=Counter)
    by_region: Counter = field(default_factory=Counter)
    top_orgs: list[tuple[str, int]] = field(default_factory=list)
    active_total: int = 0
    closing_next_week: int = 0

    def to_markdown(self) -> str:
        if self.total == 0:
            return f"최근 {self.days}일 신규 공고 없음 (활성 {self.active_total}건)"
        lines = [f"최근 {self.days}일 신규 **{self.total}건** · 현재 활성 {self.active_total}건 · 7일 내 마감 {self.closing_next_week}건", ""]
        lines += ["| 분야 | 건수 |", "|---|---|"] + [f"| {FIELD_NAMES.get(k, k)} | {v} |" for k, v in self.by_field.most_common()]
        lines += ["", "| 기관 유형 | 건수 |", "|---|---|"] + [f"| {ORG_TYPE_NAMES.get(k, k)} | {v} |" for k, v in self.by_org_type.most_common()]
        if self.by_region:
            lines += ["", "| 지역 | 건수 |", "|---|---|"] + [f"| {k} | {v} |" for k, v in self.by_region.most_common(10)]
        if self.top_orgs:
            lines += ["", "기관별 상위: " + ", ".join(f"{o} {n}" for o, n in self.top_orgs)]
        return "\n".join(lines)


def compute_stats(postings, now: datetime, days: int = 7) -> Stats:
    since = now - timedelta(days=days)
    s = Stats(days=days, since=since)
    orgs: Counter = Counter()
    for p in postings:
        if p.status != Status.expired and "피드백제외" not in p.flags:
            s.active_total += 1
            if p.deadline and now <= p.deadline <= now + timedelta(days=7):
                s.closing_next_week += 1
        if p.first_seen_at < since or "피드백제외" in p.flags:
            continue
        s.total += 1
        s.by_org_type[p.org_type.value] += 1
        s.by_field[p.field] += 1
        for r in p.region or ["지역 미상"]:
            s.by_region[r] += 1
        orgs[p.org_name] += 1
    s.top_orgs = orgs.most_common(5)
    return s
