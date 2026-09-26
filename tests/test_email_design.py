"""메일 템플릿이 사이트와 같은 디자인 토큰을 쓰는지 지킨다."""
from datetime import datetime, timedelta

from gia.extract.deadline import KST
from gia.models import Posting, SourceRef
from gia.report.build import ReportData, is_urgent, render_email

NOW = datetime(2026, 9, 26, 9, 0, tzinfo=KST)


def _posting(title: str, days: int | None) -> Posting:
    dl = (NOW + timedelta(days=days)).replace(hour=23, minute=59) if days is not None else None
    return Posting(
        id=title, canonical_key=title, title=title, org_name="어느대 평생교육원",
        org_type="university", field="어학", employment_type="시간강사", region=["부산"],
        deadline=dl, relevance_score=90,
        sources=[SourceRef(source_id="s", url="https://example.org/1", fetched_at=NOW)],
        first_seen_at=NOW, last_seen_at=NOW,
    )


def test_is_urgent_only_within_window():
    assert is_urgent(_posting("내일", 1), NOW)
    assert is_urgent(_posting("오늘", 0), NOW)
    assert not is_urgent(_posting("멀었다", 9), NOW)
    assert not is_urgent(_posting("마감없음", None), NOW)


def test_email_uses_site_design_tokens():
    data = ReportData(date_str="2026-09-26 (토)", new=[_posting("신규 공고 하나", 9)], closing_days=3)
    html = render_email(data, NOW, "https://example.org/site/")
    assert "#3182f6" in html and "#191f28" in html  # 토스 블루 / 잉크
    assert "Pretendard" in html
    # 지메일은 웹폰트를 막는다. 시스템 한글 폰트로 떨어질 자리가 있어야 한다
    assert "Apple SD Gothic Neo" in html and "Malgun Gothic" in html
    # 아웃룩은 gradient 를 못 읽는다. bgcolor 로 받쳐 둔 표지가 있어야 한다
    assert 'bgcolor="#dcefff"' in html
    assert "https://example.org/site/" in html  # 전체 목록 버튼


def test_email_marks_closing_soon_red():
    urgent = ReportData(date_str="d", closing=[_posting("내일 마감", 1)], closing_days=3)
    calm = ReportData(date_str="d", new=[_posting("여유 있음", 30)], closing_days=3)
    assert "#f04452" in render_email(urgent, NOW)
    assert "#f04452" not in render_email(calm, NOW)
