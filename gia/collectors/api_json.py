"""범용 JSON/XML API 어댑터 (docs/DESIGN.md 5.2 api_json)."""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from typing import Any

import httpx

from ..config import resolve_env
from ..extract.deadline import KST
from ..models import RawListing, RawPosting
from ..normalize import GYEONGNAM_WORDS, SIGUN
from .base import FetchError, SourceAdapter, get_path, matches_keywords, parse_date_loose, substitute_placeholders

REGION_ALIASES = {"@gyeongnam": GYEONGNAM_WORDS + SIGUN}


class ApiJsonAdapter(SourceAdapter):
    type_name = "api_json"

    def fetch_list(self) -> list[RawListing]:
        today = date.today()
        since = self.since or (today - timedelta(days=self.settings.default_days))
        a = substitute_placeholders(resolve_env(self.a), today, since)
        endpoint = a["endpoint"]
        params = dict(a.get("params") or {})
        fmt = (a.get("format") or "json").lower()
        paging = a.get("paging") or {}
        max_pages = int(paging.get("max_pages") or self.settings.default_pages)
        page_param = paging.get("page_param")
        size_param = paging.get("size_param")
        size = int(paging.get("size") or 100)
        start_page = int(paging.get("start_page") or 1)

        items: list[Any] = []
        for page in range(start_page, start_page + max_pages):
            p = dict(params)
            if page_param:
                p[page_param] = page
            if size_param:
                p[size_param] = size
            r = self.http.get(endpoint, params=p)
            data = self._parse(r, fmt)
            page_items = get_path(data, a.get("items_path"))
            if isinstance(page_items, dict):
                page_items = [page_items]
            if not page_items:
                break
            items.extend(page_items)
            if not page_param or len(page_items) < size:
                break

        out: list[RawListing] = []
        for it in items:
            if not isinstance(it, dict):
                continue
            listing = self._to_listing(it, a)
            if listing and self._passes(listing, a, since):
                out.append(listing)
        return out

    def fetch_detail(self, listing: RawListing) -> RawPosting:
        d = self.a.get("detail") or {}
        body = str(listing.extra.get("body_text") or "")
        if d.get("fetch") and listing.url:
            from .html_list import extract_body  # 지연 import (순환 방지)
            r = self.http.get(listing.url)
            body = extract_body(r, d.get("body_selector") or "body", d.get("encoding")) or body
        return RawPosting(**listing.model_dump(), body_text=body, fetched_at=datetime.now(KST))

    # ---- internals -----------------------------------------------------
    @staticmethod
    def _parse(r: httpx.Response, fmt: str) -> Any:
        text = r.text
        if fmt == "xml":
            try:
                root = ET.fromstring(text)
            except ET.ParseError as e:
                raise FetchError(f"XML 파싱 실패: {e}") from e
            return {root.tag: xml_to_obj(root)}
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            raise FetchError(f"JSON 파싱 실패: {e}; 응답 앞부분: {text[:120]!r}") from e

    def _to_listing(self, it: dict, a: dict) -> RawListing | None:
        fm = a.get("field_map") or {}

        def f(key: str) -> str:
            path = fm.get(key)
            return _s(get_path(it, path)) if path else ""

        title = f("title")
        if not title:
            return None
        url = f("url")
        if not url and fm.get("url_template"):
            url = _format_template(fm["url_template"], it)
        if not url:
            url = self.cfg.homepage or ""
        formats = a.get("date_formats") or []
        posted = parse_date_loose(get_path(it, fm["posted_at"]), formats) if fm.get("posted_at") else None
        deadline_text = f("deadline")
        region_text = f("region")
        org = f("org_name") or (None if self.cfg.org_type.value == "portal" else self.cfg.name)
        extra = {"raw": it}
        body = f("body")
        if body:
            extra["body_text"] = body
        return RawListing(
            source_id=self.cfg.id, title=title, url=url, org_name=org, posted_at=posted,
            deadline_text=deadline_text or None, region_text=region_text or None, extra=extra,
        )

    def _passes(self, l: RawListing, a: dict, since: date) -> bool:
        blob = " ".join([l.title, str(l.extra.get("body_text", ""))])
        if not matches_keywords(blob, a.get("keywords")):
            return False
        rf = a.get("region_filter")
        if isinstance(rf, str):
            rf = REGION_ALIASES.get(rf, [rf])
        if rf and l.region_text and not any(w in l.region_text for w in rf):
            return False
        if l.posted_at and l.posted_at < since:
            return False
        return True


def xml_to_obj(el: ET.Element) -> Any:
    children = list(el)
    if not children:
        return (el.text or "").strip()
    out: dict[str, Any] = {}
    for c in children:
        v = xml_to_obj(c)
        if c.tag in out:
            if not isinstance(out[c.tag], list):
                out[c.tag] = [out[c.tag]]
            out[c.tag].append(v)
        else:
            out[c.tag] = v
    return out


def _s(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, (list, dict)):
        return json.dumps(v, ensure_ascii=False)
    return str(v).strip()


class _SafeDict(dict):
    def __missing__(self, key: str) -> str:
        return ""


def _format_template(tpl: str, it: dict) -> str:
    return tpl.format_map(_SafeDict({k: v for k, v in it.items() if not isinstance(v, (dict, list))}))
