"""강좌 개설 제안·공모를 강사 공고로 잡는다.

대학 평생교육원은 강사를 '강좌 개설 제안·공모'로 구한다. 강사가 강좌를 제안하면
심사해서 개설하고 그 사람이 강의를 맡는다. 제목에 '강사'라는 낱말이 없을 뿐이다.
"""
from pathlib import Path

from gia.classify.rules import score_posting
from gia.collectors.base import matches_keywords
from gia.config import load_sources, with_course_open_keywords

# 실제로 수집된 제목들
REAL = [
    "2026학년도 제2학기 신규 개설강좌 공모",
    "평생교육원 신규 강좌 개설 제안서 안내",
    "2026학년도 2학기 진주보건대학교 평생교육원 강좌 개설 신청 공고",
    "2026학년도 2학기 평생교육부 강좌 개설 희망자 모집 및 서류 제출 안내",
    "2026학년도 1학기 평생교육과정 하계방학특강 개설 제안 공모 안내",
]
# 수강생 대상이라 잡히면 안 되는 것들
STUDENT = [
    "2026학년도 2학기 신규 개설강좌 안내",
    "평생교육원 가을학기 수강생 모집",
]


def test_course_open_titles_reach_include_threshold():
    for t in REAL:
        r = score_posting(t, org_name="부산대학교 평생교육원")
        assert r.score >= 70, f"{t} → {r.score}점 · {r.reasons}"


def test_student_facing_notices_stay_out():
    for t in STUDENT:
        r = score_posting(t, body="이번 학기 강좌를 안내합니다", org_name="부산대학교 평생교육원")
        assert r.score < 70, f"{t} → {r.score}점 · {r.reasons}"


def test_every_enabled_source_lets_course_open_titles_through():
    """목록 필터에서 막히면 점수를 매길 기회조차 없다."""
    for s in load_sources(Path("config/sources.yaml")):
        if not s.enabled:
            continue
        kw = s.adapter.get("keywords")
        for t in REAL:
            assert matches_keywords(t, kw), f"{s.id} 가 '{t}' 를 막는다"


def test_pass_all_sources_are_left_alone():
    """keywords 가 없으면 전부 통과라는 뜻이다. 목록을 얹으면 오히려 좁아진다."""
    assert with_course_open_keywords(None) is None
    assert with_course_open_keywords([]) == []
    assert with_course_open_keywords(["강사"])[0] == "강사"
