# 부·울·경 대학 평생교육원 강사공고

부산·울산·경남에 있는 **대학 부설 평생교육원**(평생학습원·미래교육원 등)의 강사 모집 공고를
매일 모아 하루 한 번 요약을 만든다. 지자체·교육청·출자출연기관·채용포털은 이 저장소의 대상이 아니다.

## 하는 일

1. `config/sources.yaml` 에 등록된 평생교육원 게시판을 매일 06:30 KST 에 수집한다 (`collect` 워크플로).
2. 제목·본문·첨부(HWP·PDF·DOCX)에서 강사 공고 여부를 규칙으로 가려내고 마감일을 뽑는다.
3. 07:30 KST 에 `reports/YYYY-MM-DD.md` 로 요약을 만든다 (`report` 워크플로).
   텔레그램·이메일 설정이 없으면 파일만 만들고 보고 상태를 기록한다.
4. `data/` 의 공고를 GitHub Pages 아카이브로 배포한다 (`pages` 워크플로).

## 명령

```bash
pip install -e ".[dev]"
python -m pytest -q                      # 오프라인 테스트
python -m gia sources                    # 소스별 설정 상태
python -m gia probe <id> --detail        # 소스 하나 시험 수집
python -m gia collect --dry-run          # 전체 수집, 저장 안 함
python -m gia collect                    # 수집·저장 (data/)
python -m gia collect --refetch --sources <id>   # 이미 아는 URL도 다시 파싱 (파서 수정 후 보정)
python -m gia report                     # 요약본 생성·출력 (reports/)
python -m gia site --out site            # Pages 아카이브 생성
```

## 수집 범위

| 지역 | 상태 |
|---|---|
| 경남 | 창원대(공지·구인구직), 마산대(공지·강좌개설), 연암공대, 진주보건대, 거제대 수집 중. 경상국립대·경남대·거창캠퍼스는 robots.txt 차단, 인제대·가야대·창신대·창원문성대·김해대·동원과기대는 접속·구조 문제로 보류 |
| 부산 | 부산대·부경대·동아대·동의대·부산외대·부산보건대·동의과학대·영산대 등 후보 등록, 게시판 구조 확인 전 |
| 울산 | 울산대·울산과학대·춘해보건대 후보 등록, 게시판 구조 확인 전 |

비활성 소스는 모두 `notes` 에 사유를 적어 둔다. 자세한 검증 절차는 `docs/SOURCE_VERIFICATION.md`.

## 구조

- `gia/` 파이프라인 (수집·판별·마감일 추출·리포트·사이트)
- `config/sources.yaml` 수집원 레지스트리 (단일 진실 원천)
- `config/settings.yaml` 동작 설정, `config/org_aliases.yaml` 기관명 표준화
- `.github/workflows/` collect·report·pages·probe·test
- `docs/DESIGN.md` 설계, `docs/SOURCE_VERIFICATION.md` 소스 검증 방법
