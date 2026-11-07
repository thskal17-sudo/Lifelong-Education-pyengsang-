"""저장소에 남아 있던 중복 합치기 (기관명 설정이 바뀌어 같은 공고가 된 옛 기록)."""
from __future__ import annotations

from datetime import datetime

from gia.dedupe import canonical_key, merge_stored_duplicates
from gia.extract.deadline import KST
from gia.models import OrgType, Posting, SourceRef
from gia.store import Store

NOW = datetime(2026, 11, 7, 12, 0, tzinfo=KST)
제목 = "2026학년도 2학기 평생교육과정 동계방학특강 개설 제안 공모 안내"


def _posting(org: str, source_id: str, url: str, seen_day: int) -> Posting:
    seen = datetime(2026, 10, seen_day, 9, 0, tzinfo=KST)
    return Posting(
        id=f"{source_id}-1", canonical_key=canonical_key(org, 제목), title=제목, org_name=org,
        org_type=OrgType.university,
        sources=[SourceRef(source_id=source_id, url=url, fetched_at=seen)],
        first_seen_at=seen, last_seen_at=seen,
    )


def _store(tmp_path, postings):
    s = Store(tmp_path / "data")
    for p in postings:
        s.upsert(p)
    return s


def test_같은_기관_같은_제목이면_하나로_합친다(tmp_path):
    """마산대는 공지사항과 강좌 개설 신청 두 게시판에 같은 공고가 올라온다."""
    org = "마산대학교 평생교육원"
    a = _posting(org, "masan_lifelong", "https://lifelong.masan.ac.kr/boardview/000001/295", 27)
    b = _posting(org, "masan_lectopen", "https://lifelong.masan.ac.kr/lectopen/view/2026/20/010/999/19", 28)
    # 옛 기록은 키가 서로 다르다 (기관명이 달랐을 때 저장됐다)
    b.canonical_key = canonical_key("마산대학교 평생교육원 강좌 개설 신청", 제목)
    store = _store(tmp_path, [a, b])
    assert len(list(store.values())) == 2

    합친수 = merge_stored_duplicates(store, NOW)

    assert 합친수 == 1
    남은 = list(store.values())
    assert len(남은) == 1
    # 먼저 들어온 쪽에 두 출처가 모인다
    assert sorted(s.source_id for s in 남은[0].sources) == ["masan_lectopen", "masan_lifelong"]
    assert 남은[0].first_seen_at == a.first_seen_at


def test_기관이_다르면_합치지_않는다(tmp_path):
    a = _posting("마산대학교 평생교육원", "masan_lifelong", "https://a", 27)
    b = _posting("창원대학교 평생교육원", "cwnu_lifelong", "https://b", 28)
    store = _store(tmp_path, [a, b])
    assert merge_stored_duplicates(store, NOW) == 0
    assert len(list(store.values())) == 2


def test_합칠_것이_없으면_아무것도_하지_않는다(tmp_path):
    store = _store(tmp_path, [_posting("마산대학교 평생교육원", "masan_lifelong", "https://a", 27)])
    assert merge_stored_duplicates(store, NOW) == 0
    assert len(list(store.values())) == 1
