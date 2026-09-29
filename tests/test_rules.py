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


# ---- 소스 region_hint ---------------------------------------------------
def test_source_region_hint_fills_the_gap_bare_sigun_names_leave():
    """extract_regions 는 맨 시군 이름을 일부러 인정하지 않는다.

    '고성→고성능', '양산→대량양산' 오탐을 막으려는 절충인데, 그 바람에
    '진주보건대학교'의 '진주'도 놓쳐 +15 를 못 받는다. config/sources.yaml 의
    region_hint 는 우리가 적어 둔 값이므로 그 판단을 거치지 않아도 된다.
    """
    from gia.classify.rules import score_posting

    t = "2026학년도 2학기 진주보건대학교 평생교육원 강좌 개설 신청 공고"
    assert score_posting(t).score == 55
    assert score_posting(t, source_regions=["경남", "진주"]).score == 70


def test_source_region_hint_is_not_added_twice():
    from gia.classify.rules import score_posting

    r = score_posting("부산대학교 평생교육원 시간강사 모집", source_regions=["부산"])
    assert sum(1 for x in r.reasons if "부·울·경 지역" in x) == 1


def test_source_region_hint_does_not_mask_other_region_penalty():
    """기관이 경남에 있어도 근무지가 서울이면 그대로 깎여야 한다.

    타지역 감점은 공고가 스스로 밝힌 근무지를 보는 것이다. 기관 소재지로
    덮으면 서울 일자리가 부·울·경 목록에 섞인다.
    """
    from gia.classify.rules import score_posting

    r = score_posting("평생교육원 협력기관 강사 모집", body="근무지: 서울특별시 강남구",
                      source_regions=["경남", "진주"])
    assert any("타지역(서울)" in x for x in r.reasons)


# --- 2026-09-29: 경남 저장소에서 찾은 것을 옮긴다 ---

def test_fixed_term_worker_without_teaching_word_is_excluded():
    """'기간제근로자'만 적힌 제목은 행정·관리 자리다. 본문에 '지도사'가 있어도 제외한다."""
    from gia.classify.rules import score_posting, title_veto

    assert score_posting("진해국민체육센터 기간제근로자(초단시간) 채용공고", "생활체육 지도사 협조. 창원시", None).score < 30
    assert title_veto("하동군 청소년방과후아카데미 기간제근로자 채용 공고") == "제외: 비강사 직종(기간제근로자)"


def test_non_instructor_veto_spares_titles_with_a_teaching_word():
    """가르치는 자리를 함께 뽑는 공고는 제목만으로 잘라내지 않는다."""
    from gia.classify.rules import score_posting, title_veto

    assert title_veto("체육센터 기간제근로자(헬스지도자, 청사관리원) 채용") is None
    r = score_posting("체육센터 기간제근로자(헬스지도자, 청사관리원) 채용", "부산시", None)
    assert not any("비강사" in x for x in r.reasons)
    # 청원경찰도 마찬가지다 — 제목에 핵심어가 없을 때만 걸린다
    assert title_veto("2026년 창원시 청원경찰 채용시험 계획 공고") == "제외: 비강사 직종(청원경찰)"
    assert title_veto("평생교육원 시간강사 모집") is None


def test_lesson_word_counts_as_instructor_posting():
    """체육 계열은 가르치는 자리를 '수영강습'처럼 강습으로만 적는다."""
    from gia.classify.rules import score_posting, title_veto

    assert score_posting("시민생활체육관 수영강습 강사 모집", "부산시", None).score >= 70
    # 수강생을 부르는 글은 강습이 들어가도 그대로 걸러진다
    assert title_veto("2026년 하반기 수영강습 수강생 모집") is not None
