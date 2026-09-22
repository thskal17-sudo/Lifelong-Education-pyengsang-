"""Playwright 어댑터: 로컬 HTTP 서버가 JS로 목록을 그리는 페이지를 제공한다."""
from __future__ import annotations

import threading
from datetime import date
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from gia.collectors.base import HttpClient
from gia.collectors.playwright_list import PlaywrightListAdapter, find_chromium
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
VIEW_HTML = "<html><head><meta charset='utf-8'></head><body><div id='body'></div><script>document.getElementById('body').innerHTML='<p>접수기간: 2026. 9. 22.(월) ~ 2026. 9. 30.(수) 18:00까지</p><a class=\"file\" href=\"/f/공고.hwpx\">공고.hwpx</a>';</script></body></html>".encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = LIST_HTML if self.path.startswith("/list") else VIEW_HTML if self.path.startswith("/view") else b""
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


@pytest.mark.skipif(find_chromium() is None, reason="Chromium 없음 (PLAYWRIGHT_BROWSERS_PATH 또는 GIA_CHROMIUM_PATH)")
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
