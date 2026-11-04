"""본문 다듬기: HWP 에서 붙여넣은 공고문의 어긋난 공백을 되돌리고 항목 기호 앞에서 줄을 바꾼다."""
from __future__ import annotations

from gia.normalize import tidy_body

# 2026-11-04 창원대·부산대 공고 상세 화면이 한 덩어리로 보인다는 지적에서 출발했다.
창원대 = (
    "국립창원대학교 평생교육원 2027 학년도 제 1 학기 신규 개설강좌 공모 바랍니다 . "
    "2026 년 11 월 3일 평생교육원장 1. 모집부문 ○ AI 기반 전문 강좌 ( 예시 : 유튜브 , 챗 GPT ) "
    "2. 강사 응모자격 ○ 교육 · 연구경력 2 년 이상인 자 "
    "3. 원서접수 가 . 접수기간 : 2026. 11. 3.( 화 ) ~ 11. 13.( 금 ) 나 . 접수방법 : e-mail "
    "① 강좌 개설 신청서 1 부 ② 강의계획서 1 부"
)


def test_숫자와_단위_사이_공백을_붙인다():
    out = tidy_body(창원대)
    assert "2027학년도 제1학기" in out
    assert "2026년 11월 3일" in out
    assert "2년 이상인 자" in out
    assert "신청서 1부" in out


def test_괄호와_문장부호_앞뒤_공백을_없앤다():
    out = tidy_body(창원대)
    assert "(예시: 유튜브, 챗 GPT)" in out
    assert "바랍니다." in out
    assert "접수기간:" in out


def test_항목_기호_앞에서_줄을_바꾼다():
    lines = tidy_body(창원대).split("\n")
    assert "1. 모집부문" in lines
    assert "2. 강사 응모자격" in lines
    assert "나. 접수방법: e-mail" in lines
    assert any(line.startswith("○ AI 기반") for line in lines)
    assert any(line.startswith("① 강좌 개설") for line in lines)


def test_날짜_가운데에서는_줄을_바꾸지_않는다():
    """'2026. 11. 3.(화) ~ 11. 13.(금)' 의 11 은 번호 항목이 아니다."""
    out = tidy_body(창원대)
    assert "2026. 11. 3.(화) ~ 11. 13.(금)" in out


def test_가운뎃점은_끊지_않는다():
    """'교육 · 연구경력' 을 목록으로 보고 끊으면 말이 두 동강 난다."""
    assert "교육 · 연구경력" in tidy_body(창원대)


def test_빈_값():
    assert tidy_body("") == ""
    assert tidy_body(None) == ""
