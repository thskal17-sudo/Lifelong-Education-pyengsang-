# 수집원 검증 가이드 (Phase 2)

`config/sources.yaml`의 `TODO` 값을 채우고 `verified: true`로 바꾸는 절차입니다. 네트워크가 열린 환경에서 진행합니다.

## 0. 준비: GitHub Actions 로 구조 확인하기

작업 환경에서 사이트 접속이 막혀 있으면 `probe` 워크플로를 수동 실행한다 (Actions → probe → Run workflow).

- `urls`: 목록 페이지 URL을 공백으로 구분해 넣으면 `scripts/dump_structure.py`가 표/목록 구조, 행 내부 요소, 링크·onclick, 페이징, 날짜 표본을 로그에 출력한다.
  URL에 `amode=view`, `View.do`, `Detail.do`, `regSn=` 이 있으면 상세 페이지로 보고 본문·첨부 후보를 출력한다.
- `sources`: source id 를 넣으면 `gia probe <id> --detail` 을 실행한다.
- 기본 브랜치가 아닌 브랜치의 스크립트로 실행하려면 Run workflow 의 "Use workflow from" 에서 그 브랜치를 고른다.

### probe 워크플로 입력 `days`

게시가 한 학기에 몇 건뿐인 게시판(대학 평생교육원 등)은 기본 14일 창 안에 글이 없어 `목록 0건`으로 나온다. 셀렉터가 맞는지 보려면 `days` 입력에 `400` 처럼 넉넉한 값을 넣어 실행한다 (러너 안에서만 `settings.yaml` 의 `default_days` 를 바꾸며 저장소에는 반영되지 않는다).

## 0-1. 현황 보기

```bash
python -m gia sources            # 소스별 설정 상태 (미설정 이유 포함)
python -m gia sources --tier 2   # 특정 tier만
```

## 1. 게시판 URL 찾기

- 기관 홈페이지에서 "채용", "공고", "모집", "인재채용", "공지사항" 메뉴를 연다.
- 목록 URL에 페이지 번호가 있으면 `{page}`로 바꾼다. 예: `.../list.do?pageIndex={page}`
- 목록이 JavaScript로만 그려지면(HTML 소스에 글 제목이 없음) 지금은 등록하지 말고 `notes`에 "JS 렌더링 필요"라고 적는다 (Phase 4 Playwright 어댑터).
- 로그인이 필요하거나 robots.txt가 해당 경로를 막으면 등록하지 않는다.

## 2. 응답 저장

```bash
python -m gia probe <source_id> --save-fixture
```

`tests/fixtures/live/<source_id>/` 아래에 목록 페이지(과 첫 상세 페이지)가 저장됩니다. 이 파일을 열어 셀렉터를 정합니다.
`list_url`만 채운 상태여도 `--save-fixture`는 동작합니다 (row_selector가 `TODO`면 저장만 하고 파싱은 건너뜀).

## 3. 셀렉터 정하기

| 항목 | 설명 | 흔한 값 |
|---|---|---|
| `row_selector` | 공고 한 건이 되는 요소 | `table.bbs_list tbody tr`, `ul.board_list li`, `div.list-item` |
| `title_selector` | 행 안에서 제목 링크 | `td.subject a`, `td.title a`, `a.tit` |
| `link_selector` | 제목과 다른 요소에 링크가 있을 때 | 보통 생략 (title_selector 사용) |
| `date_selector` | 게시일 | `td.date`, `span.date`, `td:nth-child(4)` |
| `org_selector` | 포털(여러 기관)일 때 기관명 | `td.org` |
| `encoding` | EUC-KR 사이트 | `euc-kr` (meta charset이 없을 때만) |
| `detail.body_selector` | 상세 본문 | `div.bbs_view_content`, `div.view_con`, `td.content` |
| `detail.attachment_selector` | 첨부 링크 | `a[href*="download"]`, `ul.file_list a` |

### onclick 링크 게시판

`<a href="#" onclick="fn_view('12345')">제목</a>`처럼 URL이 없는 경우:

```yaml
adapter:
  type: html_list
  list_url: https://www.example.go.kr/board/list.do?pageIndex={page}
  row_selector: table.bbs_list tbody tr
  title_selector: td.subject a
  link_attr: onclick
  link_regex: "fn_view\\('(\\d+)'\\)"
  link_url_template: "https://www.example.go.kr/board/view.do?seq={1}"
  date_selector: td.date
  detail: { body_selector: div.bbs_view_content, attachment_selector: "a[href*='download']" }
```

`{0}`은 정규식 전체 일치, `{1}`부터는 그룹입니다.

### 정부 표준 CMS 예시 (표 형태)

```yaml
adapter:
  type: html_list
  list_url: https://www.example.go.kr/portal/saeol/gosi/list.do?pageIndex={page}
  row_selector: table.tbl_list tbody tr
  title_selector: td.tit a
  date_selector: td:nth-child(4)
  keywords: [강사, 교강사, 지도자, 지도사]
  detail: { body_selector: div.view_cont, attachment_selector: "div.file a" }
```

### JS 렌더링 게시판 (playwright)

HTML 소스에 글 제목이 없고 스크립트가 목록을 그리는 사이트는 `type: playwright`로 등록합니다. 셀렉터 설정은 `html_list`와 같고 `wait_for`(목록이 그려졌음을 뜻하는 셀렉터)만 추가합니다.

```yaml
adapter:
  type: playwright
  list_url: https://www.example.or.kr/recruit/list?page={page}
  wait_for: table.list tbody tr
  row_selector: table.list tbody tr
  title_selector: td.title a
  date_selector: td.date
  detail: { render: true, body_selector: div.view_body }   # render: false 면 상세는 일반 HTTP로
```

- 실행 환경에 Chromium이 필요합니다. `pip install -e ".[browser]"` 후 `playwright install chromium`. GitHub Actions에서는 `collect.yml`에 `playwright install --with-deps chromium` 단계를 추가합니다 (약 1분).
- 이미 설치된 Chromium을 쓰려면 `GIA_CHROMIUM_PATH` 환경변수로 실행 파일을 지정합니다.
- 브라우저 렌더링은 HTTP보다 10배 이상 느리므로 `paging.max_pages`를 1~2로 둡니다.

### 검색어 기반 포털 (search_portal)

민간 채용 포털처럼 검색 결과 페이지에서 수집하는 소스입니다. `query_url_template`의 `{query}`에 `queries`를 차례로 넣고, 결과는 `html_list`와 같은 셀렉터로 파싱합니다. 같은 URL은 한 번만 남깁니다.

```yaml
adapter:
  type: search_portal
  query_url_template: https://www.example.com/search?q={query}&page={page}
  queries: ["강사 경남", "강사 창원"]
  row_selector: div.item
  title_selector: a.title
  org_selector: span.company
  date_selector: span.date
  paging: { max_pages: 2 }
```

민간 포털은 **이용약관의 자동 수집 조항을 먼저 확인**하고 `tos_checked: true`를 기록한 뒤에만 `enabled: true`로 바꿉니다. 약관이 금지하면 등록하지 않고 사이트의 이메일 알림 기능을 씁니다.

### API 소스

`gia probe <id> --save-fixture`가 저장한 JSON/XML을 보고 `items_path`와 `field_map`을 맞춥니다.
날짜 형식이 다르면 `date_formats`에 추가합니다 (`%Y%m%d`, `%Y-%m-%d`, `%y-%m-%d` 등).

## 4. 확인

```bash
python -m gia probe <source_id>            # 목록 5건 출력
python -m gia probe <source_id> --detail   # 첫 건의 본문 길이, 마감일, 점수, 포함 여부
python -m gia collect --dry-run --sources <source_id>
```

확인 항목

- 제목·링크·날짜가 올바르게 나온다.
- 상세 본문에 접수기간 문장이 들어 있다. 첨부에만 있으면 `attachment_selector`를 확인한다.
- 마감일이 `fixed`로 잡힌다. `unknown`이면 첨부 추출 실패인지, 날짜 표기가 특이한지 본다.
- 강사 공고가 아닌 글은 점수 30 미만으로 제외된다.

## 5. 마무리

- `verified: true`, `tos_checked: true`(약관 확인 시)로 바꾼다.
- 저장한 fixture 중 대표 목록·상세 HTML을 `tests/fixtures/<source_id>/`로 옮기고 `tests/test_sources_live.py`에 파싱 테스트를 추가하면 사이트 개편을 CI에서 잡을 수 있다 (선택).
- 같은 공고가 Tier 1 포털에서도 수집되면 이 소스는 `notes`에 적고 우선순위를 낮춘다.

## 자주 생기는 문제

| 증상 | 원인 | 조치 |
|---|---|---|
| 목록 0건 | row_selector 불일치, JS 렌더링 | fixture HTML에서 셀렉터 재확인 |
| 제목은 나오는데 URL이 홈페이지 | onclick 링크 | `link_attr`, `link_regex`, `link_url_template` |
| 글자 깨짐 | 인코딩 | `encoding: euc-kr` |
| 리포트 기관명이 게시판 이름('○○ 채용정보')이나 작성자('관리자')로 나옴 | `org_selector` 가 없거나 작성자 열을 가리킴 | `adapter.org_name: 기관명` 으로 고정값을 준다 (`org_selector` 보다 후순위) |
| 마감일 unknown | 첨부(HWP)에만 있음 | `attachment_selector` 확인, `첨부추출실패` 플래그 확인 |
| HTTP 403 | User-Agent 차단 또는 robots | `notes`에 기록하고 비활성화 |
| `robots.txt 차단: …` | 사이트가 `User-agent: * Disallow: /` (경상국립대·경남대·거창캠퍼스 평생교육원, 2026-09-22 확인) | `respect_robots` 정책상 수집하지 않는다. 구조를 확인했으면 `verified: true` 로 두되 `enabled: false` 와 사유를 `notes` 에 적는다. 운영자 동의를 받으면 활성화 |
| robots.txt 에 `Disallow: /*Board.do` 같은 와일드카드가 있는데 probe 는 통과함 | 파이썬 `urllib.robotparser` 가 `*` 와일드카드를 지원하지 않음 (동원과기대 평생교육원) | RFC 9309 기준으로는 차단이므로 비활성 처리. 와일드카드 지원은 gia HTTP 클라이언트 개선 항목 |
| 목록은 열리는데 `목록 0건` | 14일 창 안에 게시글이 없음 (셀렉터 문제가 아님) | probe 워크플로 `days` 입력(예: 400)으로 재실행해 셀렉터를 확인 |
| `CERTIFICATE_VERIFY_FAILED` | 서버가 중간 인증서를 안 보냄 (인제대 본교, 양산시설공단) | 브라우저는 열리지만 httpx 는 실패. `adapter.tls_verify: false` 를 주면 그 소스의 URL 호스트만 검증을 생략한다 (다른 소스에는 영향 없음). 사유를 `notes` 에 적는다 |
| `SSLV3_ALERT_HANDSHAKE_FAILURE`, `DH_KEY_TOO_SMALL` | TLS 1.0/약한 암호만 지원하는 구형 서버 (창신대·창원문성대·거제대 평생교육원, 밀양문화관광재단) | `scripts/dump_structure.py` 는 SECLEVEL 낮춘 컨텍스트로 재시도해 구조를 볼 수 있음. gia 는 `adapter.tls_legacy: true` 를 주면 그 소스의 호스트만 구형 TLS 컨텍스트(검증 생략)로 연다. playwright 어댑터에는 적용되지 않음 |
| 연결 시간초과(ConnectTimeout)가 여러 사이트에서 동시에 남 | GitHub 호스티드 러너 IP 대역을 지자체 방화벽이 차단. 같은 시각 다른 러너(Azure 리전)에서는 열리기도 함 (2026-09-21 관측: eastus2 러너는 창원·김해·하동·거창 정상, eastus 러너는 전부 시간초과) | 재실행해 다른 러너에 배정되길 기다리거나, 국내 IP(자체 호스팅 러너·프록시)로 수집. `collect` 워크플로도 같은 영향을 받으므로 소스별 실패를 일시 장애로 취급하고 다음 날 재시도 |
| 재실행해도 특정 사이트만 계속 실패 (시간초과, 400 'Request Blocked', 1.4KB 차단 페이지, error.html 리다이렉트, DNS 실패) | 해당 사이트가 GitHub 호스티드 러너 IP 대역을 일관되게 차단 (2026-09-22 관측: 브라우저형 헤더·Referer·재시도를 적용하고 westus3·centralus 러너 3회로 시도해도 진주·거제·의령·함안·창녕·고성·남해·산청·함양·합천·경남도청 12곳은 동일하게 실패. UA 문제가 아님) | 러너 재실행으로는 해결되지 않음. 국내 IP가 필요: (1) PC에서 `python -m gia probe <id> --detail` 을 직접 실행해 셀렉터를 채우거나, (2) 국내 자체 호스팅 러너(`runs-on: self-hosted`)를 등록하거나, (3) 국내 HTTP 프록시를 Secrets(`HTTPS_PROXY`)로 넣는다. 그때까지 해당 소스는 `list_url: TODO`(미검증)로 두고 `candidate_list_url`만 유지 |
