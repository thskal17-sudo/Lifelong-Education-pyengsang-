import httpx
import pytest

from gia.notify.github_issue import BODY_LIMIT, issue_body, send_issue


def _client(handler):
    """httpx.post 를 가짜 전송으로 바꿔치기한다."""
    def fake_post(url, json=None, headers=None, timeout=None):
        return handler(url, json, headers)
    return fake_post


def test_issue_body_appends_site_and_truncates():
    assert issue_body("  본문  ") == "본문"
    body = issue_body("본문", "https://example.org/")
    assert body.endswith("전체 목록: https://example.org/")
    long = issue_body("가" * (BODY_LIMIT + 500))
    assert len(long) < BODY_LIMIT + 200 and long.endswith("reports/ 폴더에 있습니다)")


def test_send_issue_posts_and_returns_url(monkeypatch):
    seen = {}

    def handler(url, payload, headers):
        seen.update(url=url, payload=payload, headers=headers)
        return httpx.Response(201, json={"html_url": "https://github.com/o/r/issues/7"},
                              request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", _client(handler))
    out = send_issue("o/r", "tok", "제목", "본문", labels=["공고"])
    assert out == "https://github.com/o/r/issues/7"
    assert seen["url"] == "https://api.github.com/repos/o/r/issues"
    assert seen["payload"] == {"title": "제목", "body": "본문", "labels": ["공고"]}
    assert seen["headers"]["Authorization"] == "Bearer tok"


def test_send_issue_retries_without_labels_on_422(monkeypatch):
    """라벨이 없는 저장소에서 422 가 나면 라벨을 빼고 다시 연다."""
    calls = []

    def handler(url, payload, headers):
        calls.append(payload)
        if "labels" in payload:
            return httpx.Response(422, json={"message": "Validation Failed"},
                                  request=httpx.Request("POST", url))
        return httpx.Response(201, json={"html_url": "https://github.com/o/r/issues/8"},
                              request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", _client(handler))
    assert send_issue("o/r", "tok", "제목", "본문", labels=["공고"]).endswith("/8")
    assert len(calls) == 2 and "labels" not in calls[1]


def test_send_issue_raises_on_error(monkeypatch):
    def handler(url, payload, headers):
        return httpx.Response(403, json={"message": "Forbidden"},
                              request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", _client(handler))
    with pytest.raises(httpx.HTTPStatusError):
        send_issue("o/r", "tok", "제목", "본문")
