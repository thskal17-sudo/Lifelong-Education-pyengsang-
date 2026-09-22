"""어댑터 인터페이스와 HTTP 클라이언트 (docs/DESIGN.md 5절)."""
from __future__ import annotations

import logging
import random
import re
import ssl
import threading
import time
import warnings
from datetime import date, datetime
from typing import Any
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from ..config import CollectorSettings, SourceConfig
from ..extract.deadline import KST
from ..models import RawListing, RawPosting


log = logging.getLogger("gia.http")


class FetchError(Exception):
    pass


class UnconfiguredSource(Exception):
    pass


class HttpClient:
    """도메인별 요청 간격, 재시도, robots.txt 확인을 담당한다."""

    def __init__(self, settings: CollectorSettings, transport: httpx.BaseTransport | None = None):
        self.settings = settings
        self._transport = transport
        self._client = self._make_client(verify=True)
        # 호스트별 TLS 모드: "insecure"(tls_verify: false) / "legacy"(tls_legacy: true). 모드별 클라이언트는 지연 생성
        self._host_mode: dict[str, str] = {}
        self._mode_clients: dict[str, httpx.Client] = {}
        self._last: dict[str, float] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()
        self._robots: dict[str, RobotFileParser | None] = {}

    def _make_client(self, verify: "bool | ssl.SSLContext") -> httpx.Client:
        return httpx.Client(
            headers={"User-Agent": self.settings.user_agent, "Accept-Language": "ko,en;q=0.8"},
            timeout=self.settings.request_timeout_sec,
            follow_redirects=True,
            transport=self._transport,
            verify=verify,
        )

    @staticmethod
    def legacy_tls_context() -> ssl.SSLContext:
        """TLS 1.0/1.1·약한 암호(DH_KEY_TOO_SMALL 포함)만 지원하는 구형 서버용. 검증도 끈다 (scripts/dump_structure.py 와 동일)."""
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)  # TLSv1 지정 자체가 deprecated 경고를 냄
            ctx.minimum_version = ssl.TLSVersion.TLSv1
        ctx.set_ciphers("DEFAULT:@SECLEVEL=0")
        ctx.options |= getattr(ssl, "OP_LEGACY_SERVER_CONNECT", 0x4)
        return ctx

    def set_tls_mode(self, host: str, mode: str) -> None:
        """해당 호스트만 다른 TLS 설정을 쓴다. mode: "insecure"(인증서 검증 끔) / "legacy"(구형 TLS + 검증 끔)."""
        host = host.lower()
        if mode not in ("insecure", "legacy"):
            raise ValueError(f"알 수 없는 TLS 모드: {mode}")
        if self._host_mode.get(host) == mode:
            return
        self._host_mode[host] = mode
        if mode not in self._mode_clients:
            self._mode_clients[mode] = self._make_client(verify=False if mode == "insecure" else self.legacy_tls_context())
        log.warning("[http] %s: %s", host, "TLS 인증서 검증 비활성 (tls_verify: false)" if mode == "insecure" else "구형 TLS 허용·검증 비활성 (tls_legacy: true)")

    def allow_insecure_tls(self, host: str) -> None:
        """adapter.tls_verify: false — 중간 인증서 누락 등 서버 쪽 설정 문제용."""
        self.set_tls_mode(host, "insecure")

    def _client_for(self, url: str) -> httpx.Client:
        mode = self._host_mode.get(urlsplit(url).netloc.lower()) if self._host_mode else None
        return self._mode_clients[mode] if mode else self._client

    def close(self) -> None:
        self._client.close()
        for c in self._mode_clients.values():
            c.close()

    def get(self, url: str, params: dict | None = None, headers: dict | None = None) -> httpx.Response:
        host = urlsplit(url).netloc
        if self.settings.respect_robots and not self._allowed(url):
            raise FetchError(f"robots.txt 차단: {url}")
        with self._lock_for(host):
            self._wait(host)
            last_err: Exception | None = None
            for attempt in range(3):
                try:
                    r = self._client_for(url).get(url, params=params, headers=headers)
                except (httpx.TimeoutException, httpx.TransportError) as e:
                    last_err = e
                    time.sleep(2 ** attempt * 0.5 if self.settings.per_domain_delay_sec else 0)
                    continue
                if r.status_code >= 500:
                    last_err = FetchError(f"HTTP {r.status_code} {url}")
                    time.sleep(2 ** attempt * 0.5 if self.settings.per_domain_delay_sec else 0)
                    continue
                if r.status_code >= 400:
                    raise FetchError(f"HTTP {r.status_code} {url}")
                return r
            raise FetchError(f"재시도 실패: {last_err}")

    def download(self, url: str, max_bytes: int) -> tuple[bytes, str | None]:
        """첨부파일을 크기 상한까지 내려받는다. 반환: (bytes, Content-Disposition 파일명)."""
        host = urlsplit(url).netloc
        if self.settings.respect_robots and not self._allowed(url):
            raise FetchError(f"robots.txt 차단: {url}")
        with self._lock_for(host):
            self._wait(host)
            try:
                with self._client_for(url).stream("GET", url) as r:
                    if r.status_code >= 400:
                        raise FetchError(f"HTTP {r.status_code} {url}")
                    buf = bytearray()
                    for chunk in r.iter_bytes():
                        buf += chunk
                        if len(buf) > max_bytes:
                            raise FetchError(f"첨부 크기 초과(>{max_bytes // 1024 // 1024}MB): {url}")
                    return bytes(buf), filename_from_headers(r.headers)
            except (httpx.TimeoutException, httpx.TransportError) as e:
                raise FetchError(f"첨부 다운로드 실패: {e}") from e

    def post_json(self, url: str, payload: dict) -> httpx.Response:
        r = self._client_for(url).post(url, json=payload)
        if r.status_code >= 400:
            raise FetchError(f"HTTP {r.status_code} {url}: {r.text[:200]}")
        return r

    def check_allowed(self, url: str) -> None:
        """robots.txt 정책상 허용되지 않으면 FetchError."""
        if self.settings.respect_robots and not self._allowed(url):
            raise FetchError(f"robots.txt 차단: {url}")

    def throttle(self, url: str) -> None:
        """HTTP 클라이언트를 거치지 않는 요청(브라우저 렌더링)도 도메인별 간격을 지키게 한다."""
        host = urlsplit(url).netloc
        with self._lock_for(host):
            self._wait(host)

    def _lock_for(self, host: str) -> threading.Lock:
        with self._guard:
            if host not in self._locks:
                self._locks[host] = threading.Lock()
            return self._locks[host]

    def _wait(self, host: str) -> None:
        delay = self.settings.per_domain_delay_sec
        if delay <= 0:
            return
        last = self._last.get(host)
        if last is not None:
            gap = delay + random.uniform(-0.5, 0.5)
            remaining = max(0.0, gap) - (time.monotonic() - last)
            if remaining > 0:
                time.sleep(remaining)
        self._last[host] = time.monotonic()

    def _allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        base = f"{parts.scheme}://{parts.netloc}"
        with self._guard:
            cached = self._robots.get(base, "miss")
        if cached == "miss":
            rp: RobotFileParser | None = RobotFileParser()
            try:
                r = self._client_for(base).get(base + "/robots.txt")
                if r.status_code == 200:
                    rp.parse(r.text.splitlines())
                else:
                    rp = None
            except httpx.HTTPError:
                rp = None
            with self._guard:
                self._robots[base] = rp
            cached = rp
        if cached is None:
            return True
        return cached.can_fetch(self.settings.user_agent, url)


class SourceAdapter:
    type_name = "base"

    def __init__(self, cfg: SourceConfig, http: HttpClient, settings: CollectorSettings, since: date | None = None):
        self.cfg = cfg
        self.http = http
        self.settings = settings
        self.a: dict[str, Any] = cfg.adapter
        self.since = since

    def fetch_list(self) -> list[RawListing]:
        raise NotImplementedError

    def fetch_detail(self, listing: RawListing) -> RawPosting:
        return RawPosting(**listing.model_dump(), body_text=str(listing.extra.get("body_text", "")), fetched_at=datetime.now(KST))

    def close(self) -> None:
        """브라우저 등 자원을 정리한다."""


# ---- helpers ---------------------------------------------------------
_CD_EXT = re.compile(r"filename\*=(?:[\w-]+)''([^;]+)", re.I)
_CD_PLAIN = re.compile(r'filename="?([^";]+)"?', re.I)


def filename_from_headers(headers) -> str | None:
    cd = headers.get("content-disposition", "") if headers else ""
    if not cd:
        return None
    from urllib.parse import unquote
    m = _CD_EXT.search(cd)
    if m:
        return unquote(m.group(1)).strip()
    m = _CD_PLAIN.search(cd)
    if m:
        name = m.group(1).strip()
        try:
            return name.encode("latin-1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            return unquote(name)
    return None

def get_path(obj: Any, path: str | None) -> Any:
    if not path:
        return obj
    cur = obj
    for part in path.split("."):
        if cur is None:
            return None
        if isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError):
                return None
        elif isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


_DATE_FORMATS = ["%Y%m%d", "%Y-%m-%d", "%Y.%m.%d", "%Y/%m/%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y%m%d%H%M", "%y-%m-%d", "%Y.%m.%d."]
_DATE_LOOSE = re.compile(r"(\d{4})\s*[.\-/년]\s*(\d{1,2})\s*[.\-/월]\s*(\d{1,2})")


def parse_date_loose(value: Any, formats: list[str] | None = None) -> date | None:
    if value is None:
        return None
    v = str(value).strip()
    if not v:
        return None
    for fmt in (formats or []) + _DATE_FORMATS:
        try:
            return datetime.strptime(v, fmt).date()
        except ValueError:
            continue
    m = _DATE_LOOSE.search(v)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    return None


def matches_keywords(text: str, keywords: list[str] | None) -> bool:
    if not keywords:
        return True
    return any(k in text for k in keywords)


def substitute_placeholders(obj: Any, today: date, since: date) -> Any:
    """{today}, {since} (YYYYMMDD) 와 _dash / _dot 변형을 치환한다."""
    table = {
        "today": today.strftime("%Y%m%d"), "since": since.strftime("%Y%m%d"),
        "today_dash": today.isoformat(), "since_dash": since.isoformat(),
        "today_dot": today.strftime("%Y.%m.%d"), "since_dot": since.strftime("%Y.%m.%d"),
    }
    pat = re.compile(r"\{(today|since)(_dash|_dot)?\}")
    if isinstance(obj, str):
        return pat.sub(lambda m: table[m.group(1) + (m.group(2) or "")], obj)
    if isinstance(obj, dict):
        return {k: substitute_placeholders(v, today, since) for k, v in obj.items()}
    if isinstance(obj, list):
        return [substitute_placeholders(v, today, since) for v in obj]
    return obj
