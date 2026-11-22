from __future__ import annotations

from datetime import date
from urllib.parse import urlsplit

from ..config import CollectorSettings, SourceConfig
from .api_json import ApiJsonAdapter
from .base import HttpClient, SourceAdapter, UnconfiguredSource
from .html_list import HtmlListAdapter
from .playwright_list import PlaywrightListAdapter
from .search_portal import SearchPortalAdapter

ADAPTERS: dict[str, type[SourceAdapter]] = {
    "api_json": ApiJsonAdapter,
    "html_list": HtmlListAdapter,
    "playwright": PlaywrightListAdapter,
    "search_portal": SearchPortalAdapter,
}


def build_adapter(cfg: SourceConfig, http: HttpClient, settings: CollectorSettings, since: date | None = None) -> SourceAdapter:
    reason = cfg.unconfigured_reason()
    if reason:
        raise UnconfiguredSource(reason)
    kind = cfg.adapter.get("type")
    cls = ADAPTERS.get(kind)
    if cls is None:
        raise UnconfiguredSource(f"지원하지 않는 adapter.type: {kind} (지원: api_json, html_list, playwright, search_portal)")
    if cfg.adapter.get("tls_legacy") is True:
        for host in insecure_hosts(cfg):
            http.set_tls_mode(host, "legacy")
    elif cfg.adapter.get("tls_verify") is False:
        for host in insecure_hosts(cfg):
            http.set_tls_mode(host, "insecure")
    if cfg.adapter.get("timeout_sec") or cfg.adapter.get("retries"):
        # 브라우저 수집기(playwright)는 adapter.timeout_sec 을 따로 읽는다. 여기는 HTTP 수집기용
        for host in insecure_hosts(cfg):  # 이름과 달리 소스의 URL 호스트 전부를 모은다
            http.set_host_policy(host, cfg.adapter.get("timeout_sec"), cfg.adapter.get("retries"))
    return cls(cfg, http, settings, since=since)


def insecure_hosts(cfg: SourceConfig) -> list[str]:
    """adapter.tls_verify: false / tls_legacy: true 인 소스의 URL 값(list_url, endpoint, link_url_template 등)에서 호스트를 모은다."""
    hosts: list[str] = []
    for v in cfg.adapter.values():
        if isinstance(v, str) and v.startswith("http"):
            host = urlsplit(v).netloc.lower()
            if host and host not in hosts:
                hosts.append(host)
    return hosts
