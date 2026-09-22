# 경남 강사 구인공고 수집·일일 요약 시스템 설계서

- 문서 버전: 0.1 (2026-09-21)
- 상태: Phase 4 구현 반영 (2026-09-21: playwright·search_portal 어댑터, GitHub Pages 아카이브, 주간 통계). Phase 3의 LLM 판별·추출, 피드백 루프, eval 명령 포함. Phase 2의 첨부 추출·onclick 게시판·이메일 채널 포함. 게시판 URL·셀렉터 실측은 `docs/SOURCE_VERIFICATION.md` 절차로 진행. 구현과 다른 부분은 코드가 기준이며 이 문서를 갱신한다.
- 관련 파일: `config/sources.yaml` (수집원 레지스트리), `docs/DAILY_REPORT_TEMPLATE.md` (요약본 형식)

---

## 목차

1. 목표와 범위
2. 요구사항
3. 전체 아키텍처
4. 수집 대상 (기관 분류와 우선순위)
5. 수집 계층 (Collector)
6. 정규화·중복 제거 계층 (Normalizer / Deduper)
7. 판별·분류 계층 (Classifier)
8. 저장 계층 (Store)
9. 요약 계층 (Summarizer)
10. 발송 계층 (Notifier)
11. 스케줄링과 실행 흐름
12. 데이터 모델
13. 설정 파일 스키마
14. 운영·모니터링·장애 대응
15. 준법·윤리 (크롤링 정책)
16. 테스트 전략
17. 기술 스택과 디렉터리 구조
18. 구현 로드맵
19. 리스크와 완화책
20. 미결 사항 (사용자 결정 필요)

---

## 1. 목표와 범위

### 1.1 목표

경상남도 소재 또는 경남 근무지를 대상으로 하는 **강사 구인공고**를 공공·민간·정부산하기관에서 자동 수집하고,
매일 정해진 시간에 **신규·마감임박 공고 중심의 요약본**을 지정 채널로 받아본다.

### 1.2 범위

| 구분 | 포함 | 제외 |
|---|---|---|
| 지역 | 경상남도 18개 시군, 근무지가 경남인 공고, 경남 소재 기관의 원격·출강 공고 | 부산·울산 (옵션으로 인접권 포함 가능) |
| 기관 | 경남도청·시군청, 경남교육청·교육지원청, 경남 출자·출연기관, 중앙정부 산하 공공기관의 경남 소재 지사·캠퍼스, 대학 평생교육원, 민간 학원·문화센터·기업 | 개인 과외, 학생·수강생 모집 |
| 공고 유형 | 시간강사, 외래강사, 평생교육 강사, 직업훈련 교강사, 방과후·늘봄 강사, 문화예술·체육 강사, 기업교육 강사, 강의 용역 입찰 | 정규직 교원 임용(옵션), 강사 합격자 발표, 강사료 지급 안내 |

### 1.3 산출물

- 매일 1회 일일 요약본 (텔레그램 + 이메일, 1차 채널은 사용자 선택)
- 저장소 내 누적 아카이브 (`data/`, `reports/`)
- 소스별 수집 상태 대시보드 (리포트 하단 부록)

---

## 2. 요구사항

### 2.1 기능 요구사항

| ID | 요구사항 | 우선순위 |
|---|---|---|
| F-01 | 등록된 모든 수집원에서 공고 목록을 가져온다 | 필수 |
| F-02 | 공고 상세 페이지·첨부파일(HWP/HWPX/PDF)에서 마감일·자격·접수방법을 추출한다 | 필수 |
| F-03 | 강사 구인 여부를 키워드 규칙 + LLM 보조로 판별한다 | 필수 |
| F-04 | 여러 포털에 중복 게시된 동일 공고를 하나로 병합한다 | 필수 |
| F-05 | 신규 / 변경(마감 연장 등) / 마감임박(D-3 이내) / 마감 상태를 관리한다 | 필수 |
| F-06 | 매일 지정 시각(기본 07:30 KST)에 요약본을 발송한다 | 필수 |
| F-07 | 수집 실패 소스가 있어도 나머지 결과로 요약본을 발송하고 실패 목록을 명시한다 | 필수 |
| F-08 | 요약본에 원문 링크, 기관, 분야, 마감일, 한 줄 요약을 포함한다 | 필수 |
| F-09 | 관심 분야·키워드 가중치로 정렬 우선순위를 조정할 수 있다 | 권장 |
| F-10 | 마감 3일 전 재알림, 마감 당일 알림 | 권장 |
| F-11 | 주간 통계 (기관별·분야별 건수) | 선택 |
| F-12 | 웹 아카이브 페이지(GitHub Pages)에서 검색 | 선택 |

### 2.2 비기능 요구사항

| ID | 요구사항 |
|---|---|
| N-01 | 전체 실행 시간 30분 이내 (GitHub Actions 무료 한도 고려) |
| N-02 | 요청 간격 소스당 1~2초, 동일 도메인 동시 요청 1개 (서버 부담 최소화) |
| N-03 | 소스 하나의 장애가 전체 실행을 중단시키지 않음 (격리 + 타임아웃) |
| N-04 | 새 소스 추가는 코드 수정 없이 `sources.yaml` 항목 추가로 가능 (표준 어댑터 범위 내) |
| N-05 | 모든 시각은 KST(Asia/Seoul)로 저장·표시 |
| N-06 | 비밀값(API 키, 봇 토큰)은 저장소에 커밋하지 않고 GitHub Secrets로 주입 |
| N-07 | 월 운영비 목표: 무료 ~ 1만 원 이내 (LLM 호출 최소화) |

---

## 3. 전체 아키텍처

```
┌──────────────────────────────────────────────────────────────────────────┐
│  GitHub Actions (cron, KST 06:30 수집 → 07:30 발송)                       │
│                                                                          │
│  ┌──────────┐   ┌────────────┐   ┌────────────┐   ┌──────────┐            │
│  │ Collector│──▶│ Normalizer │──▶│ Classifier │──▶│  Store   │            │
│  │ (소스별  │   │ + Deduper  │   │ (규칙+LLM) │   │ (JSONL)  │            │
│  │  어댑터) │   └────────────┘   └────────────┘   └────┬─────┘            │
│  └──────────┘                                         │                  │
│       ▲                                               ▼                  │
│  sources.yaml                                  ┌────────────┐            │
│                                                │ Summarizer │            │
│                                                │ (템플릿+LLM)│            │
│                                                └─────┬──────┘            │
│                                                      ▼                   │
│                                                ┌────────────┐            │
│                                                │  Notifier  │──▶ 텔레그램│
│                                                │            │──▶ 이메일  │
│                                                └────────────┘──▶ reports/│
└──────────────────────────────────────────────────────────────────────────┘
```

### 3.1 설계 원칙

1. **파이프라인 단계 분리**: 각 단계는 입력·출력 스키마가 고정된 순수 함수에 가깝게 만들어, 단계별로 독립 테스트한다.
2. **API 우선, HTML 스크래핑은 차선, 브라우저 렌더링은 최후**: 공공데이터포털 API가 있는 소스는 API를 쓴다. 비용·안정성 순서다.
3. **소스 장애 격리**: 소스별 타임아웃과 예외 처리를 두고, 실패는 리포트 부록에 기록만 한다.
4. **규칙 우선, LLM 보조**: 강사 여부 1차 판별과 마감일 추출은 규칙으로 하고, 규칙이 애매한 경우(신뢰도 중간)에만 LLM을 호출한다.
5. **저장은 텍스트(JSONL)**: git 친화적이며 diff로 변경 추적이 가능하다. DB 서버 불필요.
6. **설정으로 확장**: 새 소스는 YAML 항목 추가로 끝나야 한다.

---

## 4. 수집 대상 (기관 분류와 우선순위)

기관 목록의 단일 진실 원천은 `config/sources.yaml`이다. 이 절은 분류 체계와 선정 기준만 다룬다.

### 4.1 기관 유형 분류 (`org_type`)

| 코드 | 명칭 | 예시 |
|---|---|---|
| `local_gov` | 지방자치단체 | 경남도청, 18개 시군청, 읍면동 |
| `edu_office` | 교육청 | 경남교육청, 18개 교육지원청, 직속기관(도서관·연수원·과학교육원) |
| `local_public` | 지방 출자·출연·공기업 | 경남개발공사, 경남테크노파크, 경남문화예술진흥원, 경남여성가족재단, 경남인재평생교육진흥원, 시군 시설관리공단·문화재단 |
| `central_public` | 중앙정부 산하 공공기관 (경남 소재) | 한국산업인력공단 경남지사, 한국폴리텍대학 창원·진주캠퍼스, LH, 중소벤처기업진흥공단, 한국남동발전, 한국세라믹기술원, 한국승강기안전공단, 한국전기연구원, 한국재료연구원 |
| `university` | 대학·평생교육원 | 경상국립대, 창원대, 경남대, 인제대, 각 대학 평생교육원 |
| `private` | 민간 | 학원, 문화센터(백화점·마트), 직업훈련기관, 기업교육 업체, 채용 포털 |
| `portal` | 통합 채용 포털 | 나라일터, 잡알리오, 클린아이 잡플러스, 고용24(워크넷), 나라장터, 사람인, 잡코리아 |

### 4.2 수집원 계층 (Tier)

| Tier | 성격 | 커버리지 | 구현 난이도 | 도입 단계 |
|---|---|---|---|---|
| 1 | 통합 포털 (API 제공) | 매우 높음 (공공 대부분) | 낮음 | Phase 1 |
| 2 | 경남도·시군·교육청 채용 게시판 | 높음 (지자체 직접 채용) | 중간 (HTML, 게시판 구조 유사) | Phase 2 |
| 3 | 경남 출자·출연기관, 중앙 산하 경남 소재 기관 | 중간 (기관별 소량) | 중간~높음 (사이트마다 다름) | Phase 2~3 |
| 4 | 민간 포털·문화센터·학원 | 중간 (양 많고 노이즈 큼) | 높음 (봇 차단, 약관 확인 필요) | Phase 3 |

### 4.3 Tier 1 상세 (핵심)

| 포털 | 대상 | 접근 방식 | 비고 |
|---|---|---|---|
| 나라일터 (인사혁신처) | 국가·지자체 임기제·기간제·강사 | 공공데이터포털 API 우선, 없으면 검색 결과 HTML | 지역 필터 "경남" + 키워드 |
| 잡알리오 (기획재정부) | 공공기관 채용 | 공공데이터포털 "공공기관 채용정보" API | 근무지 필터 |
| 클린아이 잡플러스 (행안부) | 지방공기업·출자출연기관 채용 | HTML 검색 | 경남 출자출연기관 대부분 커버 |
| 고용24 / 워크넷 (고용노동부) | 민간·공공 구인 | 공공데이터포털 "워크넷 채용정보" API | 직종코드 "강사" + 지역코드 경남 |
| 나라장터 | 강의·교육 용역 입찰 | 공공데이터포털 "입찰공고정보" API | "교육", "강의", "강사 운영" 키워드 |
| HRD-Net / 고용24 훈련기관 | 직업훈련 교강사 | 워크넷 API로 대부분 유입 | 별도 소스는 Phase 3에서 검토 |

> 공공데이터포털(data.go.kr) API 사용에는 무료 인증키 신청이 필요하다. 일일 트래픽 한도(보통 1,000~10,000건)는 하루 1~3회 실행으로 충분하다.

### 4.4 소스 선정 기준

새 소스는 다음 조건을 만족할 때 등록한다.

1. 최근 12개월 내 강사 관련 공고를 1건 이상 게시한 이력이 있다.
2. robots.txt와 이용약관이 자동 수집을 금지하지 않는다.
3. 공고 목록을 로그인 없이 볼 수 있다.
4. Tier 1 포털에서 이미 동일 공고가 수집되지 않는다 (중복 소스는 우선순위 낮음).

---

## 5. 수집 계층 (Collector)

### 5.1 어댑터 인터페이스

```python
class SourceAdapter(Protocol):
    source_id: str

    def fetch_list(self) -> list[RawListing]:
        """목록 페이지/API에서 공고 후보를 가져온다. 상세는 가져오지 않는다."""

    def fetch_detail(self, listing: RawListing) -> RawPosting:
        """상세 본문, 첨부파일 링크, 게시일 등을 채운다."""
```

`RawListing`은 최소 `title`, `url`, `posted_at(옵션)`, `source_id`를 가진다.
`RawPosting`은 여기에 `body_text`, `attachments[]`, `raw_html(옵션)`을 더한다.

### 5.2 어댑터 유형

| type | 용도 | 구현 라이브러리 | 설정 항목 |
|---|---|---|---|
| `api_json` | 공공데이터포털 등 JSON/XML API | httpx | `endpoint`, `params`, `field_map`, `paging` |
| `rss` | RSS/Atom 제공 게시판 | feedparser | `feed_url` |
| `html_list` | 정적 HTML 게시판 | httpx + selectolax | `list_url`, `row_selector`, `title_selector`, `link_selector`, `date_selector`, `paging` |
| `playwright` | JS 렌더링 필수 사이트 | Playwright(Chromium) | `list_url`, `wait_for`, `row_selector` 등 |
| `search_portal` | 검색어 기반 포털 (사람인 등) | httpx 또는 playwright | `query_url_template`, `queries[]` |

### 5.3 공통 동작

- **User-Agent**: `GyeongnamInstructorBot/0.1 (+저장소 URL; 연락처 이메일)` 명시.
- **요청 간격**: 도메인당 최소 1.5초, 지터 ±0.5초. 도메인당 동시성 1.
- **재시도**: 5xx·타임아웃은 지수 백오프(2s, 4s, 8s) 최대 3회. 4xx는 즉시 실패 기록.
- **조건부 요청**: `ETag`/`Last-Modified` 저장 후 재사용 (지원 소스 한정).
- **상세 페이지 절약**: 목록 단계에서 이미 본 URL(`seen` 인덱스에 존재)이면 상세를 다시 가져오지 않는다. 단, 마감 연장 감지를 위해 활성 공고는 3일마다 1회 재확인한다.
- **첨부파일**: HWP(`pyhwp`/`hwp5txt`), HWPX(zip 내 XML), PDF(`pypdf`), DOCX(`python-docx`)에서 텍스트를 추출한다. 크기 상한 10MB, 파일당 타임아웃 20초. 마감일이 본문에 없고 첨부에만 있는 경우가 많으므로 필수 기능이다.
- **타임아웃**: 소스당 총 실행 상한 3분. 초과 시 해당 소스는 부분 결과로 종료.
- **인코딩**: EUC-KR 사이트 대응 (응답 헤더·meta charset 순으로 판정).

### 5.4 목록 페이지 조회 범위

- 기본: 최신 2페이지 또는 최근 14일 게시글 중 먼저 도달하는 조건.
- 최초 실행(백필): 최근 60일.
- 페이지 수는 소스별 `paging.max_pages`로 조정.

---

## 6. 정규화·중복 제거 계층

### 6.1 정규화 규칙

| 필드 | 규칙 |
|---|---|
| `title` | 전각→반각, 연속 공백 축약, `[ ]`·`( )` 안의 "재공고", "긴급", "수정" 등은 `flags`로 이동 |
| `org_name` | 기관명 별칭 사전(`config/org_aliases.yaml`)으로 표준화. 예: "경남TP" → "경남테크노파크" |
| `deadline` | 아래 6.2 파서로 `date`/`datetime` 추출, 실패 시 `null` + `deadline_text` 보존 |
| `posted_at` | 게시일. 없으면 최초 수집일로 대체하고 `posted_at_inferred=true` |
| `region` | 본문·근무지에서 시군명 추출. 다중 가능 |
| `url` | 추적 파라미터 제거, 스킴·호스트 소문자화 |

### 6.2 마감일 파서

한국 공공기관 공고에서 자주 나오는 패턴을 우선순위 순으로 시도한다.

1. `2026. 9. 30.(수) 18:00까지` / `2026.09.30.(수)`
2. `2026년 9월 30일 18시까지`
3. `~ 9. 30.(수)` (연도 생략 → 게시일 기준 연도 보정, 게시일보다 이르면 다음 해)
4. `접수기간: 2026.9.22.(월) ~ 2026.9.30.(수)`
5. `채용 시까지`, `충원 시까지`, `상시` → `deadline=null`, `deadline_type=until_filled`
6. 첨부파일 텍스트에서 위 패턴 재시도.

"접수", "제출", "마감", "공고기간"이 앞뒤 30자 안에 있는 날짜를 우선하고, "면접일", "발표일" 근처 날짜는 배제한다.

### 6.3 중복 제거

- **1차 (정확 일치)**: `canonical_key = sha1(norm(org_name) + "|" + norm(title))`. `norm`은 공백·기호 제거, 재공고 플래그 제거.
- **2차 (유사 일치)**: 같은 `org_name` 내에서 제목 유사도(RapidFuzz `token_set_ratio`) ≥ 90이고 게시일 차이 ≤ 7일이면 동일 공고로 병합.
- **병합 규칙**: 최초 수집 레코드가 기본이 되고, `sources[]`에 출처를 누적한다. 마감일이 서로 다르면 더 늦은 값을 채택하고 `status=updated`로 표시한다.
- **재공고 처리**: "재공고" 플래그가 있고 기존 공고가 마감 상태이면 새 공고로 등록하되 `reannouncement_of`로 연결한다.

---

## 7. 판별·분류 계층 (Classifier)

### 7.1 1단계: 규칙 기반 판별 (관련성 점수)

각 공고에 0~100 점수를 매기고, 임계값으로 3구간으로 나눈다.

| 구간 | 점수 | 처리 |
|---|---|---|
| 확정 포함 | ≥ 70 | LLM 호출 없이 포함 |
| 판단 유보 | 30~69 | LLM 판별 호출 |
| 제외 | < 30 | 폐기 (샘플만 로그) |

점수 산정 요소:

| 요소 | 가중치 | 예시 |
|---|---|---|
| 제목에 강사 핵심어 | +50 | 강사, 교강사, 시간강사, 외래강사, 외래교수, 초빙강사, 훈련교사, 지도자(생활체육·문화예술), 튜터, 코치, 멘토 |
| 제목에 채용 동사 | +20 | 모집, 채용, 공모, 위촉, 공개채용, 인력풀 |
| 본문에 강사 핵심어 (제목에 없을 때) | +25 | 위와 동일 |
| 본문에 강의 관련어 | +10 | 강의, 수업, 교육과정 운영, 프로그램 운영, 출강 |
| 지역 일치 | +15 | 경남, 경상남도, 18개 시군명 |
| 제외어 (제목) | −60 | 수강생, 교육생, 학생 모집, 참가자 모집, 합격자, 발표, 강사료, 지급, 만족도, 결과 |
| 제외어 (본문 위주 공고) | −30 | 입찰(단, "강의 용역"·"교육 운영 용역"이면 −0), 물품, 시설, 임대 |
| 타지역 명시 (근무지가 부산·울산·서울 등) | −50 | 근무지 필드 또는 "근무지:" 뒤 30자 |

### 7.2 2단계: LLM 판별·추출 (판단 유보 구간 + 확정 포함 구간의 구조화)

- 모델: 기본 `claude-opus-5`, `output_config.effort="low"`. 사용자가 원하면 `claude-sonnet-5`/`claude-haiku-4-5`로 교체 가능하도록 설정값으로 둔다.
- 방식: 구조화 출력(`client.messages.parse` + Pydantic). 프롬프트에 본문 최대 6,000자 + 첨부 텍스트 최대 4,000자.
- 호출 상한: 실행당 최대 60건 (초과분은 규칙 결과만으로 처리하고 리포트에 명시).
- 프롬프트 캐싱: 시스템 프롬프트(판별 기준·분야 분류표)를 고정 접두로 두어 캐시 적중.
- 안전장치: `stop_reason == "refusal"` 또는 파싱 실패 시 규칙 기반 결과로 대체.

추출 스키마 (Pydantic):

```python
class Extraction(BaseModel):
    is_instructor_job: bool            # 강사 구인공고인가
    confidence: float                  # 0~1
    field: str                         # 분야 코드 (7.3)
    employment_type: str               # 시간강사 | 기간제 | 프리랜서 | 용역 | 기타
    deadline: str | None               # ISO 8601, 없으면 null
    deadline_type: str                 # fixed | until_filled | unknown
    work_location: str | None          # 시군 단위
    qualifications: list[str]          # 핵심 자격 3개 이내
    pay: str | None                    # 시급/강사료, 원문 표현 그대로
    apply_method: str | None           # 이메일 | 방문 | 우편 | 온라인 | 혼합
    one_line_summary: str              # 40자 이내 한국어
    exclusion_reason: str | None       # 제외 판정 시 이유
```

호출 예시 (Python SDK):

```python
import anthropic

client = anthropic.Anthropic()  # ANTHROPIC_API_KEY는 GitHub Secrets로 주입

response = client.messages.parse(
    model=settings.llm_model,      # 기본 "claude-opus-5"
    max_tokens=2048,
    system=[{
        "type": "text",
        "text": CLASSIFIER_SYSTEM_PROMPT,   # 판별 기준 + 분야 분류표 (고정)
        "cache_control": {"type": "ephemeral"},
    }],
    messages=[{"role": "user", "content": build_user_prompt(posting)}],
    output_format=Extraction,
    output_config={"effort": "low"},
)
if response.stop_reason == "refusal":
    return rule_based_fallback(posting)
extraction = response.parsed_output
```

### 7.3 분야 분류표 (`field`)

| 코드 | 명칭 | 예시 키워드 |
|---|---|---|
| `lifelong` | 평생교육·문화강좌 | 평생학습관, 문화센터, 주민자치, 취미, 어학 |
| `vocational` | 직업훈련·기술 | 훈련교사, 폴리텍, 자격증, 산업기술, 국가기간전략 |
| `school` | 학교·방과후·늘봄 | 방과후, 늘봄, 돌봄, 기간제, 학교스포츠, 학교예술 |
| `arts` | 문화예술 | 예술강사, 음악, 미술, 공예, 무용, 연극 |
| `sports` | 체육·생활체육 | 생활체육지도자, 수영, 헬스, 요가, 체육센터 |
| `it_digital` | IT·디지털 | 디지털배움터, 코딩, SW, AI, 스마트폰 교육 |
| `counsel_welfare` | 상담·복지·사회서비스 | 상담사, 부모교육, 노인, 장애인, 청소년 |
| `safety_health` | 안전·보건 | 안전교육, 심폐소생술, 보건, 성교육, 소방 |
| `corporate` | 기업·직무교육 | 리더십, 직무, 서비스, 조직문화 |
| `language_kor` | 한국어·다문화 | 한국어교원, 다문화, 이주민 |
| `other` | 기타 | — |

### 7.4 관심도 가중치 (사용자 설정)

`config/settings.yaml`의 `interests`에 분야별 가중치(0~2)와 키워드 리스트를 둔다. 정렬 순서에만 영향을 주고 포함 여부에는 영향을 주지 않는다.

---

## 8. 저장 계층 (Store)

### 8.1 저장 방식

git 저장소 안의 텍스트 파일로 저장한다. 별도 DB 서버 없음.

```
data/
  postings/
    2026-09.jsonl        # 월별 공고 원장 (append-only, 1행 = 1공고 최신 상태)
  index/
    seen_urls.json       # url → canonical_key (상세 재수집 방지)
    canonical.json       # canonical_key → {first_seen, last_seen, status}
  http_cache/
    etag.json            # 소스별 ETag / Last-Modified
  runs/
    2026-09-21T06-30.json   # 실행 로그 (소스별 건수·소요시간·오류)
```

- 월별 JSONL은 실행마다 **재작성**(같은 공고는 최신 상태로 교체)하고, 변경 이력은 git 커밋 diff로 남긴다.
- 커밋은 GitHub Actions 봇 계정이 `data:` 접두 메시지로 수행한다. 하루 1~3 커밋.
- 1년 뒤 데이터가 커지면(예상 월 300~800건, 연 5MB 이내) 분기별 파일로 분할하거나 SQLite/DuckDB로 이관한다. JSONL 스키마는 그대로 이관 가능하다.

### 8.2 상태 전이

```
        수집         마감일-3일        마감일 경과
 (없음) ────▶ new ────────▶ closing_soon ────────▶ expired
               │  ▲                                 ▲
     마감일 변경│  │ 다음 실행                        │
               ▼  │                                 │
            updated ────────────────────────────────┘
```

- `new`: 이번 실행에서 처음 본 공고 (직전 리포트 이후 신규).
- `updated`: 마감일·제목·본문 해시가 바뀐 공고.
- `closing_soon`: 마감 3일 이내이고 아직 유효.
- `expired`: 마감일 경과 또는 원문 페이지 404·삭제.
- `active`: 위 어느 것도 아닌 유효 공고 (리포트 본문에서는 생략, 주간 통계에만).

---

## 9. 요약 계층 (Summarizer)

### 9.1 두 층의 요약

1. **공고 단위 한 줄 요약**: Classifier의 `one_line_summary` 재사용 (추가 호출 없음).
2. **일일 총평 (선택)**: 신규 공고가 5건 이상일 때만 LLM 1회 호출로 3문장 이내 총평 생성. "오늘은 평생교육·체육 분야가 많고, 창원·김해 집중" 같은 형태. 비용 절감을 위해 기본 비활성, 설정으로 활성.

### 9.2 리포트 구성 (`docs/DAILY_REPORT_TEMPLATE.md` 참조)

1. 헤더: 날짜, 신규/마감임박/변경 건수
2. 마감 임박 (D-3 이내, 마감 가까운 순)
3. 신규 공고 (관심 가중치 → 마감 임박 순 → 기관 유형 순)
4. 변경 공고 (마감 연장 등)
5. 부록: 소스별 수집 상태 (성공/실패/0건), LLM 호출 수, 실행 시간

### 9.3 렌더링

- Jinja2 템플릿 하나에서 세 가지 출력을 만든다: Markdown(저장소 `reports/`), 텔레그램용 HTML(4,096자 분할), 이메일용 HTML.
- 텔레그램은 메시지 길이 한도가 있으므로 "마감 임박 + 신규 상위 15건"만 보내고, 전체는 이메일·Markdown 링크로 연결한다.
- 공고 한 건의 표시 형식:

```
[평생교육] 경남인재평생교육진흥원 · 2026 하반기 시민강좌 강사 모집
  마감 09.30(수) 18:00 · 창원 · 시간강사 · 강사료 시간당 5만원
  → https://... (출처: 기관 홈페이지, 잡알리오)
```

---

## 10. 발송 계층 (Notifier)

| 채널 | 방식 | 장점 | 단점 | 권장 |
|---|---|---|---|---|
| 텔레그램 봇 | Bot API `sendMessage` | 무료, 설정 5분, 모바일 푸시 | 4,096자 제한 | 1차 채널 |
| 이메일 | SMTP (Gmail 앱 비밀번호) 또는 Resend API | 전체 내용 수용, 검색 가능 | 스팸 분류 가능성 | 2차 채널 (전문) |
| GitHub Issue | 저장소 Issue 자동 생성 | 무료, 저장소 안에 기록, 이메일 알림 자동 | 알림 노이즈 | 아카이브 대안 |
| 슬랙/디스코드 | Incoming Webhook | 팀 공유 | 개인 용도엔 과함 | 옵션 |
| 카카오톡 "나에게 보내기" | REST API | 국내 친숙 | 토큰 갱신 번거로움, 심사 | 비권장 |

- 발송은 채널별 독립 실패 처리. 텔레그램 실패해도 이메일은 발송.
- 모든 채널 실패 시 GitHub Actions 잡을 실패로 표시해 GitHub 알림 메일이 가게 한다 (최후 안전망).
- 발송 후 `reports/2026-09-21.md`를 커밋한다. GitHub Pages를 켜면 그대로 웹 아카이브가 된다.

---

## 11. 스케줄링과 실행 흐름

### 11.1 시간표 (KST 기준)

| 시각 (KST) | cron (UTC) | 작업 | 비고 |
|---|---|---|---|
| 06:30 | `30 21 * * *` | 전체 수집 + 판별 + 저장 | 소요 10~25분 예상 |
| 07:30 | `30 22 * * *` | 요약 생성 + 발송 | 수집 잡과 분리해 발송 시각 안정화 |
| 12:30 (옵션) | `30 3 * * *` | 경량 수집 (Tier 1만) | 당일 오전 게시 공고를 다음날 아침에 놓치지 않기 위함 |

- GitHub Actions cron은 수 분~수십 분 지연될 수 있다. 발송 시각의 정밀도가 중요하면 수집·발송을 하나의 잡으로 합치고 발송 시각을 `07:00`으로 당긴 뒤, 실제 발송 직전에 `sleep`으로 07:30에 맞추는 방식을 쓴다.
- 요일 조건: 기본 매일. 주말에 공고가 적으므로 `settings.yaml`에서 평일만 발송으로 바꿀 수 있다 (수집은 매일 유지).

### 11.2 실행 흐름 (수집 잡)

```
1. 설정·레지스트리 로드, enabled=true 소스만 선택
2. 소스별 병렬 실행 (도메인별 동시성 1, 전체 동시성 6)
   a. fetch_list → seen 필터 → fetch_detail (신규·재확인 대상만)
   b. 첨부 텍스트 추출
   c. 실패는 run 로그에 기록하고 계속
3. 정규화 → 중복 병합 → 규칙 점수
4. 판단 유보 + 확정 포함 건에 대해 LLM 추출 (상한 60건)
5. 상태 전이 계산 (new/updated/closing_soon/expired)
6. data/ 갱신, run 로그 저장, git 커밋·푸시
```

### 11.3 실행 흐름 (발송 잡)

```
1. data/ 최신 상태 로드
2. 직전 리포트 시각 이후의 new/updated + 현재 closing_soon 선별
3. 정렬·렌더링 (Markdown, 텔레그램 HTML, 이메일 HTML)
4. 채널별 발송 (독립 실패)
5. reports/YYYY-MM-DD.md 커밋, last_report_at 갱신
```

### 11.4 GitHub Actions 워크플로 골격

```yaml
name: collect
on:
  schedule:
    - cron: "30 21 * * *"   # 06:30 KST
  workflow_dispatch:
    inputs:
      backfill_days: { default: "0" }
concurrency: { group: pipeline, cancel-in-progress: false }
jobs:
  collect:
    runs-on: ubuntu-latest
    timeout-minutes: 40
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12", cache: pip }
      - run: pip install -e .
      - run: python -m gia collect
        env:
          DATA_GO_KR_KEY: ${{ secrets.DATA_GO_KR_KEY }}
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
      - run: |
          git config user.name "gia-bot"
          git config user.email "gia-bot@users.noreply.github.com"
          git add data && git commit -m "data: collect $(date -u +%F)" || true
          git push
```

발송 잡은 같은 구조로 `python -m gia report --send`를 실행하고 `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `SMTP_*`를 주입한다. Playwright가 필요한 소스가 있으면 `playwright install --with-deps chromium` 단계를 추가한다 (약 1분 소요).

---

## 12. 데이터 모델

### 12.1 `Posting` (JSONL 1행)

| 필드 | 타입 | 설명 |
|---|---|---|
| `id` | str | `canonical_key` 앞 12자 |
| `canonical_key` | str | 6.3 참조 |
| `title` | str | 정규화된 제목 |
| `org_name` | str | 표준화 기관명 |
| `org_type` | enum | 4.1 코드 |
| `field` | enum | 7.3 코드 |
| `employment_type` | str | 시간강사/기간제/프리랜서/용역/기타 |
| `region` | list[str] | 시군명 |
| `posted_at` | date | 게시일 |
| `deadline` | datetime\|null | KST |
| `deadline_type` | enum | fixed / until_filled / unknown |
| `deadline_text` | str\|null | 원문 표현 |
| `qualifications` | list[str] | |
| `pay` | str\|null | |
| `apply_method` | str\|null | |
| `one_line_summary` | str | |
| `relevance_score` | int | 규칙 점수 |
| `llm_confidence` | float\|null | |
| `status` | enum | new/updated/closing_soon/expired/active |
| `flags` | list[str] | 재공고, 긴급, 수정 등 |
| `sources` | list[Source] | 출처 목록 |
| `attachments` | list[Attachment] | 파일명, URL, 텍스트 추출 성공 여부 |
| `content_hash` | str | 본문+마감일 해시 (변경 감지) |
| `first_seen_at` | datetime | |
| `last_seen_at` | datetime | |
| `last_reported_at` | datetime\|null | 리포트에 마지막으로 실린 시각 |
| `reannouncement_of` | str\|null | 재공고 원본 id |

### 12.2 `Source`

| 필드 | 설명 |
|---|---|
| `source_id` | `sources.yaml`의 id |
| `url` | 해당 소스에서의 원문 URL |
| `fetched_at` | |

### 12.3 `RunLog`

| 필드 | 설명 |
|---|---|
| `run_id`, `started_at`, `finished_at` | |
| `sources[]` | `{source_id, status(ok/fail/empty), listed, new, detail_fetched, errors[], duration_ms}` |
| `llm_calls`, `llm_input_tokens`, `llm_output_tokens`, `llm_cache_read_tokens` | 비용 추적 |
| `totals` | `{new, updated, closing_soon, expired}` |

---

## 13. 설정 파일 스키마

### 13.1 `config/sources.yaml`

```yaml
sources:
  - id: gojobs                 # 고유 id (영문, 변경 금지)
    name: 나라일터
    org_type: portal           # 4.1 코드
    tier: 1
    enabled: true
    verified: false            # 구현 시 URL·셀렉터 검증 후 true
    homepage: https://...
    adapter:
      type: api_json | rss | html_list | playwright | search_portal
      # 어댑터별 항목 (5.2)
    schedule: daily | daily_light   # daily_light는 12:30 경량 수집에도 포함
    region_hint: [경남]         # 지역 판정 보조
    notes: 운영 메모
```

### 13.2 `config/settings.yaml`

```yaml
timezone: Asia/Seoul
report:
  send_time_kst: "07:30"
  weekdays_only: false
  telegram_max_items: 15
  closing_soon_days: 3
  daily_overview_llm: false
classifier:
  include_threshold: 70
  review_threshold: 30
  llm_model: claude-opus-5
  llm_effort: low
  llm_max_calls_per_run: 60
collector:
  default_pages: 2
  default_days: 14
  backfill_days: 60
  per_domain_delay_sec: 1.5
  attachment_max_mb: 10
interests:
  weights: { lifelong: 1.5, it_digital: 1.2 }
  keywords: ["한국어", "디지털", "성인문해"]
notify:
  channels: [telegram, email]
```

### 13.3 `config/org_aliases.yaml`

```yaml
경남테크노파크: [경남TP, 경남 테크노파크, (재)경남테크노파크]
경상남도교육청: [경남교육청, 경남도교육청]
```

---

## 14. 운영·모니터링·장애 대응

### 14.1 헬스 규칙 (리포트 부록 + 별도 경고)

| 상황 | 감지 | 조치 |
|---|---|---|
| 소스 HTTP 오류 | run 로그 `status=fail` | 리포트 부록 표기. 3일 연속이면 경고 메시지 별도 발송 |
| 소스 0건 지속 | 7일 연속 `listed=0` (Tier 1은 3일) | 셀렉터 변경 의심 → 경고 |
| 셀렉터 드리프트 | 목록 파싱은 됐지만 제목·링크 결측률 > 30% | 해당 소스 결과 폐기 + 경고 |
| LLM 호출 상한 도달 | `llm_calls == max` | 리포트에 "n건 규칙 판별만 적용" 표기 |
| 발송 전 채널 실패 | 채널별 예외 | 다른 채널로 계속, 전부 실패 시 잡 실패 |
| Actions cron 미실행 | 마지막 run 시각 > 26시간 | 다음 실행 시 `missed_run=true`로 표기, 백필 범위 자동 확장 |

### 14.2 운영 작업

- 새 소스 추가: `sources.yaml`에 항목 추가 → `python -m gia probe <id>`로 목록 5건 출력 확인 → `verified: true`.
- 소스 비활성화: `enabled: false` (삭제 대신, 이력 유지).
- 백필: `workflow_dispatch`로 `backfill_days=60` 지정 실행.
- 오탐·미탐 피드백: `data/feedback.jsonl`에 `{id, label}` 기록 → 키워드 가중치·LLM 프롬프트 예시 갱신에 활용.

### 14.3 비용 추정 (월)

| 항목 | 추정 | 근거 |
|---|---|---|
| GitHub Actions | 0원 | 공개 저장소 무료. 비공개면 월 2,000분 무료 한도 내 (일 25분 × 30 = 750분) |
| 공공데이터포털 API | 0원 | 무료 |
| LLM (Opus 5, 일 30건 × 약 4k 입력 + 0.3k 출력) | 약 2~3만 원 | 입력 $5/MTok, 출력 $25/MTok 기준. 캐싱 적용 시 감소. Sonnet 5로 바꾸면 1만 원 이하 |
| 텔레그램·이메일 | 0원 | |

> N-07(월 1만 원 이내)을 지키려면 `llm_model`을 `claude-sonnet-5` 또는 `claude-haiku-4-5`로 설정하거나 LLM 호출을 판단 유보 구간에만 제한한다. 기본값은 정확도 우선으로 Opus 5로 두고, 사용자가 결정한다 (20절 참조).

---

## 15. 준법·윤리 (크롤링 정책)

1. **robots.txt 준수**: 소스 등록 시 확인하고, 실행 시에도 `Disallow` 경로는 요청하지 않는다 (`urllib.robotparser`).
2. **이용약관**: 민간 채용 포털(사람인·잡코리아 등)은 자동 수집을 약관으로 제한하는 경우가 있다. 이들은 공식 API 또는 이메일 알림 기능이 있으면 그것을 쓰고, 없으면 등록하지 않는다. `sources.yaml`의 `tos_checked` 항목으로 확인 여부를 기록한다.
3. **서버 부담 최소화**: 요청 간격, 조건부 요청, 상세 페이지 재수집 억제 (5.3).
4. **개인정보**: 담당자 이름·전화번호·이메일은 저장하지 않는다. 원문 링크로 대체한다. 본문 저장 시 정규식으로 전화번호·이메일을 마스킹한다.
5. **저작권**: 공고 본문 전문은 저장하되 외부 공개(GitHub Pages)에는 제목·요약·링크만 노출한다.
6. **식별 가능한 User-Agent와 연락처**를 제공해 차단 요청을 받을 수 있게 한다.

---

## 16. 테스트 전략

| 계층 | 테스트 | 방법 |
|---|---|---|
| 어댑터 | 파서 단위 테스트 | 실제 목록·상세 HTML을 `tests/fixtures/<source_id>/`에 저장해 오프라인 파싱 검증 |
| 마감일 파서 | 골든 테스트 | 패턴 30개 이상 입력→기대값 표 (`tests/deadline_cases.yaml`) |
| 첨부 추출 | 샘플 파일 테스트 | HWP/HWPX/PDF 각 2개 이상 |
| 분류기 | 골든 테스트 | 라벨링된 공고 100건 (포함 60, 제외 40)으로 정밀도·재현율 측정. 목표 정밀도 ≥ 0.9, 재현율 ≥ 0.85 |
| 중복 제거 | 케이스 테스트 | 같은 공고 3개 포털 버전, 재공고, 마감 연장 |
| 상태 전이 | 시나리오 테스트 | 날짜를 고정(freezegun)해 new→closing_soon→expired 확인 |
| 리포트 | 스냅샷 테스트 | 렌더링 결과를 스냅샷과 비교. 텔레그램 길이 제한 준수 확인 |
| 통합 | 드라이런 | `python -m gia collect --dry-run --sources gojobs` 로 네트워크 포함 실행, 발송 없음 |
| LLM | 계약 테스트 | 녹화된 응답(vcr)으로 파싱·폴백 경로 검증. 실 호출은 주 1회 수동 |

CI: PR마다 오프라인 테스트만 실행. 네트워크 테스트는 `workflow_dispatch`.

---

## 17. 기술 스택과 디렉터리 구조

### 17.1 스택

| 영역 | 선택 | 이유 |
|---|---|---|
| 언어 | Python 3.12 | 스크래핑·문서 파싱 생태계, Playwright 지원 |
| HTTP | httpx | HTTP/2, 타임아웃·재시도 제어 용이 |
| HTML 파싱 | selectolax (기본), BeautifulSoup (복잡한 경우) | 속도 |
| JS 렌더링 | Playwright (Chromium) | 필요 소스에만 |
| 문서 추출 | pyhwp(hwp5txt), zipfile+lxml(HWPX), pypdf, python-docx | 첨부 마감일 추출 |
| 유사도 | RapidFuzz | 중복 병합 |
| 스키마 | Pydantic v2 | 데이터 모델 + LLM 구조화 출력 |
| LLM | anthropic SDK | 7.2 |
| 템플릿 | Jinja2 | 리포트 3종 출력 |
| 설정 | PyYAML + Pydantic 검증 | |
| 스케줄·실행 | GitHub Actions | 서버 불필요 |
| 테스트 | pytest, freezegun, vcrpy | |

### 17.2 디렉터리

```
.
├── config/
│   ├── sources.yaml          # 수집원 레지스트리
│   ├── settings.yaml         # 동작 설정
│   └── org_aliases.yaml      # 기관명 별칭
├── gia/                      # 패키지 (Gyeongnam Instructor Announcement)
│   ├── __main__.py           # CLI: collect | report | probe | backfill
│   ├── models.py             # Pydantic 모델 (12절)
│   ├── config.py
│   ├── collectors/
│   │   ├── base.py           # SourceAdapter, HTTP 클라이언트, 레이트리밋
│   │   ├── api_json.py
│   │   ├── rss.py
│   │   ├── html_list.py
│   │   ├── playwright_list.py
│   │   └── search_portal.py
│   ├── extract/
│   │   ├── attachments.py    # HWP/HWPX/PDF/DOCX
│   │   └── deadline.py       # 마감일 파서
│   ├── normalize.py
│   ├── dedupe.py
│   ├── classify/
│   │   ├── rules.py
│   │   ├── llm.py
│   │   └── prompts/classifier_system.md
│   ├── store.py              # JSONL 읽기·쓰기, 상태 전이
│   ├── report/
│   │   ├── build.py
│   │   └── templates/{report.md.j2, telegram.html.j2, email.html.j2}
│   └── notify/{telegram.py, email.py, github_issue.py}
├── data/                     # 8.1
├── reports/                  # 일일 Markdown 아카이브
├── tests/
├── docs/
│   ├── DESIGN.md
│   └── DAILY_REPORT_TEMPLATE.md
├── .github/workflows/{collect.yml, report.yml, test.yml}
├── pyproject.toml
└── README.md
```

---

## 18. 구현 로드맵

| 단계 | 기간 | 내용 | 완료 기준 |
|---|---|---|---|
| 0. 준비 | 3일 | 공공데이터포털 API 키 3종 신청, 텔레그램 봇 생성, `sources.yaml` Tier 1 URL 실측 검증, 라벨링용 공고 100건 수집 | 키 발급, `verified: true` Tier 1 전부 |
| 1. 최소 동작 | 1~2주 | Tier 1 어댑터(api_json) 3개, 규칙 분류기, 마감일 파서, JSONL 저장, Markdown 리포트, 텔레그램 발송, Actions 스케줄 | 매일 아침 텔레그램 수신, 골든 테스트 통과 |
| 2. 공공 확장 | 2~3주 | `html_list` 어댑터, 경남도·시군 18개·교육청, 출자출연기관 15개, 첨부 추출, 중복 병합, 이메일 채널 | 소스 40개 이상, 중복률 < 5% |
| 3. 정밀도 | 1~2주 | LLM 추출 도입, 분야 분류, 관심 가중치, 마감 재알림, 피드백 루프 | 정밀도 ≥ 0.9, 재현율 ≥ 0.85 |
| 4. 민간·아카이브 | 2주 | 약관 확인된 민간 소스, Playwright 소스, GitHub Pages 아카이브, 주간 통계 | 민간 소스 5개 이상, 웹 아카이브 공개 |

---

## 19. 리스크와 완화책

| 리스크 | 영향 | 완화 |
|---|---|---|
| 사이트 개편으로 셀렉터 무효 | 해당 소스 누락 | 헬스 규칙(14.1)로 조기 감지, fixture 기반 빠른 수정, Tier 1 포털이 대부분 백업 |
| 마감일이 첨부(HWP)에만 있음 | 마감 누락·오판 | 첨부 텍스트 추출 필수 구현, 실패 시 `deadline_type=unknown`으로 표시하고 리포트에 "마감 확인 필요" |
| 봇 차단·캡차 (민간 포털) | 소스 사용 불가 | 약관·API 우선, 차단 소스는 비활성화 |
| Actions cron 지연 | 발송 시각 흔들림 | 11.1 대안 (단일 잡 + 정시 대기) |
| LLM 오판·거부 | 오탐·미탐 | 규칙 폴백, 피드백 루프, 확정 구간은 LLM 불필요 |
| 공공데이터포털 API 장애 | Tier 1 공백 | 동일 포털의 HTML 검색을 보조 어댑터로 등록 (`fallback_of`) |
| 데이터 파일 비대화 | 저장소 크기 | 월별 분할, 1년 후 DuckDB 이관 |
| 개인정보 저장 | 법적 리스크 | 15절 마스킹, 공개 범위 제한 |

---

## 20. 미결 사항 (사용자 결정 필요)

구현 착수 전에 아래 항목을 정하면 된다. 괄호 안은 설계서의 기본값이다.

1. **1차 발송 채널** (텔레그램) 과 2차 채널 (이메일) 사용 여부.
2. **발송 시각** (07:30 KST) 과 주말 발송 여부 (매일).
3. **LLM 모델과 예산**: 정확도 우선 `claude-opus-5` (월 2~3만 원) vs 비용 우선 `claude-sonnet-5` (월 1만 원 이하).
4. **인접 지역 포함 여부**: 부산·울산 근무지 공고 (제외).
5. **정규직 교원·교수 임용 공고 포함 여부** (제외, 시간강사·외래강사만 포함).
6. **민간 채용 포털 사용 범위**: 약관상 허용되는 범위 확인 후 결정 (Phase 4로 보류).
7. **관심 분야 가중치** 초기값 (전 분야 1.0).
