"""일일 리포트 생성 (docs/DESIGN.md 9절, docs/DAILY_REPORT_TEMPLATE.md)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from jinja2 import Environment, PackageLoader, select_autoescape

from ..config import ConfigBundle
from ..extract.deadline import KST
from ..models import FIELD_NAMES, ORG_TYPE_ORDER, Posting, RunLog, Status
from ..stats import compute_stats
from ..store import Store

_WEEKDAYS = "월화수목금토일"


@dataclass
class ReportData:
    date_str: str
    closing: list[Posting] = field(default_factory=list)
    new: list[Posting] = field(default_factory=list)
    updated: list[Posting] = field(default_factory=list)
    run: RunLog | None = None
    source_names: dict[str, str] = field(default_factory=dict)
    telegram_max_items: int = 15
    closing_days: int = 3
    repo_url: str = ""
    overview: str | None = None
    weekly_md: str | None = None

    def keys(self) -> list[str]:
        return [p.canonical_key for p in self.closing + self.new + self.updated]


def select_postings(bundle: ConfigBundle, store: Store, now: datetime) -> ReportData:
    rs = bundle.settings.report
    horizon = now + timedelta(days=rs.closing_soon_days)
    closing: list[Posting] = []
    new: list[Posting] = []
    updated: list[Posting] = []
    for p in store.values():
        if p.status == Status.expired or (p.deadline and p.deadline < now) or "피드백제외" in p.flags:
            continue
        if p.deadline and p.deadline <= horizon:
            closing.append(p)
            continue
        if p.status == Status.new:
            new.append(p)
        elif p.status == Status.updated:
            updated.append(p)
    closing.sort(key=lambda p: p.deadline)  # type: ignore[arg-type]
    new.sort(key=lambda p: _new_sort_key(p, bundle))
    updated.sort(key=lambda p: p.last_seen_at, reverse=True)
    names = {s.id: s.name for s in bundle.sources}
    d = now.astimezone(KST)
    weekly = compute_stats(store.values(), now, 7).to_markdown() if rs.weekly_stats_weekday == d.weekday() else None
    return ReportData(
        date_str=f"{d:%Y-%m-%d} ({_WEEKDAYS[d.weekday()]})",
        closing=closing, new=new, updated=updated, run=store.last_run(), source_names=names,
        telegram_max_items=rs.telegram_max_items, closing_days=rs.closing_soon_days, weekly_md=weekly,
        repo_url=bundle.settings.collector.user_agent.split("+")[-1].rstrip(")") if "+" in bundle.settings.collector.user_agent else "",
    )


def _new_sort_key(p: Posting, bundle: ConfigBundle):
    w = bundle.settings.interests.weights.get(p.field, 1.0)
    kw_bonus = 10 if any(k in p.title for k in bundle.settings.interests.keywords) else 0
    dl = p.deadline.timestamp() if p.deadline else float("inf")
    return (-(w * p.relevance_score + kw_bonus), dl, ORG_TYPE_ORDER.index(p.org_type.value))


# ---- rendering ---------------------------------------------------------
def _env() -> Environment:
    env = Environment(loader=PackageLoader("gia.report", "templates"), autoescape=select_autoescape(["html"]), trim_blocks=True, lstrip_blocks=True)
    env.filters["field_name"] = lambda code: FIELD_NAMES.get(code, code)
    env.filters["deadline_str"] = deadline_str
    env.filters["dday"] = dday
    env.filters["region_str"] = lambda r: ", ".join(r) if r else "지역 미상"
    return env


def deadline_str(p: Posting) -> str:
    if p.deadline_type.value == "until_filled":
        return "채용 시까지"
    if not p.deadline:
        return "확인 필요"  # 템플릿이 앞에 "마감 "을 붙인다
    d = p.deadline.astimezone(KST)
    s = f"{d.month:02d}.{d.day:02d}({_WEEKDAYS[d.weekday()]})"
    if not (d.hour == 23 and d.minute == 59):
        s += f" {d:%H:%M}"
    return s


def dday(p: Posting, now: datetime | None = None) -> str:
    if not p.deadline:
        return ""
    now = now or datetime.now(KST)
    days = (p.deadline.astimezone(KST).date() - now.astimezone(KST).date()).days
    return "D-DAY" if days == 0 else f"D-{days}"


def render_markdown(data: ReportData, now: datetime) -> str:
    env = _env()
    env.filters["dday"] = lambda p: dday(p, now)
    return env.get_template("report.md.j2").render(r=data, now=now)


def render_telegram(data: ReportData, now: datetime) -> str:
    env = _env()
    env.filters["dday"] = lambda p: dday(p, now)
    return env.get_template("telegram.html.j2").render(r=data, now=now)


def render_email(data: ReportData, now: datetime) -> str:
    env = _env()
    env.filters["dday"] = lambda p: dday(p, now)
    return env.get_template("email.html.j2").render(r=data, now=now)


def email_subject(data: ReportData, now: datetime) -> str:
    d = now.astimezone(KST)
    return f"[부울경 평생교육원 강사공고] {d.month:02d}/{d.day:02d} 신규 {len(data.new)} · 마감임박 {len(data.closing)}"


def write_report(md: str, reports_dir: Path, now: datetime) -> Path:
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / f"{now.astimezone(KST):%Y-%m-%d}.md"
    path.write_text(md, encoding="utf-8")
    return path
