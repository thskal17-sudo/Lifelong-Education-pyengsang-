"""브라우저(playwright)로 렌더링한 뒤 게시판 구조를 덤프한다.

서버 HTML 에는 목록이 없고 JS 로 그리는 사이트(부산 지역 대학 평생교육원 다수)용.
scripts/dump_structure.py 의 분석 함수를 그대로 쓰고, HTML 만 브라우저에서 받아 온다.

사용:
    URLS="https://a/board https://b/board" python scripts/dump_rendered.py
    WAIT_FOR="table tbody tr" URLS=... python scripts/dump_rendered.py   # 이 셀렉터가 나타날 때까지 대기
    CLICK="#tab2" URLS=... python scripts/dump_rendered.py               # 렌더 후 한 번 클릭 (탭 전환)
"""
from __future__ import annotations

import os
import re
import sys

from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dump_structure import DETAIL, dump_detail, dump_links, dump_list, short_path  # noqa: E402

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"


def render(url: str, wait_for: str | None, click: str | None, timeout_ms: int = 25000) -> tuple[str, str]:
    """(최종 URL, 렌더링된 HTML)."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(user_agent=UA, locale="ko-KR")
        page = ctx.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            if click:
                try:
                    page.click(click, timeout=5000)
                except Exception as e:  # noqa: BLE001
                    print(f"  (클릭 실패 {click}: {str(e)[:80]})")
            if wait_for:
                try:
                    page.wait_for_selector(wait_for, timeout=timeout_ms)
                except Exception as e:  # noqa: BLE001
                    print(f"  (대기 실패 {wait_for}: {str(e)[:80]})")
            else:
                try:
                    page.wait_for_load_state("networkidle", timeout=timeout_ms)
                except Exception:  # noqa: BLE001
                    pass
            page.wait_for_timeout(1200)  # 늦게 그리는 목록 대비
            return page.url, page.content()
        finally:
            ctx.close()
            browser.close()


def dump(url: str) -> None:
    print("=" * 100)
    print("URL:", url, "(rendered)")
    try:
        final, html = render(url, os.environ.get("WAIT_FOR") or None, os.environ.get("CLICK") or None)
    except Exception as exc:  # noqa: BLE001
        print("  RENDER ERROR:", str(exc)[:300])
        return
    print(f"final={final} bytes={len(html)}")
    soup = BeautifulSoup(html, "lxml")
    print("title:", (soup.title.get_text(strip=True) if soup.title else "")[:80])
    sel_env = os.environ.get("BODY_SELECTOR")
    if sel_env:
        for node in soup.select(sel_env)[:3]:
            print(f"\n[BODY TEXT] {short_path(node)}")
            print(node.get_text("\n", strip=True)[:3000])
    if DETAIL.search(url):
        dump_detail(soup)
    else:
        dump_list(soup)
        dump_links(soup, final)
    # JS 로 여는 상세 링크는 onclick 에 있으므로 따로 보여 준다
    onclicks = []
    for a in soup.find_all(["a", "tr", "li", "button"]):
        oc = a.get("onclick") or ""
        if oc and re.search(r"(view|read|detail|board|goto|fn_)", oc, re.I):
            text = a.get_text(" ", strip=True)[:34]
            onclicks.append(f"   {text!r} onclick={oc[:110]}")
    if onclicks:
        print(f"\n[ONCLICK] JS 상세 링크 후보 ({len(onclicks)})")
        print("\n".join(onclicks[:15]))


if __name__ == "__main__":
    for u in sys.argv[1:] or os.environ.get("URLS", "").split():
        dump(u)
