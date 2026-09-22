from datetime import date

import httpx

from gia.collectors.base import HttpClient
from gia.collectors.search_portal import SearchPortalAdapter
from tests.conftest import make_source

PAGE = """<html><head><meta charset="utf-8"></head><body>
<div class="item"><a class="title" href="/job/{a}">{q} 학원 강사 모집</a><span class="company">창원학원</span><span class="date">2026-09-19</span></div>
<div class="item"><a class="title" href="/job/common">공통 강사 채용</a><span class="company">김해센터</span><span class="date">2026-09-18</span></div>
</body></html>"""


def test_search_portal_iterates_queries_and_dedupes(settings):
    seen_urls = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_urls.append(str(request.url))
        q = request.url.params.get("q", "")
        return httpx.Response(200, content=PAGE.format(a=q.replace(" ", "-"), q=q).encode("utf-8"), headers={"content-type": "text/html"})

    cfg = make_source("portal", "portal", type="search_portal", query_url_template="https://p.example.org/search?q={query}&page={page}",
                      queries=["강사 경남", "강사 창원"], row_selector="div.item", title_selector="a.title", org_selector="span.company",
                      date_selector="span.date", paging={"max_pages": 1})
    http = HttpClient(settings.collector, transport=httpx.MockTransport(handler))
    listings = SearchPortalAdapter(cfg, http, settings.collector, since=date(2026, 9, 1)).fetch_list()
    assert len(seen_urls) == 2 and "q=%EA%B0%95%EC%82%AC%20%EA%B2%BD%EB%82%A8" in seen_urls[0]
    titles = [l.title for l in listings]
    assert titles == ["강사 경남 학원 강사 모집", "공통 강사 채용", "강사 창원 학원 강사 모집"]  # 공통 항목은 한 번만
    assert listings[0].org_name == "창원학원" and listings[0].extra["query"] == "강사 경남"


def test_search_portal_without_queries(settings):
    cfg = make_source("portal", "portal", type="search_portal", query_url_template="https://p.example.org/s?q={query}", queries=[], row_selector="div")
    http = HttpClient(settings.collector, transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    assert SearchPortalAdapter(cfg, http, settings.collector).fetch_list() == []
