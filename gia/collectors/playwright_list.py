"""JS 렌더링 게시판 어댑터 (docs/DESIGN.md 5.2 playwright). html_list와 같은 셀렉터 설정을 쓴다."""
from __future__ import annotations

import glob
import os
from datetime import date, datetime, timedelta

from ..extract.deadline import KST
from ..models import RawListing, RawPosting
from .base import FetchError, SourceAdapter
from .html_list import extract_attachments_html, extract_body_html, parse_list_html


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
        ctx = self._browser.new_context(user_agent=self.settings.user_agent, locale="ko-KR")
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
            timeout_ms = int(self.settings.request_timeout_sec * 1000)
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
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
            out.extend(listings)
            if "{page}" not in list_url or (oldest and oldest < since):
                break
        return out

    def fetch_detail(self, listing: RawListing) -> RawPosting:
        d = self.a.get("detail") or {}
        if d.get("fetch") is False:
            return super().fetch_detail(listing)
        if d.get("render", True):
            html = self._render(listing.url, d.get("wait_for") or d.get("body_selector"))
        else:
            from .html_list import decode_html
            html = decode_html(self.http.get(listing.url), d.get("encoding"))
        body = extract_body_html(html, d.get("body_selector") or "body")
        attachments = extract_attachments_html(html, listing.url, d.get("attachment_selector"))
        return RawPosting(**listing.model_dump(), body_text=body, attachments=attachments, fetched_at=datetime.now(KST))
