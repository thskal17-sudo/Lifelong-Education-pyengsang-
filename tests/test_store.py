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
