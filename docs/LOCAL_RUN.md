# 국내 IP에서 손으로 돌리기

대학 5곳은 **GitHub 러너(미국 IP)에서 접속이 막혀** 매일 수집에서 빠져 있다.
사이트 구조 문제가 아니라 상대 서버가 해외 IP를 거절하는 것이라, **한국에서
접속되는 컴퓨터**에서 돌리면 잡힐 가능성이 높다.

| 소스 id | 대학 | 러너에서 본 증상 |
|---|---|---|
| `pknu_lifelong` | 국립부경대학교 | TCP 연결 자체가 안 됨(40초 대기 후 실패) |
| `dit_lifelong` | 동의과학대학교 | 1,627바이트 `title=Error` 페이지 |
| `ks_lifelong` | 경성대학교 | 인증서 검증 실패 → http도 25초 초과 |
| `inje_lifelong` | 인제대학교 | 403 Forbidden (3회 동일) |
| `kaya_lifelong` | 가야대학교 | 연결 끊김 RemoteDisconnected (3회 동일) |

**robots.txt로 막힌 5개 대학은 여기 해당하지 않는다.** 그쪽은 IP를 바꿔도 정책이
그대로이므로, 운영자 허락을 받기 전에는 국내에서도 수집하지 않는다. 아래 절차대로
돌려도 `robots.txt 차단` 으로 걸러진다 — 의도된 동작이다.

## 1. 준비 (처음 한 번)

Python 3.11 이상이 필요하다.

```bash
git clone https://github.com/thskal17-sudo/Lifelong-Education-pyengsang-.git
cd Lifelong-Education-pyengsang-

python -m venv .venv
source .venv/bin/activate          # 윈도우: .venv\Scripts\activate

pip install -e ".[browser]"
playwright install chromium        # 자바스크립트로 그리는 게시판용
```

`playwright install chromium` 은 200MB쯤 받는다. 부경대·동의과학대처럼 클릭해야
상세가 열리는 게시판이 있어서 필요하다.

## 2. 열리는지부터 본다

수집 전에 `probe` 로 한 곳씩 확인한다. **저장하지 않으므로 몇 번이든 돌려도 된다.**

```bash
python -m gia probe pknu_lifelong --limit 5 --ignore-keywords
```

- `--ignore-keywords` : 키워드 필터를 끄고 목록을 전부 보여준다. 셀렉터가 맞는지
  보려면 이게 편하다.
- `--detail` : 첫 건의 본문·마감일·점수까지 뽑아 본다.

나올 수 있는 결과:

| 결과 | 뜻 | 다음 할 일 |
|---|---|---|
| 목록이 제목·날짜와 함께 나온다 | 열렸다 | 3번으로 |
| `0건` 인데 오류는 없다 | 접속은 됐는데 셀렉터가 안 맞는다 | 4번으로 |
| 연결 끊김·403·시간 초과 | 이 컴퓨터에서도 막힌다 | 아래 '그래도 안 될 때' |
| `robots.txt 차단` | 정책상 대상 아님 | 건드리지 않는다 |

5곳을 한 번에 보려면:

```bash
for s in pknu_lifelong dit_lifelong ks_lifelong inje_lifelong kaya_lifelong; do
  echo "=== $s ==="
  python -m gia probe $s --limit 3 --ignore-keywords
done
```

## 3. 실제로 수집해서 저장하기

`--sources` 로 **이름을 직접 댄 소스는 `enabled: false` 여도 돈다.** 매일 도는
수집은 그대로 건너뛰므로, 이 다섯 곳만 손으로 채우는 용도다.

```bash
# 먼저 저장 없이 확인
python -m gia collect --sources pknu_lifelong,dit_lifelong --dry-run

# 괜찮으면 저장
python -m gia collect --sources pknu_lifelong,dit_lifelong
```

처음 돌릴 때는 지난 공고까지 훑는 게 좋다:

```bash
python -m gia collect --sources pknu_lifelong --backfill-days 365
```

결과 확인:

```bash
python -m gia status          # 저장소 요약
python -m gia report --print  # 오늘 리포트를 화면에만
```

### 결과를 저장소에 반영하기

수집 결과는 `data/postings.json` 에 쌓인다. 이걸 올려야 웹사이트와 메일에 나온다.

```bash
git add data
git commit -m "collect: 부경대·동의과학대 국내 IP 수집"
git pull --rebase origin main   # 그 사이 자동 수집이 올린 게 있을 수 있다
git push origin main
```

`git pull --rebase` 를 빼먹으면 자동 수집과 충돌한다. 매일 06:30 KST에 수집이
돌므로 그 시간대는 피하는 게 낫다.

## 4. 열렸는데 0건일 때 — 셀렉터 맞추기

접속은 되는데 목록이 안 잡히면 실제 HTML을 보고 셀렉터를 고쳐야 한다.

```bash
python scripts/dump_rendered.py "https://ps.pknu.ac.kr/..." 
```

이 스크립트는 브라우저로 페이지를 열어 표·링크·iframe 구조를 뽑아 준다.
환경변수로 동작을 바꾼다:

| 변수 | 쓸 때 |
|---|---|
| `WAIT_FOR="table tbody tr"` | 자바스크립트가 늦게 그리는 게시판. 이 셀렉터가 나타날 때까지 기다린다 |
| `CLICK="td.tit a"` | 상세가 주소 없이 클릭으로만 열리는 게시판. 첫 글을 눌러 본다 |
| `DETAIL=1` | 목록이 아니라 상세 페이지 구조를 볼 때 |
| `DUMP_UA` | 봇 UA를 거부하는 사이트. 비워 두면 크롬 UA를 쓴다(신라대가 이 경우였다) |
| `RENDER_TIMEOUT_SEC` | 기본 25초로 모자란 무거운 페이지 |

주소는 인자로 줘도 되고 `URLS` 로 여러 개를 줘도 된다:

```bash
WAIT_FOR="table tbody tr" URLS="https://a/board https://b/board" python scripts/dump_rendered.py
```

뽑은 구조에 맞춰 `config/sources.yaml` 의 해당 항목에서 `row_selector`,
`title_selector`, `date_selector` 를 고치고 2번부터 다시 한다.

셀렉터가 맞아서 수집까지 되면 그 항목에 `enabled: true`, `verified: true` 를
적고 `notes` 에 "국내 IP에서 확인" 을 남긴다. **다만 러너에서는 여전히 막히므로,
`enabled: true` 로 바꾸면 매일 수집이 그 소스에서 실패 로그를 남긴다.** 국내에서만
돌릴 거라면 `enabled: false` 로 두고 `--sources` 로 부르는 편이 낫다.

## 5. 그래도 안 될 때

집 인터넷에서도 막힌다면 IP 문제가 아니다. 확인할 것:

- 브라우저로 직접 그 주소가 열리는가 → 안 열리면 사이트가 내려간 것이다
- 열리는데 스크립트만 막힌다면 UA 차단이다 → `DUMP_UA` 로 크롬 UA를 흉내 내 본다
- 인증서 오류(경성대)라면 `config/sources.yaml` 의 그 항목에 `tls_legacy: true`
  를 넣어 본다. 구형 TLS만 받는 서버가 있다

## 주의

- **로그인 벽은 우회하지 않는다.** 춘해보건대는 게시판이 회원 전용이라 국내
  IP로도 대상이 아니다.
- **robots.txt는 국내에서도 지킨다.** 위 표의 5곳 외에 손대지 않는다.
- 남의 서버를 두드리는 일이다. `probe` 를 연달아 수십 번 돌리지 말고, 필요한
  만큼만 돌린다. 수집기는 도메인별 요청 간격을 지키게 돼 있다.
