from datetime import timedelta

from gia.models import Status
from gia.store import Store
from tests.conftest import NOW, make_posting


def test_roundtrip(tmp_path):
    s = Store(tmp_path)
    p = make_posting("강사 모집", deadline=NOW + timedelta(days=10))
    s.upsert(p)
    s.state["last_run_at"] = NOW.isoformat()
    s.save()
    s2 = Store(tmp_path).load()
    assert s2.get(p.canonical_key).title == "강사 모집"
    assert s2.by_url(p.sources[0].url) is not None
    assert (tmp_path / "postings" / "2026-09.jsonl").exists()


def test_status_transitions(tmp_path):
    s = Store(tmp_path)
    soon = make_posting("A 강사", deadline=NOW + timedelta(days=2))
    later = make_posting("B 강사", deadline=NOW + timedelta(days=20))
    past = make_posting("C 강사", deadline=NOW - timedelta(days=1))
    for p in (soon, later, past):
        s.upsert(p)
    s.refresh_statuses(NOW, 3)
    assert s.get(past.canonical_key).status == Status.expired
    assert s.get(soon.canonical_key).status == Status.new  # 아직 보고 전
    s.mark_reported([soon.canonical_key, later.canonical_key], NOW, 3)
    assert s.get(soon.canonical_key).status == Status.closing_soon
    assert s.get(later.canonical_key).status == Status.active
    assert s.state["last_report_at"] == NOW.isoformat()


def test_reported_on_counts_by_kst_date(tmp_path):
    """하루 한 번 제한은 '24시간'이 아니라 한국 날짜로 센다.

    시간으로 세면, 밀려서 늦게 돈 날의 시각이 다음 날 기준이 되어 발송 시각이
    하루씩 뒤로 끌린다.
    """
    from datetime import date, datetime, timedelta, timezone

    from gia.store import Store

    KST = timezone(timedelta(hours=9))
    s = Store(tmp_path)
    assert s.reported_on(date(2026, 9, 29)) is False, "보낸 적 없으면 False"

    s.state["last_report_at"] = datetime(2026, 9, 29, 2, 0, tzinfo=KST).isoformat()
    assert s.reported_on(date(2026, 9, 29)) is True, "같은 날이면 막는다"
    # 21시간밖에 안 지났지만 날이 바뀌었으므로 보낸다
    assert s.reported_on(date(2026, 9, 30)) is False

    # UTC 로 적힌 기록도 한국 날짜로 환산한다 (9/29 23:00 UTC = 9/30 08:00 KST)
    s.state["last_report_at"] = datetime(2026, 9, 29, 23, 0, tzinfo=timezone.utc).isoformat()
    assert s.reported_on(date(2026, 9, 30)) is True

    s.state["last_report_at"] = "말이 안 되는 값"
    assert s.reported_on(date(2026, 9, 30)) is False, "못 읽으면 막지 않는다"
