from datetime import timedelta

from gia.notify.telegram import split_message
from gia.report.build import ReportData, deadline_str, dday, render_markdown, render_telegram
from tests.conftest import NOW, make_posting


def _data():
    closing = make_posting("수영강사 모집", org="창원시설공단", deadline=NOW + timedelta(days=1, hours=12), field="sports", region=["창원"])
    new = make_posting("시민강좌 강사 모집", deadline=NOW + timedelta(days=10), field="lifelong", region=["창원"], flags=["판별유보"])
    return ReportData(date_str="2026-09-21 (월)", closing=[closing], new=[new], updated=[], source_names={"src": "테스트 소스"})


def test_markdown_contains_sections():
    md = render_markdown(_data(), NOW)
    assert "## ⏰ 마감 임박" in md and "D-1" in md
    assert "[체육] 창원시설공단 · 수영강사 모집" in md
    assert "⚠ 강사 공고 여부 확인 필요" in md
    assert "(출처: 테스트 소스)" in md
    assert "실행 기록 없음" in md


def test_telegram_escapes_and_links():
    d = _data()
    d.new[0].title = "A&B <강사> 모집"
    html = render_telegram(d, NOW)
    assert "A&amp;B &lt;강사&gt; 모집" in html
    assert '<a href="https://example.org/' in html


def test_deadline_and_dday_formatting():
    p = make_posting("x", deadline=NOW.replace(hour=18, minute=0) + timedelta(days=9))
    assert deadline_str(p) == "09.30(수) 18:00"
    assert dday(p, NOW) == "D-9"
    q = make_posting("y", deadline=NOW + timedelta(hours=1))
    assert dday(q, NOW) == "D-DAY"


def test_split_message_respects_limit():
    text = "\n\n".join(f"섹션 {i} " + "가" * 900 for i in range(10))
    chunks = split_message(text, limit=4000)
    assert all(len(c) <= 4000 for c in chunks)
    assert "".join(c.replace("\n\n", "") for c in chunks).count("섹션") == 10
