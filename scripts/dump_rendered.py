"""브라우저(playwright)로 렌더링한 뒤 게시판 구조를 덤프한다.

서버 HTML 에는 목록이 없고 JS 로 그리는 사이트(부산 지역 대학 평생교육원 다수)용.
scripts/dump_structure.py 의 분석 함수를 그대로 쓰고, HTML 만 브라우저에서 받아 온다.

사용:
    URLS="https://a/board https://b/board" python scripts/dump_rendered.py
    WAIT_FOR="table tbody tr" URLS=... python scripts/dump_rendered.py   # 이 셀렉터가 나타날 때까지 대기
    CLICK="#tab2" URLS=... python scripts/dump_rendered.py               # 렌더 후 한 번 클릭 (탭 전환)
    CLICK="td.textWrap a" WAIT_FOR="table tbody tr" WAIT_AFTER="#dvView" DETAIL=1 URLS=...
        # 목록이 그려질 때까지 기다렸다가 첫 글을 클릭하고, 열린 상세를 본문 후보로 분석한다
        # (상세가 URL 없이 자바스크립트로만 열리는 게시판용)
"""
from __future__ import annotations

import os
import re
import sys
from urllib.parse import urljoin

from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dump_structure import DETAIL, dump_detail, dump_links, dump_list, short_path  # noqa: E402

CHROME_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
# UA 를 바꿔 가며 같은 페이지를 훑을 수 있게 한다. 목록은 내주면서 자바스크립트 동작(postback)만
# 막는 사이트가 있어서, 수집기 UA 로도 되는지 확인하려면 이 값을 갈아 끼워야 한다
UA = os.environ.get("DUMP_UA") or CHROME_UA


def _chromium_path() -> str | None:
    """수집기와 같은 규칙으로 크로미움을 찾는다 (러너 이미지에 미리 깔린 빌드 재사용)."""
    try:
        from gia.collectors.playwright_list import find_chromium
    except ImportError:
        return os.environ.get("GIA_CHROMIUM_PATH") or None
    return find_chromium()


def _wait(page, selector: str | None, timeout_ms: int, label: str) -> None:
    try:
        if selector:
            page.wait_for_selector(selector, timeout=timeout_ms)
        else:
            page.wait_for_load_state("networkidle", timeout=timeout_ms)
    except Exception as e:  # noqa: BLE001
        print(f"  ({label} 대기 실패 {selector or 'networkidle'}: {str(e)[:80]})")


def render(url: str, wait_for: str | None, click: str | None, timeout_ms: int | None = None) -> tuple[str, str]:
    """(최종 URL, 렌더링된 HTML).

    click 이 있으면 WAIT_FOR 로 목록이 그려지기를 먼저 기다린 뒤 클릭하고,
    WAIT_AFTER(없으면 networkidle)로 상세가 열리기를 기다린다.
    """
    from playwright.sync_api import sync_playwright

    timeout_ms = timeout_ms or int(os.environ.get("RENDER_TIMEOUT_SEC") or 25) * 1000
    wait_after = os.environ.get("WAIT_AFTER") or None
    with sync_playwright() as pw:
        kw = {"headless": True}
        exe = _chromium_path()
        if exe:
            kw["executable_path"] = exe
        browser = pw.chromium.launch(**kw)
        ctx = browser.new_context(user_agent=UA, locale="ko-KR")
        page = ctx.new_page()
        try:
            # 느린 정부·대학 사이트는 domcontentloaded 도 오래 걸린다. commit 으로 먼저 붙고 기다린다
            page.goto(url, wait_until="commit", timeout=timeout_ms)
            # 클릭 대상이 늦게 그려지는 게시판이 많다. 먼저 목록을 기다린 뒤 누른다
            _wait(page, wait_for, timeout_ms, "클릭 전")
            if click:
                page.wait_for_timeout(300)
                try:
                    page.locator(click).first.click(timeout=timeout_ms)
                    print(f"  (클릭함 {click})")
                except Exception as e:  # noqa: BLE001
                    print(f"  (클릭 실패 {click}: {str(e)[:80]})")
                _wait(page, wait_after, timeout_ms, "클릭 후")
            elif not wait_for:
                _wait(page, None, timeout_ms, "로드")
            page.wait_for_timeout(1200)  # 늦게 그리는 목록 대비
            return page.url, page.content()
        finally:
            ctx.close()
            browser.close()


def dump(url: str) -> None:
    print("=" * 100)
    print("URL:", url, "(rendered)", "UA=" + UA[:60])
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
    # 클릭으로 연 상세는 URL 이 목록 그대로라 자동 판별이 안 된다. DETAIL=1 로 강제한다
    if os.environ.get("DETAIL") or DETAIL.search(final) or DETAIL.search(url):
        dump_detail(soup)
    else:
        dump_list(soup)
        dump_links(soup, final)
    # 목록이 안 보일 때 가장 흔한 원인: 표가 iframe 안에 있다.
    # page.content() 는 iframe 속을 안 담으므로 주소만이라도 알려 준다
    frames = [f for f in (i.get("src") or "" for i in soup.find_all(["iframe", "frame"])) if f]
    if frames:
        print(f"\n[IFRAME] ({len(frames)}) — 목록이 이 안에 있으면 이 주소를 직접 떠야 한다")
        for f in frames[:10]:
            print("  ", urljoin(final, f))
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
