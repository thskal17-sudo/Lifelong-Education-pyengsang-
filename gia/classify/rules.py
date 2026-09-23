"""규칙 기반 관련성 점수 (docs/DESIGN.md 7.1, 7.3)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..normalize import mentions_target_region, nfkc

CORE_WORDS = [
    "시간강사", "외래강사", "외래교수", "초빙강사", "초빙교수", "교강사", "훈련교사", "강사",
    "지도자", "지도사", "튜터", "코치", "멘토", "한국어교원", "예술강사", "스포츠강사",
]
HIRE_WORDS = ["모집", "채용", "공모", "위촉", "공개채용", "인력풀", "선발", "공개모집", "구인", "채용공고", "위촉공고", "초빙"]
LECTURE_WORDS = ["강의", "수업", "교육과정 운영", "프로그램 운영", "출강", "강좌", "교육 운영", "교육운영"]
EXCLUDE_TITLE = [
    "수강생", "교육생", "학생 모집", "참가자", "참여자", "합격자", "발표", "강사료", "지급",
    "만족도", "결과", "수료", "신청 안내", "교육 안내", "프로그램 안내", "입학", "수강 신청", "수강신청",
    "접수 안내", "참가 신청", "참가신청", "전임교원", "교원 임용", "교수 임용", "교원임용", "교수임용",
    # 강사가 되기 위해 듣는 과정(수강생 모집)은 강사 채용이 아니다 — 동의대 '파크골프 2급지도자(강사) 양성과정' 등
    "양성과정", "양성 과정", "지도자과정", "지도사과정", "자격과정", "직무연수", "보수교육",
    # 게시판 운영 공지
    "휴무", "휴강", "휴원", "정전", "점검 안내",
]
PROCUREMENT_WORDS = ["입찰", "물품", "시설", "임대", "공사"]
SERVICE_OK_WORDS = ["강의 용역", "교육 용역", "교육 운영 용역", "강사 운영", "교육과정 운영 용역", "교육 위탁"]
# 수집 대상은 부산·울산·경남이므로 이 셋은 타지역이 아니다
OTHER_REGIONS = ["서울", "대구", "경기", "인천", "광주", "대전", "세종", "강원", "충북", "충남", "전북", "전남", "경북", "제주"]
# 제목이 이 직종만 가리키면 본문에 "지도자" 같은 단어가 스쳐도 강사 공고가 아니다.
# 제목에 강사 핵심어가 하나도 없을 때만 적용한다 (핵심어가 있으면 복합 모집일 수 있음).
NON_INSTRUCTOR_JOBS = [
    "청원경찰", "경비원", "미화원", "환경미화", "조리원", "조리사", "영양사", "운전원", "운전기사",
    "사무보조", "행정보조", "사무원", "경리", "매표", "안내원", "청사관리", "시설관리원", "관리원",
    "당직", "수납원", "간호조무", "사회복무", "공무직", "생활지도원", "보안관",
]

FIELD_KEYWORDS: dict[str, list[str]] = {
    "school": ["방과후", "늘봄", "돌봄", "기간제", "학교스포츠", "학교예술", "초등학교", "중학교", "고등학교", "교육지원청"],
    "vocational": ["훈련교사", "폴리텍", "자격증", "산업기술", "국가기간", "직업훈련", "훈련과정", "기능사", "산업기사", "용접", "전기"],
    "arts": ["예술강사", "음악", "미술", "공예", "무용", "연극", "국악", "합창", "오케스트라", "문화예술", "서예", "사진"],
    "sports": ["생활체육", "수영", "헬스", "요가", "체육센터", "필라테스", "스포츠", "체육", "골프", "탁구", "배드민턴"],
    "it_digital": ["디지털배움터", "코딩", "SW", "소프트웨어", "AI", "인공지능", "스마트폰", "디지털", "정보화", "컴퓨터", "3D프린터", "드론"],
    "counsel_welfare": ["상담", "부모교육", "노인", "장애인", "청소년", "복지", "심리", "사회서비스", "돌봄", "치매"],
    "safety_health": ["안전교육", "심폐소생술", "보건", "성교육", "소방", "안전", "응급처치", "금연", "건강"],
    "language_kor": ["한국어", "다문화", "이주민", "이주여성", "결혼이민자"],
    "corporate": ["리더십", "직무", "서비스교육", "조직문화", "CS", "기업교육", "임직원"],
    "lifelong": ["평생학습", "평생교육", "문화센터", "주민자치", "취미", "어학", "시민강좌", "문해", "성인문해", "도서관", "여성회관"],
}
EMPLOYMENT_KEYWORDS: list[tuple[str, list[str]]] = [
    ("시간강사", ["시간강사", "시간제", "시간 강사"]),
    ("기간제", ["기간제", "계약직", "임기제", "한시"]),
    ("용역", ["용역", "입찰", "위탁"]),
    ("프리랜서", ["프리랜서", "위촉", "인력풀", "외래", "초빙", "외부강사"]),
]
_WORKPLACE_RE = re.compile(r"(?:근무지|근무 지역|근무장소|소재지|근무처)\s*[:：]?\s*(.{0,30})")


@dataclass
class RuleResult:
    score: int
    reasons: list[str] = field(default_factory=list)
    field: str = "other"
    employment_type: str = "기타"


def score_posting(title: str, body: str = "", region_text: str | None = None, org_name: str | None = None) -> RuleResult:
    t = nfkc(title)
    b = nfkc(body)[:4000]
    r = nfkc(region_text or "")
    score = 0
    reasons: list[str] = []

    core_t = [w for w in CORE_WORDS if w in t]
    if core_t:
        score += 50
        reasons.append(f"+50 제목 핵심어({core_t[0]})")
    else:
        core_b = [w for w in CORE_WORDS if w in b]
        if core_b:
            score += 25
            reasons.append(f"+25 본문 핵심어({core_b[0]})")
        else:
            score -= 30
            reasons.append("-30 핵심어 없음")

    hire = [w for w in HIRE_WORDS if w in t]
    if hire:
        score += 20
        reasons.append(f"+20 채용어({hire[0]})")

    lect = [w for w in LECTURE_WORDS if w in b or w in t]
    if lect:
        score += 10
        reasons.append(f"+10 강의어({lect[0]})")

    region_blob = " ".join([t, r, nfkc(org_name or ""), b[:2000]])
    if mentions_target_region(region_blob):
        score += 15
        reasons.append("+15 부·울·경 지역")

    if not core_t:
        jobs = [w for w in NON_INSTRUCTOR_JOBS if w in t]
        if jobs:
            score -= 40
            reasons.append(f"-40 비강사 직종({jobs[0]})")

    excl = [w for w in EXCLUDE_TITLE if w in t]
    if excl:
        score -= 60
        reasons.append(f"-60 제외어({excl[0]})")

    proc = [w for w in PROCUREMENT_WORDS if w in t]
    if proc and not any(w in t for w in SERVICE_OK_WORDS):
        score -= 30
        reasons.append(f"-30 조달어({proc[0]})")

    other = _other_region(t, r, b)
    if other:
        score -= 50
        reasons.append(f"-50 타지역({other})")

    score = max(0, min(100, score))
    return RuleResult(score=score, reasons=reasons, field=guess_field(t, b), employment_type=guess_employment(t, b))


def _other_region(title: str, region_text: str, body: str) -> str | None:
    _has_gn = mentions_target_region

    if region_text:
        hits = [o for o in OTHER_REGIONS if o in region_text]
        if hits and not _has_gn(region_text):
            return hits[0]
        return None
    for m in _WORKPLACE_RE.finditer(body):
        seg = m.group(1)
        hits = [o for o in OTHER_REGIONS if o in seg]
        if hits and not _has_gn(seg):
            return hits[0]
    return None


def guess_field(title: str, body: str = "") -> str:
    t = title
    b = body[:3000]
    best, best_n = "other", 0
    for code, words in FIELD_KEYWORDS.items():
        n = sum(3 for w in words if w in t) + sum(1 for w in words if w in b)
        if n > best_n:
            best, best_n = code, n
    return best


def guess_employment(title: str, body: str = "") -> str:
    blob = title + " " + body[:2000]
    for code, words in EMPLOYMENT_KEYWORDS:
        if any(w in blob for w in words):
            return code
    return "기타"
