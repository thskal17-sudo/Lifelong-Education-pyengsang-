#!/usr/bin/env python3
"""게시판 목록/상세 페이지의 HTML 구조를 요약 출력한다 (셀렉터 결정용).

사용법: python scripts/dump_structure.py URL [URL ...]   (인자가 없으면 환경변수 URLS 를 공백으로 나눠 사용)
URL 에 amode=view / View.do / Detail.do / regSn= 이 있으면 상세 페이지로 보고 본문·첨부 후보를 출력한다.
네트워크가 열린 환경(GitHub Actions 등)에서 실행하고 로그를 읽는다.
"""
from __future__ import annotations

import os
import re
import sys

import requests
import urllib3
from bs4 import BeautifulSoup

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-User": "?1",
    "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
}
NOISE = re.compile(r"(?<![a-z])(nav|menu|header|footer|lnb|gnb|tnb|snb|anb|topmenu|depth|sitemap|quick|util|breadcrumb|location|family|skip|m_menu|slide|banner|share|foot|head)(?![a-z0-9])", re.I)
DETAIL = re.compile(r"(amode=view|(?<!sub)View\.do|Detail\.do|regSn=|/view\.|nttNo=|dataSid=|wr_id=|pan=read|List2Content|NttInfo|artclView|/boardview/|/lectopen/view/|bMode=view|btype=view|mode=READ|mod=document|_view\.asp|/view/)", re.I)


def sel(tag) -> str:
    cls = ".".join(tag.get("class", [])) if tag.get("class") else ""
    i = f"#{tag.get('id')}" if tag.get("id") else ""
    return f"{tag.name}{i}{'.' + cls if cls else ''}"


def path(tag) -> str:
    parts = []
    while tag is not None and tag.name not in ("body", "[document]"):
        parts.append(sel(tag))
        tag = tag.parent
    return " > ".join(reversed(parts))


def short_path(tag) -> str:
    """잡음 없는 짧은 경로: 마지막 3단계."""
    return " > ".join(path(tag).split(" > ")[-3:])


class LegacyTLSAdapter(requests.adapters.HTTPAdapter):
    """TLS 1.0/1.1·약한 암호만 지원하는 구형 서버용 (ice.cs.ac.kr 등)."""

    def init_poolmanager(self, *args, **kwargs):
        import ssl
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            ctx.minimum_version = ssl.TLSVersion.TLSv1
        ctx.set_ciphers("DEFAULT:@SECLEVEL=0")
        ctx.options |= getattr(ssl, "OP_LEGACY_SERVER_CONNECT", 0x4)
        kwargs["ssl_context"] = ctx
        return super().init_poolmanager(*args, **kwargs)


def fetch(url: str):
    from urllib.parse import urlsplit
    u = urlsplit(url)
    headers = dict(HEADERS, Referer=f"{u.scheme}://{u.netloc}/")
    sess = requests.Session()
    for attempt in (1, 2):
        try:
            return sess.get(url, headers=headers, timeout=25)
        except requests.exceptions.SSLError as exc:
            msg = str(exc)
            if "HANDSHAKE_FAILURE" in msg or "handshake" in msg.lower() or "DH_KEY_TOO_SMALL" in msg or "dh key too small" in msg.lower():
                print("  (tls handshake failed, retrying with legacy TLS context)")
                sess.mount("https://", LegacyTLSAdapter())
                return sess.get(url, headers=headers, timeout=25, verify=False)
            print("  (ssl verify failed, retrying without verification)")
            try:
                return sess.get(url, headers=headers, timeout=25, verify=False)
            except requests.exceptions.SSLError as exc2:
                # 검증을 꺼도 안 열리면 암호·프로토콜 문제 → 구형 TLS 컨텍스트로 한 번 더
                print(f"  (still failing without verification: {str(exc2)[:80]}; retrying with legacy TLS context)")
                sess.mount("https://", LegacyTLSAdapter())
                return sess.get(url, headers=headers, timeout=25, verify=False)
        except (requests.exceptions.ConnectTimeout, requests.exceptions.ConnectionError) as exc:
            if attempt == 2:
                raise
            print(f"  (connect failed, retrying once: {str(exc)[:80]})")


def row_detail(row, limit: int = 14) -> None:
    """행 내부의 클래스/태그가 있는 요소를 얕은 순서로 출력 (제목·날짜·부서 위치 파악용)."""
    n = 0
    for el in row.find_all(True):
        if el.name in ("br", "img", "script", "style"):
            continue
        txt = el.get_text(" ", strip=True)
        own = "".join(el.find_all(string=True, recursive=False)).strip()
        if not txt:
            continue
        extra = ""
        if el.name == "a":
            extra = f" href={ (el.get('href') or '')[:90] } onclick={ (el.get('onclick') or '')[:60] }"
            data = {k: v for k, v in el.attrs.items() if k not in ("href", "onclick", "class", "title")}
            if data:
                extra += f" attrs={ {k: str(v)[:40] for k, v in list(data.items())[:5]} }"
        print(f"      {sel(el)}{extra} :: own={own[:40]!r} all={txt[:50]!r}")
        n += 1
        if n >= limit:
            break


def dump_list(soup, noise=None) -> None:
    noise = NOISE if noise is None else noise
    found = 0
    for t in soup.find_all("table"):
        rows = t.find_all("tr")
        if len(rows) < 2 or noise.search(path(t)):
            continue
        found += 1
        print(f"\n[TABLE] {short_path(t)}  rows={len(rows)}")
        for tr in rows[:2]:
            cells = tr.find_all(["th", "td"])
            print("   row:", sel(tr), "->", " | ".join(f"{sel(c)}:{c.get_text(' ', strip=True)[:26]}" for c in cells[:8]))
        if len(rows) > 1:
            row_detail(rows[1])
    for ul in soup.find_all(["ul", "ol"]):
        lis = ul.find_all("li", recursive=False)
        if len(lis) < 3 or not ul.find("a") or noise.search(path(ul)):
            continue
        if sum(len(li.get_text(" ", strip=True)) for li in lis) < 80:
            continue
        found += 1
        print(f"\n[LIST] {short_path(ul)}  items={len(lis)}")
        print("   li:", sel(lis[0]), "->", lis[0].get_text(" ", strip=True)[:100])
        row_detail(lis[0])
    pag = [a for a in soup.find_all("a") if re.search(r"(cpage|pageIndex|startPage|pageNo|page)=\d+", a.get("href") or "")]
    if pag:
        print("\n[PAGING]", (pag[0].get("href") or "")[:140])
    print("[DATES] sample:", re.findall(r"20\d{2}[.\-/]\s?\d{1,2}[.\-/]\s?\d{1,2}", soup.get_text(" "))[:5])
    if not found and noise is NOISE:
        print("\n[RETRY without noise filter]")
        dump_list(soup, noise=re.compile(r"(?!x)x"))
        return
    dump_anchor_paths(soup)


def dump_anchor_paths(soup) -> None:
    """제목 길이의 앵커를 경로별로 묶어 가장 흔한 경로를 출력 (표/목록으로 안 잡히는 게시판용)."""
    from collections import Counter, defaultdict
    groups: dict[str, list] = defaultdict(list)
    for a in soup.find_all("a"):
        text = a.get_text(" ", strip=True)
        if len(text) < 10 or NOISE.search(path(a)):
            continue
        groups[" > ".join(path(a).split(" > ")[-4:])].append(a)
    top = Counter({k: len(v) for k, v in groups.items()}).most_common(4)
    if not top:
        return
    print("\n[ANCHORS] most common link paths")
    for key, n in top:
        a = groups[key][0]
        data = {k: str(v)[:40] for k, v in a.attrs.items() if k not in ("href", "class")}
        print(f"   x{n} {key}  href={(a.get('href') or '')[:90]} {data if data else ''} text={a.get_text(' ', strip=True)[:40]!r}")
        row = a
        for _ in range(4):
            row = row.parent
            if row is None or row.name in ("body", "[document]"):
                break
            if row.name in ("tr", "li") or (row.name == "div" and len(row.find_all("a")) <= 3):
                print(f"      row? {sel(row)} :: {row.get_text(' ', strip=True)[:120]!r}")
                break


def dump_detail(soup) -> None:
    cands = []
    for el in soup.find_all(["div", "td", "article", "section", "pre", "p"]):
        if NOISE.search(path(el)) or el.find(["table", "ul"]) and el.name == "div" and len(el.find_all("a")) > 15:
            continue
        txt = el.get_text(" ", strip=True)
        if len(txt) < 120:
            continue
        # 자식 중 더 큰 텍스트 컨테이너가 있으면 그쪽을 우선하도록 (가장 안쪽 큰 블록)
        inner = max((len(c.get_text(' ', strip=True)) for c in el.find_all(["div", "td", "article", "section"], recursive=False)), default=0)
        cands.append((len(txt) - inner * 0.9, len(txt), el))
    cands.sort(key=lambda x: -x[0])
    print("\n[BODY candidates]")
    for _, ln, el in cands[:5]:
        print(f"   {short_path(el)}  textlen={ln} :: {el.get_text(' ', strip=True)[:80]!r}")
    print("\n[ATTACH candidates]")
    for a in soup.find_all("a"):
        h = a.get("href") or ""
        oc = a.get("onclick") or ""
        if re.search(r"(download|file|attach|\.hwp|\.pdf|\.hwpx|\.docx)", h + oc, re.I):
            print(f"   {short_path(a)} href={h[:100]} onclick={oc[:60]} text={a.get_text(' ', strip=True)[:40]!r}")
    print("[DATES] sample:", re.findall(r"20\d{2}[.\-/]\s?\d{1,2}[.\-/]\s?\d{1,2}", soup.get_text(" "))[:8])


def dump(url: str) -> None:
    print("=" * 100)
    print("URL:", url)
    try:
        r = fetch(url)
    except Exception as exc:  # noqa: BLE001
        print("  FETCH ERROR:", str(exc)[:200])
        return
    if not r.encoding or r.encoding.lower() == "iso-8859-1":
        r.encoding = r.apparent_encoding
    print(f"status={r.status_code} final={r.url} encoding={r.encoding} bytes={len(r.content)}")
    soup = BeautifulSoup(r.text, "lxml")
    print("title:", (soup.title.get_text(strip=True) if soup.title else "")[:80])
    if len(r.content) < 2000:
        print("body (short):", re.sub(r"\s+", " ", r.text)[:600])
        return
    sel_env = os.environ.get("BODY_SELECTOR")
    if sel_env:
        for node in soup.select(sel_env)[:3]:
            print(f"\n[BODY TEXT] {short_path(node)}")
            print(node.get_text("\n", strip=True)[:3000])
    if DETAIL.search(url):
        dump_detail(soup)
    else:
        dump_list(soup)
        dump_links(soup, r.url)


LINK_WORDS = re.compile(r"(공지|알림|소식|채용|모집|구인|강사|게시판|공고|notice|recruit|job)", re.I)


def dump_links(soup, base: str) -> None:
    """홈페이지에서 게시판 후보 링크를 찾는다 (공지·채용·모집 등 낱말이 든 앵커)."""
    from urllib.parse import urljoin
    seen, out = set(), []
    for a in soup.find_all("a"):
        text = a.get_text(" ", strip=True)
        href = a.get("href") or ""
        if not LINK_WORDS.search(text + " " + href) or href.startswith(("#", "javascript", "mailto")):
            continue
        full = urljoin(base, href)
        if full in seen:
            continue
        seen.add(full)
        out.append(f"   {text[:30]!r} -> {full[:120]}")
    if out:
        print(f"\n[LINKS] board candidates ({len(out)})")
        print("\n".join(out[:40]))


if __name__ == "__main__":
    for u in sys.argv[1:] or os.environ.get("URLS", "").split():
        dump(u)
