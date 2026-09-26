"""GitHub 이슈 알림.

설정할 게 없는 대신 저장소 알림 설정을 그대로 탄다 — 이슈가 열리면 GitHub 이
저장소를 지켜보는 사람에게 메일과 모바일 푸시를 보낸다. 워크플로에 이미 있는
GITHUB_TOKEN 으로 쓰기 때문에 비밀값을 따로 넣을 필요가 없다.

조용한 날에는 열지 않는다(gia/__main__.py 에서 신규·마감임박이 있을 때만 호출).
매일 이슈가 열리면 알림이 배경 소음이 되어 정작 볼 것을 놓친다.
"""
from __future__ import annotations

import httpx

API = "https://api.github.com"
BODY_LIMIT = 60000  # 이슈 본문 상한은 65536자. 여유를 둔다


def issue_body(markdown: str, site_url: str = "") -> str:
    body = markdown.strip()
    if len(body) > BODY_LIMIT:
        body = body[:BODY_LIMIT] + "\n\n…(본문이 길어 잘랐습니다. 전체는 reports/ 폴더에 있습니다)"
    if site_url:
        body += f"\n\n---\n전체 목록: {site_url}"
    return body


def default_assignees(repo: str) -> list[str]:
    """저장소 주인을 담당자로 쓴다.

    저장소를 지켜보지(watch) 않으면 이슈가 열려도 메일이 오지 않는다 — API 로 만든
    저장소는 주인조차 구독이 안 걸려 있다. 담당자로 지정된 사람에게는 watch 와
    무관하게 항상 알림이 가므로, 알림이 설정에 좌우되지 않게 못을 박아 둔다.
    """
    owner = repo.split("/", 1)[0].strip()
    return [owner] if owner else []


def send_issue(repo: str, token: str, title: str, body: str,
               labels: list[str] | None = None, timeout: float = 20.0,
               assignees: list[str] | None = None) -> str:
    """이슈를 열고 주소를 돌려준다. repo 는 'owner/name' 형식."""
    payload: dict = {"title": title, "body": body}
    if labels:
        payload["labels"] = labels
    if assignees:
        payload["assignees"] = assignees
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    url = f"{API}/repos/{repo}/issues"
    r = httpx.post(url, json=payload, headers=headers, timeout=timeout)
    if r.status_code == 422 and (labels or assignees):
        # 라벨이 없거나 담당자가 협업자가 아니면 422 가 난다. 장식은 포기하고 이슈는 연다
        r = httpx.post(url, json={"title": title, "body": body},
                       headers=headers, timeout=timeout)
    r.raise_for_status()
    return r.json()["html_url"]
