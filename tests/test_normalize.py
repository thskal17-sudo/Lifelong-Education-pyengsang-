from gia.normalize import clean_url, extract_regions, mask_pii, norm_key, normalize_title, standardize_org


def test_title_flags():
    t, flags = normalize_title("[재공고] 2026년  하반기 시민강좌 강사 모집 (긴급)")
    assert t == "2026년 하반기 시민강좌 강사 모집"
    assert flags == ["긴급", "재공고"]


def test_title_keeps_meaningful_brackets():
    t, flags = normalize_title("(창원캠퍼스) 시간강사 모집")
    assert t == "(창원캠퍼스) 시간강사 모집"
    assert flags == []


def test_title_strips_board_badges():
    """.web CMS 의 '새 글'·'NEW' 꼬리와 '[공지]' 머리 배지는 제목이 아니다 (#18)."""
    t, flags = normalize_title("[공지] 2026년 제7회 기간제 근로자(청년 체험형 인턴) 채용 최종합격자 결정 공고 새 글")
    assert t == "2026년 제7회 기간제 근로자(청년 체험형 인턴) 채용 최종합격자 결정 공고"
    assert flags == []
    assert normalize_title("2026 하반기 강사 모집 새글")[0] == "2026 하반기 강사 모집"
    assert normalize_title("2026 하반기 강사 모집 NEW")[0] == "2026 하반기 강사 모집"
    assert normalize_title("2026 하반기 강사 모집 [NEW]")[0] == "2026 하반기 강사 모집"
    assert normalize_title("(공지) [재공고] 강사 모집 (N)")[0] == "강사 모집"
    assert normalize_title("공지 강사 모집")[0] == "강사 모집"
    # 제목의 일부인 낱말은 건드리지 않는다
    assert normalize_title("공지사항 게시판 운영 강사 모집")[0] == "공지사항 게시판 운영 강사 모집"
    assert normalize_title("새 글쓰기 강좌 강사 모집")[0] == "새 글쓰기 강좌 강사 모집"
    assert normalize_title("NEW 미디어 교육 강사 모집")[0] == "NEW 미디어 교육 강사 모집"
    assert norm_key("[공지] 강사 모집 새 글") == norm_key("강사 모집")


def test_norm_key_ignores_flags_and_symbols():
    assert norm_key("[재공고] 강사 모집!") == norm_key("강사  모집")


def test_org_alias():
    aliases = {"경남테크노파크": ["경남TP", "(재)경남테크노파크"]}
    assert standardize_org("경남TP", aliases) == "경남테크노파크"
    assert standardize_org("(재)경남테크노파크", aliases) == "경남테크노파크"
    assert standardize_org("재단법인 김해문화재단", aliases) == "김해문화재단"


def test_regions():
    assert extract_regions("경상남도 창원시 및 김해시 근무") == ["경남", "창원", "김해"]
    assert extract_regions("서울시 강남구") == []


def test_regions_need_suffix_or_gyeongnam_context():
    """시군 이름이 다른 단어에 섞여 있을 때 지역으로 잡지 않는다 (2026-09-22 실수집 오탐)."""
    assert extract_regions("고성능 빔프로젝터를 쓰는 김해시 도서관 강좌") == ["김해"]
    assert extract_regions("제품 대량 양산 라인") == []
    assert extract_regions("거창한 규모의 남해안 축제") == []
    assert extract_regions("최고성적 우수자 / 사천원 지급") == []
    assert extract_regions("근무지: 경남 고성") == ["경남", "고성"]
    assert extract_regions("고성군청 평생학습관") == ["고성"]


def test_mentions_target_region():
    from gia.normalize import mentions_gyeongnam, mentions_target_region
    assert mentions_target_region("양산시 소재")
    assert not mentions_target_region("대량 양산 공정")
    assert mentions_gyeongnam is mentions_target_region  # 이전 이름 호환


def test_extract_regions_busan_ulsan():
    """이 저장소는 부산·울산도 수집 대상이라 지역으로 인정한다."""
    assert extract_regions("부산광역시 해운대구") == ["부산"]
    assert extract_regions("울산대학교 평생교육원") == ["울산"]
    assert extract_regions("기장군 정관읍") == ["부산"]
    assert extract_regions("울주군 웅촌면") == ["울산"]
    assert extract_regions("부산·경남 공동 과정") == ["부산", "경남"]
    # 오탐 방지: '부산물'은 지역이 아니다
    assert extract_regions("음식물 부산물 처리 교육") == []
    assert extract_regions("서울특별시 강남구") == []


def test_mask_pii():
    out = mask_pii("문의 055-123-4567 / hong@example.com")
    assert "055" not in out and "@" not in out


def test_clean_url():
    assert clean_url("HTTPS://Example.org/a?b=1&utm_source=x#frag") == "https://example.org/a?b=1"
