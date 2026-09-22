from datetime import timedelta

import httpx

from gia.collectors.base import HttpClient
from gia.config import ConfigBundle
from gia.models import Status
from gia.pipeline import collect
from gia.report.build import select_postings
from gia.store import Store
from tests.conftest import FIXTURES, NOW, make_source
from tests.helpers import make_hwpx


def _bundle(settings, sources):
    return ConfigBundle(settings=settings, sources=sources, aliases={})


def _http(settings):
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/list":
            return httpx.Response(200, content=(FIXTURES / "api_list.json").read_bytes(), headers={"content-type": "application/json"})
        if path == "/board/list":
            return httpx.Response(200, content=(FIXTURES / "board_list.html").read_bytes(), headers={"content-type": "text/html"})
        if path == "/board/view":
            name = "board_view_4.html" if request.url.params.get("id") == "4" else "board_view_3.html"
            return httpx.Response(200, content=(FIXTURES / name).read_bytes(), headers={"content-type": "text/html"})
        if path == "/files/notice.hwpx":
            body = make_hwpx(["디지털 문해교육 강사 인력풀 모집 공고", "접수기간: 2026. 9. 22.(화) ~ 2026. 10. 15.(목) 17:00까지"])
            return httpx.Response(200, content=body, headers={"content-type": "application/octet-stream", "content-disposition": "attachment; filename=\"notice.hwpx\""})
        if path == "/down":
            return httpx.Response(503)
        return httpx.Response(404)
    return HttpClient(settings.collector, transport=httpx.MockTransport(handler))


def _sources(monkeypatch):
    monkeypatch.setenv("DATA_GO_KR_KEY", "k")
    api = make_source("gojobs", "portal", type="api_json", endpoint="https://api.example.org/list", items_path="result",
                      params={"serviceKey": "${DATA_GO_KR_KEY}"},
                      field_map={"title": "recrutPbancTtl", "org_name": "instNm", "posted_at": "pbancBgngYmd", "deadline": "pbancEndYmd", "region": "workRgnNmLst", "url": "srcUrl"},
                      region_filter="@gyeongnam", keywords=["강사"], detail={"fetch": False})
    board = make_source("board", "local_public", type="html_list", list_url="https://site.example.org/board/list",
                        row_selector="table.board tbody tr", title_selector="td.title a", date_selector="td.date", detail={"body_selector": "div.content", "attachment_selector": "a.file"})
    board.name = "경남인재평생교육진흥원"
    down = make_source("down", "local_gov", type="html_list", list_url="https://site.example.org/down", row_selector="tr")
    todo = make_source("todo", "local_gov", type="html_list", list_url="TODO", row_selector="tr")
    return [api, board, down, todo]


def test_collect_end_to_end(settings, tmp_path, monkeypatch):
    bundle = _bundle(settings, _sources(monkeypatch))
    store = Store(tmp_path / "data")
    run = collect(bundle, store, _http(settings), now=NOW)

    by_id = {s.source_id: s for s in run.sources}
    assert by_id["gojobs"].status == "ok" and by_id["gojobs"].new == 1
    assert by_id["board"].status == "ok" and by_id["board"].new == 2
    assert by_id["down"].status == "fail"
    assert by_id["todo"].status == "unconfigured"

    titles = sorted(p.title for p in store.values())
    assert titles == ["2026 하반기 시민강좌 강사 모집", "2026-2학기 시간강사(전기) 모집", "디지털 문해교육 강사 인력풀 모집"]
    board_post = next(p for p in store.values() if "시민강좌" in p.title)
    assert board_post.flags == ["재공고", "첨부추출실패"]
    assert board_post.deadline.isoformat() == "2026-09-30T18:00:00+09:00"
    assert board_post.region == ["경남", "창원"]
    assert "[전화번호]" not in board_post.title
    assert "첨부추출실패" in board_post.flags  # /files/공고문.hwp 는 404
    attach_post = next(p for p in store.values() if "디지털 문해" in p.title)
    assert attach_post.deadline.isoformat() == "2026-10-15T17:00:00+09:00"  # 첨부(HWPX)에서만 마감일 확보
    assert "첨부추출실패" not in attach_post.flags
    assert (tmp_path / "data" / "postings" / "2026-09.jsonl").exists()
    assert (tmp_path / "data" / "runs").exists()

    # 두 번째 실행: 이미 본 URL은 상세를 다시 가져오지 않고 신규도 없다
    run2 = collect(bundle, store, _http(settings), now=NOW + timedelta(hours=6))
    assert run2.totals["new"] == 0
    assert {s.source_id: s.detail_fetched for s in run2.sources}["board"] == 0

    # 세 번째 실행(--refetch): 파서 오판으로 마감이 지난 것으로 저장된 공고를 다시 파싱해 바로잡는다 (#19 후속)
    board_post.deadline = NOW - timedelta(days=5)
    board_post.status = Status.expired
    store.upsert(board_post)
    store.save()
    store = Store(tmp_path / "data").load()
    run3 = collect(bundle, store, _http(settings), now=NOW + timedelta(hours=12), refetch=True)
    assert "재수집" in " ".join(run3.notes)
    assert {s.source_id: s.detail_fetched for s in run3.sources}["board"] == 2
    assert run3.totals["new"] == 0 and run3.totals["merged"] >= 2
    fixed = next(p for p in store.values() if "시민강좌" in p.title)
    assert fixed.deadline.isoformat() == "2026-09-30T18:00:00+09:00"
    assert fixed.canonical_key == board_post.canonical_key  # 같은 URL → 같은 공고, 키 유지

    # 네 번째 실행: adapter.org_name 을 바꾸면 canonical_key 가 달라지지만, 같은 URL 이므로 중복 생성 없이 기관명만 갱신
    board = next(s for s in bundle.sources if s.id == "board")
    board.adapter["org_name"] = "경남인재평생교육진흥원 평생학습관"
    n_before = len(list(store.values()))
    run4 = collect(bundle, store, _http(settings), now=NOW + timedelta(hours=13), refetch=True)
    assert run4.totals["new"] == 0 and len(list(store.values())) == n_before
    renamed = store.get(board_post.canonical_key)
    assert renamed is not None and renamed.org_name == "경남인재평생교육진흥원 평생학습관"
    assert fixed.status == Status.new  # 한 번도 보고되지 않았으므로 신규로 보고
    assert fixed.canonical_key in select_postings(bundle, store, NOW + timedelta(hours=12)).keys()

    # 리포트 선별: 둘 다 신규, 마감 임박 없음 (9/30 마감, 현재 9/21)
    data = select_postings(bundle, store, NOW)
    assert len(data.new) == 3 and data.closing == []
    store.mark_reported(data.keys(), NOW, 3)
    assert all(p.status == Status.active for p in store.values())


def test_collect_dry_run_does_not_write(settings, tmp_path, monkeypatch):
    bundle = _bundle(settings, _sources(monkeypatch)[:1])
    store = Store(tmp_path / "data")
    collect(bundle, store, _http(settings), now=NOW, dry_run=True)
    assert not (tmp_path / "data").exists()


def test_build_posting_survives_broken_text(settings, tmp_path, monkeypatch):
    """본문에 짝 없는 서로게이트가 있어도 공고를 만들고 수집이 계속된다."""
    from gia.models import RawPosting
    from gia.pipeline import build_posting
    from tests.conftest import make_source

    cfg = make_source("broken", type="html_list", list_url="https://x.example.org/l", row_selector="tr")
    bad = "강사 모집 공고\ud83d 접수: 2026. 9. 30.(수) 18:00 까지"
    raw = RawPosting(source_id="broken", title="평생교육원 강사 모집\udc00", url="https://x.example.org/1", body_text=bad)
    p = build_posting(raw, cfg, _bundle(settings, [cfg]), NOW)
    assert p is not None
    assert "\ud83d" not in p.title and "\udc00" not in p.title
    p.content_hash.encode("utf-8")
    assert p.deadline is not None and p.deadline.isoformat() == "2026-09-30T18:00:00+09:00"
