from datetime import date
from pathlib import Path

import httpx

from gia.collectors.api_json import ApiJsonAdapter, xml_to_obj
from gia.collectors.base import HttpClient
from gia.collectors.html_list import HtmlListAdapter
from tests.conftest import FIXTURES, make_source


def _client(settings, routes: dict[str, tuple[str, str]]) -> HttpClient:
    """routes: path → (content-type, fixture 파일명)"""
    def handler(request: httpx.Request) -> httpx.Response:
        key = request.url.path
        if key in routes:
            ctype, name = routes[key]
            return httpx.Response(200, content=(FIXTURES / name).read_bytes(), headers={"content-type": ctype})
        return httpx.Response(404)
    return HttpClient(settings.collector, transport=httpx.MockTransport(handler))


def test_api_json_filters_keywords_and_region(settings, monkeypatch):
    monkeypatch.setenv("DATA_GO_KR_KEY", "k")
    cfg = make_source("gojobs", "portal", type="api_json", endpoint="https://api.example.org/list", format="json",
                      params={"serviceKey": "${DATA_GO_KR_KEY}"}, paging={"page_param": "pageNo", "size_param": "numOfRows", "size": 100, "max_pages": 2},
                      items_path="result", field_map={"title": "recrutPbancTtl", "org_name": "instNm", "posted_at": "pbancBgngYmd", "deadline": "pbancEndYmd", "region": "workRgnNmLst", "url": "srcUrl"},
                      keywords=["강사"], region_filter="@gyeongnam")
    http = _client(settings, {"/list": ("application/json", "api_list.json")})
    ad = ApiJsonAdapter(cfg, http, settings.collector, since=date(2026, 9, 1))
    listings = ad.fetch_list()
    assert [l.title for l in listings] == ["2026-2학기 시간강사(전기) 모집"]
    l = listings[0]
    assert l.org_name == "한국폴리텍VII대학 창원캠퍼스" and l.posted_at == date(2026, 9, 18) and l.deadline_text == "20260930"


def test_api_json_missing_secret(settings, monkeypatch):
    from gia.config import MissingSecret
    monkeypatch.delenv("DATA_GO_KR_KEY", raising=False)
    cfg = make_source("gojobs", "portal", type="api_json", endpoint="https://api.example.org/list", params={"serviceKey": "${DATA_GO_KR_KEY}"}, items_path="result", field_map={"title": "t"})
    http = _client(settings, {})
    try:
        ApiJsonAdapter(cfg, http, settings.collector).fetch_list()
        assert False, "MissingSecret expected"
    except MissingSecret:
        pass


def test_api_xml(settings, monkeypatch):
    monkeypatch.setenv("WORKNET_API_KEY", "k")
    cfg = make_source("work24", "portal", type="api_json", endpoint="https://api.example.org/wanted", format="xml",
                      params={"authKey": "${WORKNET_API_KEY}"}, items_path="wantedRoot.wanted",
                      field_map={"title": "title", "org_name": "company", "posted_at": "regDt", "deadline": "closeDate", "region": "region", "url": "wantedInfoUrl"},
                      date_formats=["%y-%m-%d"])
    http = _client(settings, {"/wanted": ("application/xml", "worknet.xml")})
    listings = ApiJsonAdapter(cfg, http, settings.collector, since=date(2026, 9, 1)).fetch_list()
    assert len(listings) == 2
    assert listings[0].posted_at == date(2026, 9, 19) and listings[0].region_text == "경남 창원시"
    assert listings[1].deadline_text == "상시"


def test_xml_to_obj_single_item_becomes_list_via_adapter():
    import xml.etree.ElementTree as ET
    root = ET.fromstring("<r><item><a>1</a></item></r>")
    assert xml_to_obj(root) == {"item": {"a": "1"}}


def test_html_list_and_detail(settings):
    cfg = make_source("board", "local_public", type="html_list", list_url="https://site.example.org/board/list?page={page}",
                      row_selector="table.board tbody tr", title_selector="td.title a", date_selector="td.date",
                      paging={"max_pages": 3}, detail={"body_selector": "div.content", "attachment_selector": "a.file"})
    http = _client(settings, {"/board/list": ("text/html", "board_list.html"), "/board/view": ("text/html", "board_view_3.html")})
    ad = HtmlListAdapter(cfg, http, settings.collector, since=date(2026, 9, 1))
    listings = ad.fetch_list()
    # 6월 게시글은 since 이전이라 제외, 페이지 2는 가장 오래된 글이 since 이전이라 요청하지 않음
    assert [l.title for l in listings] == ["디지털 문해교육 강사 인력풀 모집", "[재공고] 2026 하반기 시민강좌 강사 모집", "2026 시민강좌 수강생 모집 안내"]
    listings = listings[1:]
    assert listings[0].url == "https://site.example.org/board/view?id=3"
    assert listings[0].org_name == "board 기관"
    raw = ad.fetch_detail(listings[0])
    assert "접수기간" in raw.body_text and "alert" not in raw.body_text
    assert raw.attachments == ["https://site.example.org/files/공고문.hwp"]


def test_html_list_onclick_links(settings):
    cfg = make_source("onclick", "local_gov", type="html_list", list_url="https://site.example.org/bbs/list",
                      row_selector="table.bbs_list tbody tr", title_selector="td.subject a", date_selector="td.date",
                      link_attr="onclick", link_regex=r"fn_view\('(\d+)'\)", link_url_template="https://site.example.org/bbs/view?seq={1}")
    http = _client(settings, {"/bbs/list": ("text/html", "board_onclick.html")})
    listings = HtmlListAdapter(cfg, http, settings.collector, since=date(2026, 9, 1)).fetch_list()
    assert [(l.title, l.url) for l in listings] == [("체육센터 수영강사 모집", "https://site.example.org/bbs/view?seq=1001")]
    assert listings[0].posted_at == date(2026, 9, 19)


def test_tls_verify_false_routes_host_to_insecure_client(settings):
    """adapter.tls_verify: false 인 소스의 호스트만 검증 없는 클라이언트로 보내고, 다른 호스트는 그대로 둔다 (#13)."""
    import httpx
    from gia.collectors.base import HttpClient
    from gia.collectors.registry import build_adapter, insecure_hosts
    from tests.conftest import make_source

    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.host)
        return httpx.Response(200, text="<html><body><table><tbody></tbody></table></body></html>", headers={"content-type": "text/html"})

    http = HttpClient(settings.collector, transport=httpx.MockTransport(handler))
    cfg = make_source("insecure", type="html_list", list_url="https://Insecure.example.org/board?page={page}", row_selector="tr",
                      link_url_template="https://files.example.org/view/{1}", tls_verify=False)
    assert insecure_hosts(cfg) == ["insecure.example.org", "files.example.org"]
    build_adapter(cfg, http, settings.collector)
    assert http._client_for("https://insecure.example.org/board") is http._mode_clients["insecure"]
    assert http._client_for("https://files.example.org/view/1") is http._mode_clients["insecure"]
    assert http._client_for("https://other.example.org/") is http._client
    assert http._mode_clients["insecure"] is not http._client
    assert http.get("https://insecure.example.org/board").status_code == 200
    assert http.get("https://other.example.org/").status_code == 200
    assert seen == ["insecure.example.org", "other.example.org"]
    http.close()

    plain = HttpClient(settings.collector, transport=httpx.MockTransport(handler))
    build_adapter(make_source("secure", type="html_list", list_url="https://secure.example.org/board", row_selector="tr"), plain, settings.collector)
    assert plain._mode_clients == {}
    plain.close()

    legacy = HttpClient(settings.collector, transport=httpx.MockTransport(handler))
    build_adapter(make_source("old", type="html_list", list_url="https://old.example.org/board", row_selector="tr", tls_legacy=True), legacy, settings.collector)
    assert legacy._host_mode == {"old.example.org": "legacy"}
    assert legacy._client_for("https://old.example.org/x") is legacy._mode_clients["legacy"]
    assert legacy.get("https://old.example.org/board").status_code == 200
    import ssl
    ctx = HttpClient.legacy_tls_context()
    assert ctx.minimum_version == ssl.TLSVersion.TLSv1 and ctx.verify_mode == ssl.CERT_NONE
    legacy.close()
