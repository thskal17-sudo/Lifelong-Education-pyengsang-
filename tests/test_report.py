from datetime import datetime, timedelta

from gia.models import Status
from gia.notify.telegram import split_message
from gia.report.build import ReportData, deadline_str, dday, render_markdown, render_telegram, select_postings
from gia.store import Store
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


def test_closing_window_counts_whole_days(settings, bundle, tmp_path):
    """마감이 그날 23:59 여도 D-3 에 잡혀야 한다.

    지금 시각에 3일을 더해 자르면 23:59 마감 공고가 15시간 차이로 밀려나,
    D-3 이 한 번도 뜨지 않고 D-2 에야 처음 나온다. 한국 공고는 23:59 마감이
    대부분이라 경고가 통째로 하루 늦어진다.
    """
    from gia.extract.deadline import KST

    now = datetime(2026, 9, 27, 8, 59, tzinfo=KST)
    store = Store(tmp_path)
    edge = make_posting("사흘 뒤 자정 마감", deadline=datetime(2026, 9, 30, 23, 59, tzinfo=KST), now=now)
    late = make_posting("나흘 뒤 마감", deadline=datetime(2026, 10, 1, 23, 59, tzinfo=KST), now=now)
    for p in (edge, late):
        p.status = Status.active
        store.upsert(p)
    bundle.settings.report.closing_soon_days = 3

    data = select_postings(bundle, store, now)
    titles = [p.title for p in data.closing]
    assert "사흘 뒤 자정 마감" in titles, "D-3 이 창 밖으로 밀렸다"
    assert "나흘 뒤 마감" not in titles, "창이 너무 넓어졌다"
