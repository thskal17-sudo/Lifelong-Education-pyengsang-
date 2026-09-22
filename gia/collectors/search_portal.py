"""검색어 기반 포털 어댑터 (docs/DESIGN.md 5.2 search_portal).

query_url_template 의 {query} 에 queries 를 차례로 넣어 html_list 와 같은 셀렉터로 파싱한다.
민간 채용 포털은 약관(tos_checked) 확인 후에만 enabled=true 로 바꾼다.
"""
from __future__ import annotations

from datetime import date, timedelta
from urllib.parse import quote

from ..models import RawListing
from .html_list import HtmlListAdapter, decode_html, parse_list_html


class SearchPortalAdapter(HtmlListAdapter):
    type_name = "search_portal"

    def fetch_list(self) -> list[RawListing]:
        a = self.a
        tpl: str = a["query_url_template"]
        queries: list[str] = [str(q) for q in (a.get("queries") or [])]
        if not queries:
            return []
        max_pages = int((a.get("paging") or {}).get("max_pages") or 1)
        since = self.since or (date.today() - timedelta(days=self.settings.default_days))
        seen: set[str] = set()
        out: list[RawListing] = []
        for q in queries:
            for page in range(1, max_pages + 1):
                url = tpl.replace("{query}", quote(q)).replace("{page}", str(page))
                r = self.http.get(url)
                listings, oldest = parse_list_html(decode_html(r, a.get("encoding")), url, a, self.cfg, since)
                fresh = [l for l in listings if l.url not in seen]
                for l in fresh:
                    seen.add(l.url)
                    l.extra["query"] = q
                out.extend(fresh)
                if not listings or "{page}" not in tpl or (oldest and oldest < since):
                    break
        return out
