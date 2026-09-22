"""정규화 규칙 (docs/DESIGN.md 6.1)."""
from __future__ import annotations

import re
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

FLAG_WORDS = ["재공고", "재모집", "재채용", "긴급", "수정", "연장", "정정", "추가", "변경"]
# 경남 18개 시군과 행정 접미사. 맨 이름만으로는 매칭하지 않는다
# ("고성"→고성능, "양산"→대량양산, "거창"→거창하다, "남해"→남해안 같은 오탐 방지)
SIGUN_SUFFIX = {
    "창원": "시", "진주": "시", "통영": "시", "사천": "시", "김해": "시", "밀양": "시", "거제": "시", "양산": "시",
    "의령": "군", "함안": "군", "창녕": "군", "고성": "군", "남해": "군", "하동": "군", "산청": "군",
    "함양": "군", "거창": "군", "합천": "군",
}
SIGUN = list(SIGUN_SUFFIX)
GYEONGNAM_WORDS = ["경남", "경상남도"]
# 부산·울산 광역시. '부산물'·'부산광역시' 같은 형태를 가려낸다. 자치구 이름(남구·북구 등)은
# 다른 시도와 겹쳐 쓰지 않고, 그 지역에서만 쓰는 이름(해운대·기장군·울주군)만 추가로 인정한다.
_METRO_PATTERNS = {
    "부산": re.compile(r"부산(?!물|만한|스럽)(?:광역시|시)?|해운대|기장군"),
    "울산": re.compile(r"울산(?:광역시|시)?|울주군"),
}
METRO = list(_METRO_PATTERNS)
# 지역으로 인정하는 형태
#  - 붙여 쓴 행정명: 고성군, 고성군청, 창원시설공단, 김해시립도서관
#  - 띄어 쓴 행정명: "고성 군" 뒤에 글자가 이어지면 제외 ("대량 양산 시행"의 "양산 시" 차단)
#  - 경남 문맥: "경남 고성", "경상남도 하동"
_SIGUN_PATTERNS = {
    name: re.compile(
        rf"{name}{suffix}|{name}\s+{suffix}(?![가-힣])|(?:경남|경상남도)\s*{name}(?![가-힣])"
    )
    for name, suffix in SIGUN_SUFFIX.items()
}
ORG_PREFIX_RE = re.compile(r"^\s*(?:\(재\)|\(사\)|\(주\)|재단법인|사단법인|주식회사)\s*")
_BRACKET_RE = re.compile(r"[\[\(【〔]([^\]\)】〕]{1,20})[\]\)】〕]")
# 게시판 배지: 목록 CMS 가 제목 앞뒤에 붙이는 '새 글'·'NEW'·'[공지]' (거창·진주시설공단·경남인재평생교육진흥원 등 .web CMS, #18)
_BADGE_LEAD_RE = re.compile(r"^(?:[\[\(【]\s*(?:공지|필독|NEW|New|new|N)\s*[\]\)】]|공지(?=\s))\s*[:\-·]?\s*")
_BADGE_TAIL_RE = re.compile(r"\s*(?:[\[\(【]\s*(?:새\s?글|NEW|New|new|N)\s*[\]\)】]|새\s?글|NEW|New|new)\s*$")
_WS_RE = re.compile(r"\s+")
_KEY_RE = re.compile(r"[^0-9a-z가-힣]")
_PHONE_RE = re.compile(r"(?<!\d)0\d{1,2}[-.\s)]?\d{3,4}[-.\s]?\d{4}(?!\d)")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def nfkc(s: str) -> str:
    return unicodedata.normalize("NFKC", s or "")


def strip_badges(t: str) -> str:
    """목록 CMS 가 붙이는 '새 글'·'NEW'·'[공지]' 배지를 제목 앞뒤에서 떼어낸다 (#18)."""
    for _ in range(3):  # '[공지] … 새 글 NEW' 처럼 겹쳐 붙는 경우
        t2 = _BADGE_TAIL_RE.sub("", _BADGE_LEAD_RE.sub("", t)).strip()
        if t2 == t or not t2:
            break
        t = t2
    return t


def normalize_title(title: str) -> tuple[str, list[str]]:
    """제목 정리 + 재공고/긴급 등 플래그 분리."""
    t = strip_badges(_WS_RE.sub(" ", nfkc(title)).strip())
    flags: set[str] = set()

    def _sub(m: re.Match) -> str:
        inner = m.group(1).strip()
        hit = [w for w in FLAG_WORDS if w in inner]
        if hit and len(inner) <= 8:
            flags.update(hit)
            return " "
        return m.group(0)

    t = _BRACKET_RE.sub(_sub, t)
    for w in FLAG_WORDS:
        if t.startswith(w + " ") or t.endswith(" " + w):
            flags.add(w)
            t = t.removeprefix(w + " ").removesuffix(" " + w)
    t = _WS_RE.sub(" ", t).strip(" -·:")
    return t, sorted(flags)


def norm_key(s: str) -> str:
    t = strip_badges(_WS_RE.sub(" ", nfkc(s)).strip()).lower()
    for w in FLAG_WORDS:
        t = t.replace(w, "")
    return _KEY_RE.sub("", t)


def standardize_org(name: str, aliases: dict[str, list[str]]) -> str:
    raw = ORG_PREFIX_RE.sub("", _WS_RE.sub(" ", nfkc(name)).strip())
    key = norm_key(raw)
    for canonical, alist in aliases.items():
        if key == norm_key(canonical):
            return canonical
        for a in alist:
            if key == norm_key(a):
                return canonical
    return raw


def extract_regions(text: str) -> list[str]:
    """텍스트에서 부산·울산·경남 지역명을 뽑는다. 경남 시군은 행정 접미사나 경남 문맥이 있을 때만 인정."""
    t = nfkc(text)
    out: list[str] = []
    for name, pattern in _METRO_PATTERNS.items():
        if pattern.search(t):
            out.append(name)
    if any(w in t for w in GYEONGNAM_WORDS):
        out.append("경남")
    for name, pattern in _SIGUN_PATTERNS.items():
        if pattern.search(t):
            out.append(name)
    return out


def mentions_target_region(text: str) -> bool:
    """부산·울산·경남(시군 포함)이 언급되는지."""
    return bool(extract_regions(text))


mentions_gyeongnam = mentions_target_region  # 이전 이름 호환


def mask_pii(text: str) -> str:
    t = _EMAIL_RE.sub("[이메일]", text or "")
    return _PHONE_RE.sub("[전화번호]", t)


def clean_url(url: str) -> str:
    parts = urlsplit((url or "").strip())
    q = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not k.lower().startswith("utm_")]
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, urlencode(q), ""))
