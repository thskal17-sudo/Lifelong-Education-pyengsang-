from datetime import date, datetime

import pytest

from gia.extract.deadline import KST, DeadlineType, parse_deadline, parse_known_format

REF = date(2026, 9, 15)

CASES = [
    ("접수기간: 2026. 9. 22.(월) ~ 2026. 9. 30.(수) 18:00까지", datetime(2026, 9, 30, 18, 0, tzinfo=KST)),
    ("제출기한 2026.09.30.(수)", datetime(2026, 9, 30, 23, 59, tzinfo=KST)),
    ("2026년 9월 30일 18시까지 접수", datetime(2026, 9, 30, 18, 0, tzinfo=KST)),
    ("접수: 9. 22.(월) ~ 9. 30.(수)", datetime(2026, 9, 30, 23, 59, tzinfo=KST)),
    ("공고기간 2026-09-16 ~ 2026-09-25", datetime(2026, 9, 25, 23, 59, tzinfo=KST)),
    ("면접일: 2026. 10. 5.(월) / 서류 제출 마감: 2026. 9. 28.(월) 오후 6시", datetime(2026, 9, 28, 18, 0, tzinfo=KST)),
    ("접수마감 12. 3.(목) 17:00까지", datetime(2026, 12, 3, 17, 0, tzinfo=KST)),
    ("접수기간 2026.12.20 ~ 1.10 까지", datetime(2027, 1, 10, 23, 59, tzinfo=KST)),
]


@pytest.mark.parametrize("text,expected", CASES)
def test_fixed_deadlines(text, expected):
    res = parse_deadline(text, REF)
    assert res.deadline_type == DeadlineType.fixed
    assert res.deadline == expected


def test_until_filled():
    res = parse_deadline("모집인원 충원 시까지 상시 접수", REF)
    assert res.deadline_type == DeadlineType.until_filled
    assert res.deadline is None


def test_unknown_when_only_dates_are_negative_context():
    res = parse_deadline("면접일 2026. 10. 5.(월), 합격자 발표 2026. 10. 7.(수)", REF)
    assert res.deadline is None
    assert res.deadline_type == DeadlineType.unknown


def test_partial_without_context_is_ignored():
    res = parse_deadline("강의시간은 주 1.5시간이며 3.5명 규모입니다", REF)
    assert res.deadline is None


def test_known_formats():
    assert parse_known_format("20260930") == datetime(2026, 9, 30, 23, 59, tzinfo=KST)
    assert parse_known_format("2026-09-30 18:00:00") == datetime(2026, 9, 30, 18, 0, tzinfo=KST)
    assert parse_known_format("상시") is None


# --- 2026-09-22 실수집에서 나온 오판 회귀 테스트 ---

def test_past_year_date_is_not_a_deadline():
    """근거 규정·사업연도로 적힌 과거 날짜를 마감일로 잡지 않는다 (창원시 청원경찰 공고)."""
    text = "청원경찰법 시행규칙(2017.12.31.)에 따라 시행합니다."
    assert parse_deadline(text, REF).deadline is None


def test_past_year_date_loses_to_real_deadline():
    text = "근거: 규칙(2017.12.31.) / 접수기간: 2026. 9. 25.(금) 18:00까지"
    res = parse_deadline(text, REF)
    assert res.deadline == datetime(2026, 9, 25, 18, 0, tzinfo=KST)


def test_contract_end_date_far_in_future_is_not_a_deadline():
    """계약·근무기간 종료일(1년 초과)을 마감일로 잡지 않는다 (하동군 방과후아카데미 공고)."""
    assert parse_deadline("근무기간: 2026.10.01. ~ 2027.09.30.", REF).deadline is None
    res = parse_deadline("계약기간 2026.10.01.~2027.09.30. 접수기간 2026. 9. 30.(수)까지", REF)
    assert res.deadline == datetime(2026, 9, 30, 23, 59, tzinfo=KST)


def test_deadline_window_bounds():
    from gia.extract.deadline import in_deadline_window
    assert in_deadline_window(date(2026, 9, 20), REF)      # 게시일 직전 (게시일 추정 오차)
    assert not in_deadline_window(date(2026, 7, 1), REF)   # 30일보다 이전
    assert in_deadline_window(date(2027, 9, 1), REF)       # 1년 이내
    assert not in_deadline_window(date(2027, 12, 1), REF)  # 1년 초과


# --- 2026-09-22 창원시설공단·통영국제음악재단 오판 회귀 테스트 (#19) ---

def test_posting_date_without_context_is_not_a_deadline():
    """본문이 짧고 공고문이 첨부인 그누보드 게시글: 첨부 등록 시각(DATE :)을 마감으로 잡지 않는다."""
    text = ("[성산스포츠센터] 생활체육(요가) 도급강사 경력경쟁모집 공고 작성자 전재일 댓글 0건 조회 220회 "
            "작성일 2026-09-10 본문 첨부파일 응시원서 및 제출서류성산스포츠센터.hwp (34.5K) "
            "10회 다운로드 | DATE : 2026-09-10 16:50:57 목록")
    res = parse_deadline(text, date(2026, 9, 10))
    assert res.deadline is None
    assert res.deadline_type == DeadlineType.unknown


def test_signature_date_equal_to_posting_date_is_ignored():
    """공문 말미의 서명 일자(게시일과 같은 날)는 마감이 아니다."""
    text = "통영시민오케스트라 교육강사를 모집하오니 유능한 인재의 많은 지원 바랍니다. 2026 년 9 월 21 일 재단법인 통영국제음악재단 이사장"
    res = parse_deadline(text, date(2026, 9, 21))
    assert res.deadline is None


def test_same_day_deadline_with_context_is_kept():
    """게시일과 같은 날이라도 '까지' 등 마감 문맥이 있으면 마감으로 인정한다."""
    text = "접수기간: 2026. 9. 10.(수) 09:00 ~ 2026. 9. 10.(수) 18:00까지"
    res = parse_deadline(text, date(2026, 9, 10))
    assert res.deadline == datetime(2026, 9, 10, 18, 0, tzinfo=KST)


def test_later_date_without_context_still_parses():
    """게시일 이후의 날짜는 문맥이 없어도 기존처럼 마감 후보로 남긴다 (회귀 방지)."""
    text = "공고문 참조. 2026. 9. 30.(수) 18:00"
    res = parse_deadline(text, date(2026, 9, 10))
    assert res.deadline == datetime(2026, 9, 30, 18, 0, tzinfo=KST)


def test_short_year_dates_from_attachment_table():
    """첨부 HWP 표에서 접수기간이 '26.09.10' / '26.09.11' 처럼 두 자리 연도로 줄마다 떨어져 나오는 경우 (창원시설공단 요가 강사 공고)."""
    ref = date(2026, 9, 10)
    body = "접수기간\n26.09.10\n26.09.11\n접수번호\n12회 다운로드 | DATE : 2026-09-10 16:50:57"
    res = parse_deadline(body, ref)
    assert res.deadline == datetime(2026, 9, 11, 23, 59, tzinfo=KST)
    assert res.text == "26.09.11"
    # 게시일과 같은 두 자리 연도 날짜만 있으면 마감으로 잡지 않는다
    assert parse_deadline("작성일 26.09.10", ref).deadline is None
    # 문맥이 있으면 그대로
    assert parse_deadline("접수: 26.9.30(수) 18:00까지", ref).deadline == datetime(2026, 9, 30, 18, 0, tzinfo=KST)
    # 버전·번호 형태는 날짜로 보지 않는다
    assert parse_deadline("문서번호 1.26.09.11-3", ref).deadline is None
    assert parse_known_format("26.09.30") == datetime(2026, 9, 30, 23, 59, tzinfo=KST)


def test_until_filled_variants():
    """'수시 접수'(거제대 평생학습원 강사 모집 안내)·'연중 상시' 도 채용 시까지로 본다."""
    for text in ("1. 모집기간 : 수시 접수", "수시모집", "연중 상시 접수", "상시 모집"):
        res = parse_deadline(text, date(2026, 9, 22))
        assert res.deadline is None and res.deadline_type == DeadlineType.until_filled, text


def test_contest_period_beats_class_period():
    """부산대 미래시민교육원 강좌 공모 (2026-11-04). 공모 기간 끝(11.15)이 마감이고, 교육 기간 끝(2027.2.5)은 아니다.
    첨부에서 뽑은 글이라 '공모 기간', '교육 기간' 처럼 띄어 쓰여 있고 날짜 앞에 범위 시작일이 있다."""
    text = (
        "Ⅰ 강좌 공모 가 . 공모개요 ○ 공모 학기 : 2026 학년도 겨울계절학기 "
        "○ 공모 기간 : 2026. 11. 2.( 월 ) ~ 2026. 11. 15.( 일 ) ○ 공모 대상 : 강좌 개설을 희망하는 개인 "
        "나 . 26 학년도 겨울계절학기 강좌 운영 ○ 교육 기간 : 2027. 1. 4.( 월 ) ~ 2027. 2. 5.( 금 ), 과정별 상이"
    )
    res = parse_deadline(text, date(2026, 10, 26))
    assert res.deadline_type == DeadlineType.fixed
    assert res.deadline == datetime(2026, 11, 15, 23, 59, tzinfo=KST)


def test_spaced_class_period_loses_to_application_period():
    """띄어 쓴 '운영 기간' 끝 날짜는 '접수 기간' 끝 날짜에 진다 (늦은 날짜라도)."""
    text = "○ 운영 기간 : 2026. 12. 1.( 화 ) ~ 2026. 12. 20.( 일 ) ○ 접수 기간 : 2026. 9. 16.( 수 ) ~ 2026. 9. 25.( 금 )"
    res = parse_deadline(text, REF)
    assert res.deadline == datetime(2026, 9, 25, 23, 59, tzinfo=KST)


def test_bullet_hyphen_on_next_line_is_not_a_range_start():
    """마산대 평생교육원 (2026-11-10). 기간 끝 날짜 바로 다음 줄이 '- 신청방법:' 처럼 글머리표로 시작한다.
    그 '-' 를 범위 시작 기호로 세면 신청 마감이 깎여 뒤에 오는 운영기간 끝(2027.01.29)에 밀린다."""
    text = (
        "Ⅰ. 강좌개설 신청\n"
        "- 기간: 2026.10.26.(월) ~ 11.13.(금)\n"
        "- 방법: e-mail 접수 (gpdls6770@masan.ac.kr)\n"
        "Ⅱ. 강좌운영 계획\n"
        "- 운영기간: 2026.12.01.(화) ~ 2027.01.29.(금)\n"
    )
    res = parse_deadline(text, date(2026, 10, 26))
    assert res.deadline_type == DeadlineType.fixed
    assert res.deadline == datetime(2026, 11, 13, 23, 59, tzinfo=KST)


def test_application_period_end_without_year():
    """같은 공고의 '신청기간: 2026.11.09.(월) ~ 12.24.(목)' — 끝 날짜에 연도가 없어도 게시 연도로 읽는다."""
    text = (
        "Ⅰ. 강좌개설 신청\n"
        "- 신청기간: 2026.11.09.(월) ~ 12.24.(목)\n"
        "- 신청방법: e-mail 접수\n"
        "Ⅱ. 강좌운영 계획\n"
        "- 운영기간: 2027.03.08.(월) ~ 06.05.(토)\n"
    )
    res = parse_deadline(text, date(2026, 11, 10))
    assert res.deadline == datetime(2026, 12, 24, 23, 59, tzinfo=KST)


def test_same_line_hyphen_range_still_counts():
    """같은 줄에서 숫자로 이어지는 '-' 는 그대로 범위 시작으로 본다 (시작일이 마감으로 뽑히지 않는다)."""
    text = "접수기간 2026. 9. 16. - 2026. 9. 25."
    res = parse_deadline(text, REF)
    assert res.deadline == datetime(2026, 9, 25, 23, 59, tzinfo=KST)
