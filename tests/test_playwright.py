"""Playwright 어댑터: 로컬 HTTP 서버가 JS로 목록을 그리는 페이지를 제공한다."""
from __future__ import annotations

import threading
from datetime import date
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from gia.collectors.base import HttpClient
from gia.collectors.playwright_list import PlaywrightListAdapter, playwright_ready
from tests.conftest import make_source

LIST_HTML = """<html><head><meta charset="utf-8"></head><body>
<table class="list"><tbody id="rows"></tbody></table>
<script>
setTimeout(function(){
  document.getElementById('rows').innerHTML =
    '<tr><td class="title"><a href="#" onclick="view(7)">JS 게시판 수영강사 모집</a></td><td class="date">2026-09-20</td></tr>' +
    '<tr><td class="title"><a href="#" onclick="view(6)">수강생 모집 안내</a></td><td class="date">2026-09-19</td></tr>';
}, 50);
</script></body></html>""".encode("utf-8")
POSTBACK_HTML = """<html><head><meta charset="utf-8"></head><body>
<table class="pb"><tbody>
  <tr><td class="no">1037</td><td class="tit"><a href="javascript:__doPostBack('ctl00$grd$ctl02$lnk','')">포스트백 게시판 요가강사 위촉 공고</a></td><td class="date">2026-09-20</td></tr>
  <tr><td class="no">1036</td><td class="tit"><a href="javascript:__doPostBack('ctl00$grd$ctl03$lnk','')">수강생 모집 안내</a></td><td class="date">2026-09-19</td></tr>
</tbody></table>
<div id="detail"></div>
<script>
function __doPostBack(t, a){
  var n = t.indexOf('ctl02') >= 0 ? '1037' : '1036';
  document.getElementById('detail').innerHTML =
    '<div class="view">글번호 ' + n + ' 접수기간: 2026. 9. 22.(월) ~ 2026. 9. 30.(수) 18:00까지</div>';
}
document.querySelectorAll('td.tit a').forEach(function(a){
  a.addEventListener('click', function(e){ e.preventDefault(); __doPostBack(a.getAttribute('href'), ''); });
});
</script></body></html>""".encode("utf-8")
FNVIEW_HTML = """<html><head><meta charset="utf-8"></head><body>
<div class="board_list"><table><tbody>
  <tr><td>2</td><td class="left"><a href="javascript:void(0)" onclick="fn_View('402','88118')">fn_View 게시판 바리스타 강사 초빙</a></td><td class="c_gray">2026-09-21</td></tr>
  <tr><td>1</td><td class="left"><a href="javascript:void(0)" onclick="fn_View('402','88117')">수강신청 안내</a></td><td class="c_gray">2026-09-15</td></tr>
</tbody></table></div>
<div class="board_view"></div>
<script>
function fn_View(b, seq){
  document.querySelector('div.board_view').innerHTML =
    '<p>seq ' + seq + ' 접수기간: 2026. 9. 21.(월) ~ 2026. 10. 5.(월) 18:00까지</p>';
}
</script></body></html>""".encode("utf-8")
UA_TEMPLATE = """<html><head><meta charset="utf-8"></head><body>
<table class="ua"><tbody>
  <tr><td class="t"><a href="/view?id=1">{ua} 강사</a></td><td class="d">2026-09-20</td></tr>
</tbody></table></body></html>"""

VIEW_HTML = "<html><head><meta charset='utf-8'></head><body><div id='body'></div><script>document.getElementById('body').innerHTML='<p>접수기간: 2026. 9. 22.(월) ~ 2026. 9. 30.(수) 18:00까지</p><a class=\"file\" href=\"/f/공고.hwpx\">공고.hwpx</a>';</script></body></html>".encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/ua"):
            body = UA_TEMPLATE.format(ua=self.headers.get("User-Agent", "")).encode("utf-8")
        else:
            body = (LIST_HTML if self.path.startswith("/list")
                    else POSTBACK_HTML if self.path.startswith("/postback")
                    else FNVIEW_HTML if self.path.startswith("/fnview")
                    else VIEW_HTML if self.path.startswith("/view") else b"")
        self.send_response(200 if body else 404)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):  # 조용히
        pass


@pytest.fixture
def server():
    httpd = HTTPServer(("127.0.0.1", 0), Handler)
    th = threading.Thread(target=httpd.serve_forever, daemon=True)
    th.start()
    yield f"http://127.0.0.1:{httpd.server_port}"
    httpd.shutdown()


@pytest.mark.skipif(not playwright_ready(), reason="playwright 패키지 또는 Chromium 없음")
def test_playwright_list_and_detail(settings, server):
    cfg = make_source("jsboard", "local_public", type="playwright", list_url=f"{server}/list",
                      wait_for="table.list tbody tr", row_selector="table.list tbody tr", title_selector="td.title a", date_selector="td.date",
                      link_attr="onclick", link_regex=r"view\((\d+)\)", link_url_template=f"{server}/view?id={{1}}",
                      keywords=["강사"], detail={"render": True, "body_selector": "#body", "attachment_selector": "a.file"})
    http = HttpClient(settings.collector)
    ad = PlaywrightListAdapter(cfg, http, settings.collector, since=date(2026, 9, 1))
    try:
        listings = ad.fetch_list()
        assert [(l.title, l.url) for l in listings] == [("JS 게시판 수영강사 모집", f"{server}/view?id=7")]
        raw = ad.fetch_detail(listings[0])
        assert "접수기간" in raw.body_text
        assert raw.attachments == [f"{server}/f/공고.hwpx"]
    finally:
        ad.close()
        http.close()
    assert ad._browser is None


@pytest.mark.skipif(not playwright_ready(), reason="playwright 패키지 또는 Chromium 없음")
def test_playwright_click_detail(settings, server):
    """상세가 URL 없이 자바스크립트로만 열리는 게시판 (신라대 __doPostBack, 부산가톨릭대 fn_View).

    링크는 글 번호로 합성하고, 상세는 목록에서 제목을 클릭해 읽는다.
    """
    cfg = make_source("pbboard", "university", type="playwright", list_url=f"{server}/postback",
                      wait_for="table.pb tbody tr", row_selector="table.pb tbody tr",
                      title_selector="td.tit a", date_selector="td.date",
                      id_selector="td.no", link_url_template=f"{server}/postback?no={{1}}",
                      keywords=["강사"],
                      detail={"fetch": True, "click": True, "body_selector": "div.view"})
    http = HttpClient(settings.collector)
    ad = PlaywrightListAdapter(cfg, http, settings.collector, since=date(2026, 9, 1))
    try:
        listings = ad.fetch_list()
        # 글 번호로 만든 링크라 재수집해도 같은 공고로 이어진다
        assert [(l.title, l.url) for l in listings] == [
            ("포스트백 게시판 요가강사 위촉 공고", f"{server}/postback?no=1037")
        ]
        raw = ad.fetch_detail(listings[0])
        assert "글번호 1037" in raw.body_text     # 두 번째 글이 아니라 클릭한 글이 열렸다
        assert "접수기간" in raw.body_text
    finally:
        ad.close()
        http.close()


@pytest.mark.skipif(not playwright_ready(), reason="playwright 패키지 또는 Chromium 없음")
def test_playwright_click_detail_onclick_link(settings, server):
    """상세 URL 은 onclick 인자로 만들고, 본문은 클릭해서 읽는 게시판 (부산가톨릭대 fn_View).

    fn_View('402','88118') 처럼 인자가 둘이라 두 번째 그룹({2})을 seq 로 쓴다.
    """
    cfg = make_source("fnboard", "university", type="playwright", list_url=f"{server}/fnview",
                      wait_for="div.board_list table tbody tr", row_selector="div.board_list table tbody tr",
                      title_selector="td.left a", date_selector="td.c_gray",
                      link_attr="onclick", link_regex=r"fn_View\('(\d+)','(\d+)'",
                      link_url_template=f"{server}/fnview?seq={{2}}",
                      keywords=["강사"],
                      detail={"fetch": True, "click": True, "body_selector": "div.board_view"})
    http = HttpClient(settings.collector)
    ad = PlaywrightListAdapter(cfg, http, settings.collector, since=date(2026, 9, 1))
    try:
        listings = ad.fetch_list()
        assert [(l.title, l.url) for l in listings] == [
            ("fn_View 게시판 바리스타 강사 초빙", f"{server}/fnview?seq=88118")
        ]
        raw = ad.fetch_detail(listings[0])
        assert "seq 88118" in raw.body_text     # 두 번째 글이 아니라 클릭한 글이 열렸다
        assert "접수기간" in raw.body_text
    finally:
        ad.close()
        http.close()


@pytest.mark.skipif(not playwright_ready(), reason="playwright 패키지 또는 Chromium 없음")
def test_playwright_click_detail_url_from_page(settings, server):
    """목록에 글 번호가 없으면 클릭해서 열린 주소를 공고 주소로 쓴다 (창신대·김해대).

    목록 단계의 주소는 임시값이라, 그대로 두면 중복 판정과 리포트 링크가 어긋난다.
    """
    cfg = make_source("fnboard2", "university", type="playwright", list_url=f"{server}/fnview",
                      wait_for="div.board_list table tbody tr", row_selector="div.board_list table tbody tr",
                      title_selector="td.left a", date_selector="td.c_gray",
                      id_selector="td:first-child", link_url_template=f"{server}/fnview#row{{1}}",
                      keywords=["강사"],
                      detail={"fetch": True, "click": True, "url_from_page": True,
                              "body_selector": "div.board_view"})
    http = HttpClient(settings.collector)
    ad = PlaywrightListAdapter(cfg, http, settings.collector, since=date(2026, 9, 1))
    try:
        listings = ad.fetch_list()
        assert listings[0].url == f"{server}/fnview#row2"      # 목록 단계: 임시 주소
        raw = ad.fetch_detail(listings[0])
        assert raw.url == f"{server}/fnview"                   # 클릭 뒤 실제 주소로 교체
        assert "seq 88118" in raw.body_text
    finally:
        ad.close()
        http.close()


@pytest.mark.skipif(not playwright_ready(), reason="playwright 패키지 또는 Chromium 없음")
def test_playwright_source_user_agent_override(settings, server):
    """adapter.user_agent 로 이 게시판에서만 UA 를 갈아 끼운다.

    봇 UA 에는 자바스크립트가 빠진 페이지를 내주는 사이트가 있다(신라대).
    """
    ua = "Mozilla/5.0 (X11; Linux x86_64) TestBrowser/1.0"
    cfg = make_source("uaboard", "university", type="playwright", list_url=f"{server}/ua",
                      user_agent=ua, wait_for="table.ua tbody tr", row_selector="table.ua tbody tr",
                      title_selector="td.t a", date_selector="td.d", keywords=["강사"],
                      detail={"fetch": False})
    http = HttpClient(settings.collector)
    ad = PlaywrightListAdapter(cfg, http, settings.collector, since=date(2026, 9, 1))
    try:
        listings = ad.fetch_list()
        assert len(listings) == 1
        assert listings[0].title.startswith(ua)     # 설정한 UA 로 요청이 나갔다
        assert settings.collector.user_agent not in listings[0].title
    finally:
        ad.close()
        http.close()
