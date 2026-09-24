"""JS 렌더링 게시판 어댑터 (docs/DESIGN.md 5.2 playwright). html_list와 같은 셀렉터 설정을 쓴다."""
from __future__ import annotations

import glob
import os
from datetime import date, datetime, timedelta

from ..extract.deadline import KST
from ..models import RawListing, RawPosting
from .base import FetchError, SourceAdapter
from .html_list import extract_attachments_html, extract_body_html, parse_list_html


def playwright_ready() -> bool:
    """playwright 패키지와 크로미움이 모두 있어야 이 어댑터를 쓸 수 있다."""
    try:
        import playwright.sync_api  # noqa: F401
    except ImportError:
        return False
    return find_chromium() is not None


def find_chromium() -> str | None:
    """실행 파일 경로: GIA_CHROMIUM_PATH > PLAYWRIGHT_BROWSERS_PATH 안의 chrome > Playwright 기본."""
    explicit = os.environ.get("GIA_CHROMIUM_PATH")
    if explicit and os.path.exists(explicit):
        return explicit
    base = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if base:
        for pat in ("chromium-*/chrome-linux/chrome", "chromium-*/chrome-mac/Chromium.app/Contents/MacOS/Chromium"):
            hits = sorted(glob.glob(os.path.join(base, pat)))
            if hits:
                return hits[-1]
    return None


class PlaywrightListAdapter(SourceAdapter):
    type_name = "playwright"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._pw = None
        self._browser = None

    # ---- browser lifecycle ---------------------------------------------
    def _page(self):
        if self._browser is None:
            try:
                from playwright.sync_api import sync_playwright
            except ImportError as e:  # pragma: no cover
                raise FetchError("playwright 패키지가 없음: pip install playwright") from e
            self._pw = sync_playwright().start()
            kw = {"headless": True}
            exe = find_chromium()
            if exe:
                kw["executable_path"] = exe
            try:
                self._browser = self._pw.chromium.launch(**kw)
            except Exception as e:  # noqa: BLE001
                self._pw.stop()
                self._pw = None
                raise FetchError(f"브라우저 실행 실패: {str(e)[:150]}") from e
        # adapter.user_agent: 이 게시판에서만 UA 를 갈아 끼운다. 봇 UA 에는 자바스크립트가 빠진
        # 가벼운 페이지를 내주는 사이트가 있어서(신라대), 그대로 두면 상세가 열리지 않는다
        ctx = self._browser.new_context(user_agent=self.a.get("user_agent") or self.settings.user_agent, locale="ko-KR")
        return ctx.new_page()

    def close(self) -> None:
        try:
            if self._browser is not None:
                self._browser.close()
            if self._pw is not None:
                self._pw.stop()
        finally:
            self._browser = None
            self._pw = None

    def _render(self, url: str, wait_for: str | None) -> str:
        self.http.check_allowed(url)
        self.http.throttle(url)
        page = self._page()
        try:
            # adapter.timeout_sec: 무거운 목록 페이지용 (김해대는 기본 20초로 domcontentloaded 도 못 넘긴다)
            timeout_ms = int(float(self.a.get("timeout_sec") or self.settings.request_timeout_sec) * 1000)
            # commit 으로 먼저 붙고 wait_for 로 기다린다. domcontentloaded 까지 기다리면
            # 광고·폰트까지 묶여서, 정작 목록은 다 그려졌는데 시간만 넘긴다
            page.goto(url, wait_until="commit", timeout=timeout_ms)
            if wait_for:
                page.wait_for_selector(wait_for, timeout=timeout_ms)
            else:
                page.wait_for_load_state("networkidle", timeout=timeout_ms)
            return page.content()
        except Exception as e:  # noqa: BLE001
            raise FetchError(f"렌더링 실패 {url}: {str(e)[:150]}") from e
        finally:
            page.context.close()

    # ---- adapter API -------------------------------------------------------
    def fetch_list(self) -> list[RawListing]:
        a = self.a
        list_url: str = a["list_url"]
        max_pages = int((a.get("paging") or {}).get("max_pages") or self.settings.default_pages)
        since = self.since or (date.today() - timedelta(days=self.settings.default_days))
        out: list[RawListing] = []
        for page_no in range(1, max_pages + 1):
            url = list_url.replace("{page}", str(page_no))
            html = self._render(url, a.get("wait_for") or a.get("row_selector"))
            listings, oldest = parse_list_html(html, url, a, self.cfg, since)
            if not listings and oldest is None:
                break
            for l in listings:
                l.extra["list_url"] = url   # 클릭 방식 상세는 이 페이지를 다시 열어 제목을 누른다
            out.extend(listings)
            if "{page}" not in list_url or (oldest and oldest < since):
                break
        return out

    def _render_click(self, listing: RawListing, d: dict) -> tuple[str, str]:
        """목록에서 이 공고의 제목을 클릭하고, (상세 HTML, 그때의 주소) 를 돌려준다.

        상세가 URL 없이 자바스크립트로만 열리는 게시판용
        (ASP.NET __doPostBack, fn_View 같은 onclick).
        """
        list_url = listing.extra.get("list_url") or self.a["list_url"].replace("{page}", "1")
        self.http.check_allowed(list_url)
        self.http.throttle(list_url)
        page = self._page()
        try:
            timeout_ms = int(self.settings.request_timeout_sec * 1000)
            # 클릭 뒤에는 폼 전체를 다시 올리는 게시판이 있다 (신라대는 뷰스테이트가 1.6MB).
            # 목록을 받는 시간과 상세가 열리는 시간은 자릿수가 달라서 따로 잡는다
            detail_ms = int(float(d.get("timeout_sec") or max(self.settings.request_timeout_sec, 60)) * 1000)
            page.goto(list_url, wait_until="commit", timeout=timeout_ms)
            page.wait_for_selector(self.a.get("row_selector") or "table", timeout=timeout_ms)
            # __doPostBack 은 스크립트가 다 올라와야 동작한다. 행만 보고 바로 누르면 아무 일도 안 일어난다
            try:
                page.wait_for_load_state("load", timeout=timeout_ms)
            except Exception:  # noqa: BLE001
                pass
            page.wait_for_timeout(300)
            # 제목이 같은 링크를 행 안에서 찾는다. 제목은 목록에서 읽은 그대로라 정확히 일치한다
            scope = page.locator(self.a.get("row_selector") or "tr").filter(has_text=listing.title)
            link = scope.locator(d.get("click_selector") or self.a.get("title_selector") or "a").first
            if link.count() == 0:
                link = page.get_by_text(listing.title, exact=True).first
            link.click(timeout=timeout_ms)
            # 먼저 통신이 끝나기를 기다린다. 상세 칸이 목록에도 (빈 채로) 있는 게시판이 많아서,
            # 이걸 건너뛰고 셀렉터만 보면 클릭 전 빈 칸을 본문으로 잡을 수 있다
            try:
                page.wait_for_load_state("networkidle", timeout=detail_ms)
            except Exception:  # noqa: BLE001
                pass
            wait_for = d.get("wait_for") or d.get("body_selector")
            if wait_for:
                # 화면에 보이는지(visible)까지 따지지 않는다. 우리는 DOM 만 읽고,
                # 접힌 채로 그려 두는 게시판에서 괜히 실패한다
                page.wait_for_selector(wait_for, timeout=detail_ms, state="attached")
            page.wait_for_timeout(500)
            return page.content(), page.url
        except Exception as e:  # noqa: BLE001
            raise FetchError(f"클릭 상세 실패 {listing.title[:30]}: {str(e)[:150]}") from e
        finally:
            page.context.close()

    def fetch_detail(self, listing: RawListing) -> RawPosting:
        d = self.a.get("detail") or {}
        if d.get("fetch") is False:
            return super().fetch_detail(listing)
        opened_url = None
        if d.get("click"):
            html, opened_url = self._render_click(listing, d)
        elif d.get("render", True):
            html = self._render(listing.url, d.get("wait_for") or d.get("body_selector"))
        else:
            from .html_list import decode_html
            html = decode_html(self.http.get(listing.url), d.get("encoding"))
        data = listing.model_dump()
        if d.get("url_from_page") and opened_url and opened_url != data["url"]:
            # 목록에 글 번호가 없는 게시판(창신대·김해대)은 목록 단계의 주소가 임시값이다.
            # 클릭해서 열린 진짜 주소로 바꿔야 중복 판정과 리포트 링크가 맞는다
            data["url"] = opened_url
        body = extract_body_html(html, d.get("body_selector") or "body")
        attachments = extract_attachments_html(html, data["url"], d.get("attachment_selector"))
        return RawPosting(**data, body_text=body, attachments=attachments, fetched_at=datetime.now(KST))
