"""범용 HTML 게시판 어댑터 (docs/DESIGN.md 5.2 html_list)."""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from urllib.parse import urljoin

import httpx
from selectolax.parser import HTMLParser

from ..extract.deadline import KST
from ..models import RawListing, RawPosting
from .base import SourceAdapter, matches_keywords, parse_date_loose

_META_CHARSET = re.compile(rb"charset=[\"']?([\w\-]+)", re.I)


def decode_html(r: httpx.Response, encoding: str | None = None) -> str:
    enc = encoding
    if not enc:
        m = _META_CHARSET.search(r.content[:4096])
        if m:
            enc = m.group(1).decode("ascii", "ignore")
    if not enc:
        enc = r.encoding or "utf-8"
    try:
        return r.content.decode(enc, errors="replace")
    except LookupError:
        return r.content.decode("utf-8", errors="replace")


def extract_body(r: httpx.Response, selector: str, encoding: str | None = None) -> str:
    return extract_body_html(decode_html(r, encoding), selector)


def resolve_link(node, page_url: str, a: dict) -> str | None:
    """href 또는 onclick에서 상세 URL을 만든다.

    - link_attr: 읽을 속성 (기본 href, 없으면 onclick)
    - link_regex: 속성값에서 식별자를 뽑는 정규식 (그룹 사용)
    - link_url_template: "{1}" 같은 그룹 자리표시자를 채울 URL 템플릿
    """
    if node is None:
        return None
    attrs = node.attributes
    value = attrs.get(a.get("link_attr") or "href") or attrs.get("onclick") or attrs.get("href") or ""
    regex = a.get("link_regex")
    if regex:
        m = re.search(regex, value)
        if not m:
            return None
        tpl = a.get("link_url_template")
        if tpl:
            return tpl.format(m.group(0), *m.groups())
        return urljoin(page_url, m.group(1) if m.groups() else m.group(0))
    if not value or value.startswith(("javascript:", "#")):
        return None
    return urljoin(page_url, value)


def synthetic_link(row, a: dict) -> str | None:
    """상세 URL 이 없는 게시판에서 행의 고유 번호로 링크를 만든다.

    - id_selector: 번호가 들어 있는 셀 (예: 목록 첫 칸의 글 번호)
    - id_regex: 그 텍스트에서 번호를 뽑는 정규식 (기본: 숫자)
    - link_url_template: "{1}" 에 번호를 채울 URL 틀
    """
    node = row.css_first(a["id_selector"])
    if node is None:
        return None
    m = re.search(a.get("id_regex") or r"(\d+)", node.text(strip=True))
    tpl = a.get("link_url_template")
    if not m or not tpl:
        return None
    return tpl.format(m.group(0), *m.groups())


def parse_list_html(html: str, page_url: str, a: dict, cfg, since: date) -> tuple[list[RawListing], date | None]:
    """목록 HTML에서 공고 후보를 뽑는다. 반환: (목록, 페이지 내 가장 오래된 게시일)."""
    tree = HTMLParser(html)
    rows = tree.css(a["row_selector"])
    out: list[RawListing] = []
    oldest_on_page: date | None = None
    for row in rows:
        t = row.css_first(a.get("title_selector") or "a")
        if t is None:
            continue
        title = (t.attributes.get(a["title_attr"]) if a.get("title_attr") else None) or t.text(strip=True)
        if a.get("id_selector"):
            # 상세가 URL 이 아니라 자바스크립트로 열리는 게시판: 행의 고유 번호로 합성 URL 을 만든다.
            # (번호는 글마다 고정이라 재수집해도 같은 공고로 이어진다)
            target = synthetic_link(row, a)
        else:
            link = row.css_first(a.get("link_selector") or a.get("title_selector") or "a")
            if link is None or (a.get("link_attr") and not link.attributes.get(a["link_attr"])):
                # 행(tr·li) 자체에 onclick 이 걸린 게시판 (부산외대 평생교육원 등)
                link = row if row.attributes.get(a.get("link_attr") or "onclick") else link
            target = resolve_link(link, page_url, a)
        if not title or not target:
            continue
        posted = None
        if a.get("date_selector"):
            dn = row.css_first(a["date_selector"])
            posted = parse_date_loose(dn.text(strip=True) if dn is not None else None, a.get("date_formats"))
            if posted and (oldest_on_page is None or posted < oldest_on_page):
                oldest_on_page = posted
        org = None
        if a.get("org_selector"):
            on = row.css_first(a["org_selector"])
            org = on.text(strip=True) if on is not None else None
        if org is None and cfg.org_type.value != "portal":
            org = a.get("org_name") or cfg.name  # adapter.org_name: 게시판 이름 대신 쓸 기관명
        if not matches_keywords(title, a.get("keywords")):
            continue
        if posted and posted < since:
            continue
        out.append(RawListing(source_id=cfg.id, title=title, url=target, org_name=org, posted_at=posted))
    return out, oldest_on_page


def extract_body_html(html: str, selector: str) -> str:
    tree = HTMLParser(html)
    for tag in ("script", "style", "noscript"):
        for n in tree.css(tag):
            n.decompose()
    node = tree.css_first(selector) or tree.body
    if node is None:
        return ""
    text = node.text(separator="\n", strip=True)
    return re.sub(r"\n{3,}", "\n\n", text)[:20000]


def extract_attachments_html(html: str, page_url: str, selector: str | None) -> list[str]:
    if not selector:
        return []
    tree = HTMLParser(html)
    out: list[str] = []
    for n in tree.css(selector):
        href = n.attributes.get("href")
        if href:
            out.append(urljoin(page_url, href))
    return out


class HtmlListAdapter(SourceAdapter):
    type_name = "html_list"

    def fetch_list(self) -> list[RawListing]:
        a = self.a
        list_url: str = a["list_url"]
        max_pages = int((a.get("paging") or {}).get("max_pages") or self.settings.default_pages)
        since = self.since or (date.today() - timedelta(days=self.settings.default_days))
        out: list[RawListing] = []
        for page in range(1, max_pages + 1):
            url = list_url.replace("{page}", str(page))
            r = self.http.get(url)
            listings, oldest = parse_list_html(decode_html(r, a.get("encoding")), url, a, self.cfg, since)
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
        r = self.http.get(listing.url)
        html = decode_html(r, d.get("encoding") or self.a.get("encoding"))
        body = extract_body_html(html, d.get("body_selector") or "body")
        attachments = extract_attachments_html(html, listing.url, d.get("attachment_selector"))
        return RawPosting(**listing.model_dump(), body_text=body, attachments=attachments, fetched_at=datetime.now(KST))
