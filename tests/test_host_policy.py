"""호스트별 응답 대기·재시도 (adapter.timeout_sec / adapter.retries).

연암공대 평생교육원이 기본 20초로 'The read operation timed out' 을 반복해서 넣었다
(2026-11-22). 그 전엔 HTTP 수집기가 adapter.timeout_sec 을 아예 읽지 않아, 설정에
적어도 조용히 무시됐다 — 브라우저 수집기만 읽었다.
"""
import httpx

from gia.collectors.base import FetchError, HttpClient
from gia.collectors.registry import build_adapter
from tests.conftest import make_source


def _flaky(fail_times: int, seen: list):
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.extensions.get("timeout", {}).get("read"))
        if len(seen) <= fail_times:
            raise httpx.ReadTimeout("The read operation timed out", request=request)
        return httpx.Response(200, text="ok")
    return handler


def test_host_timeout_is_sent_with_the_request(settings):
    seen: list = []
    http = HttpClient(settings.collector, transport=httpx.MockTransport(_flaky(0, seen)))
    http.set_host_policy("slow.example.kr", timeout=45)
    http.get("https://slow.example.kr/list")
    http.get("https://fast.example.kr/list")
    assert seen[0] == 45
    assert seen[1] == settings.collector.request_timeout_sec


def test_host_retries_count(settings):
    settings.collector.per_domain_delay_sec = 0  # 테스트에서는 재시도 간격을 두지 않는다
    seen: list = []
    http = HttpClient(settings.collector, transport=httpx.MockTransport(_flaky(4, seen)))
    http.set_host_policy("slow.example.kr", retries=5)
    assert http.get("https://slow.example.kr/list").text == "ok"
    assert len(seen) == 5

    seen.clear()
    http2 = HttpClient(settings.collector, transport=httpx.MockTransport(_flaky(4, seen)))
    try:
        http2.get("https://other.example.kr/list")
        raise AssertionError("기본 3회에서 멈춰야 한다")
    except FetchError:
        pass
    assert len(seen) == 3


def test_registry_applies_adapter_timeout_to_http(settings):
    seen: list = []
    http = HttpClient(settings.collector, transport=httpx.MockTransport(_flaky(0, seen)))
    cfg = make_source(type="html_list", list_url="https://lifelong.yc.ac.kr/bbs/board.php?page={page}",
                      row_selector="li", title_selector="a", timeout_sec=45, retries=3)
    build_adapter(cfg, http, settings.collector)
    http.get("https://lifelong.yc.ac.kr/bbs/board.php?page=1")
    assert seen[0] == 45
