import pytest

from gia.classify.rules import guess_employment, guess_field, score_posting

INCLUDE = [
    ("2026년 하반기 평생학습관 시민강좌 강사 모집", "근무지: 창원시 평생학습관. 강의 가능한 분", None),
    ("한국폴리텍VII대학 진주캠퍼스 2학기 시간강사 채용 공고", "", "경남"),
    ("늘봄학교 프로그램 강사 인력풀 모집", "경남교육청 관내 초등학교 방과후 수업", None),
    ("생활체육지도자 채용 공고", "김해시 체육센터", None),
    ("2026년 하반기 시간강사 모집", "근무지: 부산광역시 해운대구", "부산"),   # 부산도 수집 대상
    ("평생교육원 정규강좌 신규 강사 모집", "울산대학교 평생교육원", None),
]
EXCLUDE = [
    ("2026 시민강좌 수강생 모집 안내", "강사: 홍길동", "경남"),
    ("강사 합격자 발표", "", "경남"),
    ("체육시설 물품 구매 입찰 공고", "강사 휴게실 비품", "경남"),
    ("2026년 하반기 시간강사 모집", "근무지: 서울특별시 강남구", "서울"),
    # 강사가 되려고 듣는 과정·운영 공지는 강사 채용이 아니다 (2026-09-23 부산 대학 수집에서 나온 오탐)
    ("파크골프 2급지도자(강사) 양성과정 모집안내(3기)", "수강료 20만원, 정원 20명", "부산"),
    ("2025학년도 하반기 특수분야 직무연수(버터케이크 플라워 데코레이션)", "연수 신청 안내", "부산"),
    ("8월 미래시민교육원 휴무일 안내", "광복절 휴무", "부산"),
]


@pytest.mark.parametrize("title,body,region", INCLUDE)
def test_include(title, body, region):
    assert score_posting(title, body, region).score >= 70


@pytest.mark.parametrize("title,body,region", EXCLUDE)
def test_exclude(title, body, region):
    assert score_posting(title, body, region).score < 30


def test_service_contract_not_penalized():
    r = score_posting("2026 직원 교육 운영 용역 입찰 공고 (강사 운영 포함)", "강의 운영 업체 모집", "경남")
    assert not any("조달어" in x for x in r.reasons)


def test_field_and_employment():
    assert guess_field("디지털배움터 스마트폰 교육 강사", "") == "it_digital"
    assert guess_field("수영 강사 모집", "체육센터") == "sports"
    assert guess_employment("시간강사 모집", "") == "시간강사"
    assert guess_employment("외부강사 위촉 공고", "") == "프리랜서"


# --- 2026-09-22 실수집에서 나온 오탐 회귀 테스트 ---

def test_non_instructor_job_titles_are_excluded():
    """제목에 강사 핵심어가 없고 비강사 직종이면, 본문에 '지도자'가 스쳐도 제외한다."""
    assert score_posting("2026년 창원시 청원경찰 채용시험 계획 공고", "체력검정은 지도자 입회하에 실시. 창원시", None).score < 30
    assert score_posting("초등학교 조리원 채용 공고", "지도자 협조. 김해시", None).score < 30


def test_non_instructor_penalty_not_applied_when_title_has_core_word():
    """제목에 강사 핵심어가 있으면 복합 모집일 수 있으므로 감점하지 않는다."""
    r = score_posting("하동국민체육센터 기간제근로자(헬스지도자, 청사관리원, 매표안내원) 채용", "하동군 체육센터", None)
    assert r.score >= 70
    assert not any("비강사" in x for x in r.reasons)


# ---- 수강생 모집 거부권 -------------------------------------------------
def test_student_call_is_vetoed_not_merely_penalised():
    """감점만으로는 모자랐다.

    울산과학대 '노인학습지도사 수강생 모집'은 과정 이름에 강사 핵심어(지도사)가
    박혀 있어 +50 을 먹고, -60 을 맞고도 35점으로 살아남아 목록에 남아 있었다.
    """
    from gia.classify.rules import score_posting

    r = score_posting("[모집](수업료 무료)2026 울산 시민학사 '노인학습지도사' 수강생 모집",
                      body="평생교육원 강사가 지도합니다", org_name="울산과학대학교 평생교육원")
    assert r.score == 0 and "수강생 모집" in r.reasons[0]


def test_combined_notice_survives_the_veto():
    """'강사 및 수강생 모집'은 강사를 부르는 글이기도 하다."""
    from gia.classify.rules import score_posting

    for t in ("2026학년도 2학기 평생교육원 강사 및 수강생 모집",
              "평생교육원 강사 모집 및 수강생 모집 안내"):
        r = score_posting(t, org_name="부산대학교 평생교육원")
        assert r.score >= 70, f"{t} → {r.score}점 · {r.reasons}"


def test_title_veto_needs_no_body():
    """gia prune 은 본문을 갖고 있지 않다. 본문이 필요한 판단을 섞으면 멀쩡한 공고를 지운다."""
    from gia.classify.rules import title_veto

    assert title_veto("2026 바리스타 과정 수강생 모집")
    assert title_veto("평생교육원 시간강사 모집 공고") is None
    assert title_veto("2026학년도 제2학기 신규 개설강좌 공모") is None
    # 본문에만 단서가 있는 글은 제목 거부권 대상이 아니다
    assert title_veto("2026학년도 2학기 공지사항") is None
