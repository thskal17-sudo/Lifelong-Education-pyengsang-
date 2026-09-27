"""목록이 제목을 잘라 내주는 게시판.

마산대 강좌 개설 신청은 목록 앵커에 '…평생교육과정 신규…' 까지만 담아 내준다
(2026-09-27 러너 확인, 43자). 상세에는 온전한 제목이 있으므로 거기서 다시 읽는다.
"""
import httpx

from gia.collectors.base import HttpClient
from gia.collectors.html_list import HtmlListAdapter, extract_title_html
from gia.models import RawListing
from tests.conftest import NOW, make_source

FULL = "2026학년도 2학기 창원시 · 함안군 및 창녕군 위탁 평생교육과정 신규강좌 개설 제안 공모 안내"
CUT = "2026학년도 2학기 창원시 · 함안군 및 창녕군 위탁 평생교육과정 신규..."

# 실제 상세 페이지 구조. 제목 아래로 메타데이터가 줄줄이 따라붙는다
DETAIL_HTML = f"""
<html><body><div id="IContents_divView"><div class="board-view">
  <div class="board-view-title">
    {FULL}
    <span>event</span><span>학년도-학기 : 2026-2학기</span>
    <span>view_list</span><span>교육과정 : 평생위탁과정</span>
    <span>visibility</span><span>조회수 : 421</span>
  </div>
  <div class="board-view-cont">※ 직업능력교육 과정 외 4개 과정 지원 가능. 접수: 2026.06.30 까지</div>
</div></div></body></html>
"""


def test_extract_title_takes_only_the_first_line():
    """제목 칸에 딸린 학년도·조회수가 제목에 섞이면 안 된다."""
    got = extract_title_html(DETAIL_HTML, "div.board-view-title")
    assert got == FULL
    assert "조회수" not in got and "학년도-학기" not in got


def test_extract_title_missing_selector_is_empty():
    assert extract_title_html(DETAIL_HTML, "div.nope") == ""


def _adapter(settings, **detail):
    src = make_source("lectopen", "university", type="html_list",
                      list_url="https://lifelong.example.ac.kr/lectopen",
                      row_selector="table tbody tr", title_selector="td.text-left a",
                      detail={"fetch": True, "body_selector": "div.board-view-cont", **detail})
    http = HttpClient(settings.collector, transport=httpx.MockTransport(
        lambda request: httpx.Response(200, text=DETAIL_HTML, headers={"content-type": "text/html"})))
    return HtmlListAdapter(src, http, settings.collector), http


def test_detail_title_selector_replaces_the_cut_title(settings):
    adapter, http = _adapter(settings, title_selector="div.board-view-title")
    try:
        got = adapter.fetch_detail(RawListing(source_id="lectopen", title=CUT, url="https://lifelong.example.ac.kr/view/13"))
        assert got.title == FULL
    finally:
        http.close()


def test_without_the_selector_the_list_title_is_kept(settings):
    adapter, http = _adapter(settings)
    try:
        got = adapter.fetch_detail(RawListing(source_id="lectopen", title=CUT, url="https://lifelong.example.ac.kr/view/13"))
        assert got.title == CUT
    finally:
        http.close()


def test_a_shorter_detail_title_never_wins(settings):
    """상세 제목이 더 짧으면 목록 쪽을 지킨다.

    셀렉터가 엉뚱한 칸을 가리켜 '내용보기' 같은 한 낱말을 물어오는 일이 있다.
    그걸로 멀쩡한 제목을 덮으면 공고를 알아볼 수 없게 된다.
    """
    adapter, http = _adapter(settings, title_selector="div.board-view-cont")
    try:
        got = adapter.fetch_detail(RawListing(source_id="lectopen", title=FULL, url="https://lifelong.example.ac.kr/view/13"))
        assert got.title == FULL
    finally:
        http.close()
