"""마감일 파서 (docs/DESIGN.md 6.2)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from ..models import DeadlineType

KST = ZoneInfo("Asia/Seoul")

_WEEKDAY = r"(?:\s*\(\s*[월화수목금토일]\s*(?:요일)?\s*\))?"
_TIME = r"(?:\s*(?:(?P<ampm>오전|오후)\s*)?(?P<hour>\d{1,2})\s*[:시]\s*(?P<minute>\d{2})?\s*분?)?"
_FULL = re.compile(
    r"(?P<year>\d{4})\s*[.년/\-]\s*(?P<month>\d{1,2})\s*[.월/\-]\s*(?P<day>\d{1,2})\s*일?\.?" + _WEEKDAY + _TIME
)
# 두 자리 연도 'YY.MM.DD' (첨부 HWP 표의 접수기간 '26.09.10 ~ 26.09.11', 게시판 날짜 열). 앞뒤에 숫자·점이 붙으면 제외
_SHORT_YEAR = re.compile(
    r"(?<![\d.\-/])(?P<year>2\d)\s*\.\s*(?P<month>\d{1,2})\s*\.\s*(?P<day>\d{1,2})\.?(?![\d.])" + _WEEKDAY + _TIME
)
_PARTIAL = re.compile(
    r"(?<![\d.\-/])(?P<month>\d{1,2})\s*[.월/]\s*(?P<day>\d{1,2})\s*일?\.?(?![\d])" + _WEEKDAY + _TIME
)
_UNTIL_FILLED = re.compile(r"채용\s*시\s*까지|충원\s*시\s*까지|(?:상시|수시)\s*(?:모집|채용|접수)|적격자\s*채용\s*시|모집\s*시\s*까지|연중\s*(?:상시|수시)")

# 마감일 유효 구간: 게시일보다 이만큼 이전이면 과거 날짜(사업연도·근거 규정 등), 이후면 계약·근무기간 종료일로 본다
PAST_SLACK_DAYS = 30
FUTURE_LIMIT_DAYS = 365

_POS_BEFORE = ["접수", "제출", "마감", "공고기간", "모집기간", "신청", "접수기간", "기한", "공고 기간", "모집 기간"]
_NEG_BEFORE = [
    "면접", "발표", "합격", "시험", "근무", "계약", "임용", "게시", "심사", "개강",
    "교육기간", "강의기간", "운영기간", "채용예정", "근무기간", "위촉기간", "임기", "작성일", "등록일",
    "DATE", "다운로드", "조회", "수정일", "작성자",
]
_RANGE_START = re.compile(r"^\s*(?:~|∼|～|-|–|—|부터)")

_KNOWN_FORMATS = ["%Y%m%d", "%Y-%m-%d", "%Y.%m.%d", "%Y/%m/%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y%m%d%H%M", "%y-%m-%d", "%y.%m.%d"]


@dataclass
class DeadlineResult:
    deadline: datetime | None
    deadline_type: DeadlineType
    text: str | None = None
    score: int = 0


def parse_known_format(value: str) -> datetime | None:
    """API가 주는 정형 문자열(20260930 등)을 KST datetime으로."""
    v = (value or "").strip()
    if not v:
        return None
    for fmt in _KNOWN_FORMATS:
        try:
            dt = datetime.strptime(v, fmt)
        except ValueError:
            continue
        if "%H" not in fmt:
            dt = dt.replace(hour=23, minute=59)
        return dt.replace(tzinfo=KST)
    return None


def parse_deadline(text: str, ref_date: date | None = None) -> DeadlineResult:
    """자유 텍스트에서 마감일을 찾는다. ref_date는 연도 생략 보정 기준(보통 게시일)."""
    if not text:
        return DeadlineResult(None, DeadlineType.unknown)
    ref = ref_date or date.today()
    candidates: list[tuple[int, datetime, str]] = []
    spans: list[tuple[int, int]] = []

    for m in _FULL.finditer(text):
        dt = _build(int(m.group("year")), int(m.group("month")), int(m.group("day")), m)
        if dt is None:
            continue
        spans.append(m.span())  # 구간은 기록해 부분 패턴이 같은 자리를 다시 읽지 않게 한다
        if not in_deadline_window(dt.date(), ref):
            continue
        sc = _score(text, m, partial=False)
        if sc <= 0 and dt.date() == ref:
            # 게시일과 같은 날짜가 마감 문맥 없이 나오면 작성·서명·첨부 등록 일자로 본다
            # (그누보드 'DATE : 2026-09-10 16:50:57', 공문 말미 '2026년 9월 21일 이사장')
            continue
        candidates.append((sc, dt, m.group(0).strip()))

    for m in _SHORT_YEAR.finditer(text):
        if any(s <= m.start() < e for s, e in spans):
            continue
        dt = _build(2000 + int(m.group("year")), int(m.group("month")), int(m.group("day")), m)
        if dt is None:
            continue
        spans.append(m.span())
        if not in_deadline_window(dt.date(), ref):
            continue
        sc = _score(text, m, partial=False)
        if sc <= 0 and dt.date() == ref:
            continue
        candidates.append((sc, dt, m.group(0).strip()))

    for m in _PARTIAL.finditer(text):
        if any(s <= m.start() < e for s, e in spans):
            continue
        year = ref.year
        dt = _build(year, int(m.group("month")), int(m.group("day")), m)
        if dt is None:
            continue
        if dt.date() < ref - timedelta(days=PAST_SLACK_DAYS):
            dt = dt.replace(year=year + 1)
        if not in_deadline_window(dt.date(), ref):
            continue
        sc = _score(text, m, partial=True)
        if sc <= 0:
            continue
        candidates.append((sc, dt, m.group(0).strip()))

    if candidates:
        candidates.sort(key=lambda c: (c[0], c[1]), reverse=True)
        best = candidates[0]
        if best[0] > -3:
            return DeadlineResult(best[1], DeadlineType.fixed, best[2], best[0])

    if _UNTIL_FILLED.search(text):
        return DeadlineResult(None, DeadlineType.until_filled, _UNTIL_FILLED.search(text).group(0))
    return DeadlineResult(None, DeadlineType.unknown)


def in_deadline_window(value: date, ref: date) -> bool:
    """접수 마감일로 볼 수 있는 날짜인지. 게시일 기준 과거 30일 ~ 미래 365일."""
    return ref - timedelta(days=PAST_SLACK_DAYS) <= value <= ref + timedelta(days=FUTURE_LIMIT_DAYS)


def _build(year: int, month: int, day: int, m: re.Match) -> datetime | None:
    hour, minute = 23, 59
    if m.group("hour"):
        hour = int(m.group("hour"))
        minute = int(m.group("minute") or 0)
        if m.group("ampm") == "오후" and hour < 12:
            hour += 12
        if hour > 24 or minute > 59:
            return None
        if hour == 24:
            hour, minute = 23, 59
    try:
        return datetime(year, month, day, hour, minute, tzinfo=KST)
    except ValueError:
        return None


def _score(text: str, m: re.Match, partial: bool) -> int:
    before = text[max(0, m.start() - 25): m.start()]
    after = text[m.end(): m.end() + 12]
    sc = 0
    for w in _POS_BEFORE:
        if w in before:
            sc += 2
    for w in _NEG_BEFORE:
        if w in before:
            sc -= 3
    if "까지" in after[:6]:
        sc += 3
    if _RANGE_START.match(after):
        sc -= 5  # 기간의 시작일
    if partial and ("~" in before[-3:] or "∼" in before[-3:] or "～" in before[-3:]):
        sc += 1  # 기간의 종료일
    if not partial and ("~" in before[-3:] or "∼" in before[-3:]):
        sc += 1
    return sc
