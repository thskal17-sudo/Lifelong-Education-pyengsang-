"""GitHub Pages 아카이브 빌더 (docs/DESIGN.md F-12). 제목·요약·링크만 공개하고 본문은 싣지 않는다."""
from __future__ import annotations

import html
import json
import re
from datetime import datetime
from pathlib import Path

from .extract.deadline import KST
from .models import FIELD_NAMES, Posting, Status
from .stats import compute_stats

_FONT = (
    '<link rel="preconnect" href="https://cdn.jsdelivr.net">'
    '<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9'
    '/dist/web/variable/pretendardvariable-dynamic-subset.min.css">'
)

# 토스증권 리서치 리포트(Then And Now, 2026-06)의 디자인 언어를 참고했다:
# 위쪽 하늘색 그라데이션 표지, 큰 볼드 제목, 파란 강조색, 넉넉한 여백, 얇은 구분선.
# 폰트는 토스 전용체(Toss Product Sans)라 쓸 수 없어 형태가 가장 가까운 Pretendard 로 대체했다.
# 로고·기관명 등 토스 고유 표식은 쓰지 않는다.
_STYLE = """
:root{
  --blue:#3182f6; --blue-dark:#1b64da; --blue-soft:#e8f3ff;
  --ink:#191f28; --ink-2:#4e5968; --ink-3:#8b95a1;
  --bg:#ffffff; --bg-2:#f2f4f6; --line:#e5e8eb;
  --urgent:#f04452; --urgent-bg:#fff0f1;
  --wrap:1000px;
}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
  --blue:#4c9aff; --blue-dark:#8fc0ff; --blue-soft:#1b2734;
  --ink:#e8eaed; --ink-2:#b0b8c1; --ink-3:#8b95a1;
  --bg:#12161b; --bg-2:#1a1f26; --line:#2a313a;
  --urgent:#ff6b76; --urgent-bg:#2b1a1d;
}}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{
  margin:0;background:var(--bg);color:var(--ink);
  font-family:'Pretendard Variable',Pretendard,-apple-system,BlinkMacSystemFont,system-ui,
    'Apple SD Gothic Neo','Noto Sans KR','Malgun Gothic',sans-serif;
  font-size:16px;line-height:1.65;letter-spacing:-0.01em;
  -webkit-font-smoothing:antialiased;
}
.wrap{max-width:var(--wrap);margin:0 auto;padding:0 16px}
a{color:var(--blue-dark);text-decoration:none}
a:hover{text-decoration:underline}

/* ── 표지: 위는 옅게, 아래로 갈수록 파랗게. 가운데 아래 은은한 빛무리 ── */
.hero{position:relative;overflow:hidden;color:#0b2447;
  background:linear-gradient(180deg,#eaf5ff 0%,#dcefff 38%,#a9d4f7 78%,#7cbdf2 100%)}
.hero::after{content:"";position:absolute;left:50%;bottom:-38%;width:150%;aspect-ratio:2/1;
  transform:translateX(-50%);border-radius:50%;
  background:radial-gradient(ellipse at center,rgba(255,255,255,.85),rgba(255,255,255,0) 62%)}
.hero>.wrap{position:relative;z-index:1;padding-top:22px;padding-bottom:40px}
.meta{display:flex;flex-wrap:wrap;gap:8px 44px;
  border-top:1px solid rgba(11,36,71,.35);padding-top:14px;margin-bottom:56px}
.meta div{min-width:0}
.meta span{display:block;font-size:12px;font-weight:700;letter-spacing:0;opacity:.72}
.meta b{font-size:14px;font-weight:700}
.hero h1{margin:0;font-size:clamp(34px,7vw,60px);line-height:1.08;letter-spacing:-0.035em;
  font-weight:800;color:#fff;text-shadow:0 1px 2px rgba(11,36,71,.12)}
.hero .count{margin:14px 0 0;font-size:16px;font-weight:700;color:#0b2447;opacity:.8}

/* ── 탭 ── */
.tabs{position:sticky;top:0;z-index:5;background:var(--bg);border-bottom:1px solid var(--line)}
.tabs .wrap{display:flex;gap:4px}
.tabs a{padding:14px 12px;font-size:15px;font-weight:600;color:var(--ink-3);
  border-bottom:2px solid transparent;margin-bottom:-1px}
.tabs a:hover{color:var(--ink-2);text-decoration:none}
.tabs a.on{color:var(--blue);border-bottom-color:var(--blue)}

main{padding:28px 0 64px}
h1,h2,h3{letter-spacing:-0.03em;line-height:1.3}
main h1{font-size:28px;font-weight:800;margin:0 0 20px}
main h2{font-size:21px;font-weight:700;margin:40px 0 12px;padding-top:20px;border-top:1px solid var(--line)}
main h2:first-of-type{border-top:0;padding-top:0;margin-top:8px}
main h3{font-size:17px;font-weight:700;margin:24px 0 8px}
p{margin:0 0 14px}

/* ── 검색 ── */
.search{position:relative;margin:0 0 20px}
.search input{width:100%;padding:14px 16px;font:inherit;font-size:16px;color:var(--ink);
  background:var(--bg-2);border:1px solid transparent;border-radius:12px;outline:none}
.search input::placeholder{color:var(--ink-3)}
.search input:focus{border-color:var(--blue);background:var(--bg)}

/* ── 공고 목록 ── */
.list{display:flex;flex-direction:column;gap:10px}
.row{display:block;padding:18px 20px;background:var(--bg);border:1px solid var(--line);
  border-radius:14px;color:inherit;transition:border-color .12s,transform .12s}
.row:hover{border-color:var(--blue);text-decoration:none;transform:translateY(-1px)}
.row-top{display:flex;flex-wrap:wrap;align-items:center;gap:8px;font-size:13px;color:var(--ink-3)}
.pill{background:var(--blue-soft);color:var(--blue-dark);font-weight:700;font-size:12px;
  padding:3px 9px;border-radius:999px;letter-spacing:0}
.org{font-weight:600;color:var(--ink-2)}
.row-title{margin:8px 0 10px;font-size:18px;font-weight:700;line-height:1.45;
  letter-spacing:-0.02em;color:var(--ink)}
.row-sum{margin:-4px 0 10px;font-size:14px;color:var(--ink-2)}
.dl{display:inline-flex;align-items:center;gap:6px;font-size:13px;font-weight:600;color:var(--ink-2)}
.dl b{color:var(--ink);font-weight:700}
.dday{background:var(--bg-2);color:var(--ink-2);font-size:12px;font-weight:700;
  padding:2px 8px;border-radius:6px}
.dl.urgent b,.dl.urgent{color:var(--urgent)}
.dl.urgent .dday{background:var(--urgent-bg);color:var(--urgent)}
.empty{padding:56px 20px;text-align:center;color:var(--ink-3);background:var(--bg-2);border-radius:14px}

/* ── 표 (리포트·통계) ── */
table{border-collapse:collapse;width:100%;margin:8px 0 20px;font-size:15px}
th,td{border-bottom:1px solid var(--line);padding:11px 12px;text-align:left;vertical-align:top}
th{background:var(--bg-2);font-weight:700;font-size:13px;color:var(--ink-2);letter-spacing:0}
main ul{padding-left:20px;margin:0 0 16px}
main li{margin:6px 0}
blockquote{border-left:3px solid var(--blue);background:var(--bg-2);margin:0 0 16px;
  padding:10px 16px;border-radius:0 8px 8px 0;color:var(--ink-2)}
code{background:var(--bg-2);padding:1px 6px;border-radius:5px;font-size:.92em}
.archive{list-style:none;padding:0;display:grid;gap:8px;
  grid-template-columns:repeat(auto-fill,minmax(150px,1fr))}
.archive a{display:block;padding:14px 16px;background:var(--bg-2);border-radius:10px;
  font-weight:700;color:var(--ink)}
.archive a:hover{background:var(--blue-soft);color:var(--blue-dark);text-decoration:none}

footer{border-top:1px solid var(--line);padding:24px 0 48px;
  font-size:13px;color:var(--ink-3)}
@media(max-width:560px){
  .hero>.wrap{padding-bottom:32px}
  .meta{gap:6px 24px;margin-bottom:36px}
  .row{padding:16px}
  .row-title{font-size:17px}
}
"""


def public_record(p: Posting) -> dict:
    return {
        "id": p.id, "title": p.title, "org": p.org_name, "org_type": p.org_type.value, "field": p.field,
        "field_name": FIELD_NAMES.get(p.field, p.field), "region": p.region, "employment_type": p.employment_type,
        "deadline": p.deadline.astimezone(KST).isoformat() if p.deadline else None, "deadline_type": p.deadline_type.value,
        "summary": p.one_line_summary, "url": p.primary_url, "status": p.status.value,
        "first_seen": p.first_seen_at.astimezone(KST).date().isoformat(), "flags": [f for f in p.flags if f != "피드백제외"],
    }


def md_to_html(md: str) -> str:
    """리포트 Markdown 전용 최소 변환기: 제목, 표, 목록, 굵게, 링크, 인용, 문단."""
    out: list[str] = []
    in_table = False
    in_list = False
    for raw in md.splitlines():
        line = raw.rstrip()
        if in_table and not line.startswith("|"):
            out.append("</table>")
            in_table = False
        if in_list and line.startswith("   ") and line.strip() and out and out[-1].endswith("</li>"):
            out[-1] = out[-1][:-5] + "<br>" + _inline(line.strip()) + "</li>"
            continue
        if in_list and not re.match(r"^\s*(\d+\.|-)\s", line):
            out.append("</ul>")
            in_list = False
        if not line.strip():
            continue
        if line.startswith("|"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            if all(re.fullmatch(r":?-{2,}:?", c) for c in cells):
                continue
            if not in_table:
                out.append("<table>")
                in_table = True
                out.append("<tr>" + "".join(f"<th>{_inline(c)}</th>" for c in cells) + "</tr>")
            else:
                out.append("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in cells) + "</tr>")
            continue
        m = re.match(r"^(#{1,3})\s+(.*)", line)
        if m:
            out.append(f"<h{len(m.group(1))}>{_inline(m.group(2))}</h{len(m.group(1))}>")
            continue
        if line.startswith("> "):
            out.append(f"<blockquote>{_inline(line[2:])}</blockquote>")
            continue
        m = re.match(r"^\s*(?:\d+\.|-)\s+(.*)", line)
        if m:
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{_inline(m.group(1))}</li>")
            continue
        out.append(f"<p>{_inline(line)}</p>")
    if in_table:
        out.append("</table>")
    if in_list:
        out.append("</ul>")
    return "\n".join(out)


def _inline(s: str) -> str:
    s = html.escape(s, quote=False)
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"`(.+?)`", r"<code>\1</code>", s)
    s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', s)
    s = re.sub(r"(?<![\"'>])(https?://[^\s<)]+)", r'<a href="\1">\1</a>', s)
    return s


def _page(title: str, body: str, base: str = "./", active: str = "", hero: str = "") -> str:
    """공통 껍데기. base 는 하위 폴더(reports/)에서 ../ 로 넘긴다."""
    def tab(href: str, label: str, key: str) -> str:
        on = " class=\"on\"" if key == active else ""
        return f'<a href="{base}{href}"{on}>{label}</a>'

    tabs = tab("index.html", "활성 공고", "index") + tab("reports/index.html", "일일 리포트", "reports") \
        + tab("stats.html", "주간 통계", "stats")
    return f"""<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light dark">
<title>{html.escape(title)}</title>{_FONT}<style>{_STYLE}</style></head><body>
{hero}
<div class="tabs"><div class="wrap">{tabs}</div></div>
<main class="wrap">
{body}
</main>
<footer class="wrap">제목·요약·원문 링크만 게시합니다. 본문은 원문에서 확인하세요.</footer>
</body></html>"""


def _hero(meta: list[tuple[str, str]], title_html: str, count: str = "") -> str:
    cells = "".join(
        f"<div><span>{html.escape(k)}</span><b>{html.escape(v)}</b></div>" for k, v in meta
    )
    tail = f'<p class="count">{html.escape(count)}</p>' if count else ""
    return f'<header class="hero"><div class="wrap"><div class="meta">{cells}</div>' \
           f'<h1>{title_html}</h1>{tail}</div></header>'


def _dday(r: dict, now: datetime) -> str:
    """마감 표시. 3일 이내면 urgent 로 강조한다."""
    if r["deadline_type"] == "until_filled":
        return '<span class="dl">채용 시까지</span>'
    if not r["deadline"]:
        return '<span class="dl">마감 확인 필요</span>'
    dl = datetime.fromisoformat(r["deadline"])
    left = (dl.date() - now.astimezone(KST).date()).days
    tag = "D-DAY" if left == 0 else (f"D-{left}" if left > 0 else f"D+{-left}")
    cls = "dl urgent" if 0 <= left <= 3 else "dl"
    return f'<span class="{cls}">마감 <b>{dl:%Y-%m-%d %H:%M}</b><span class="dday">{tag}</span></span>'


def build_site(postings, reports_dir: Path, out_dir: Path, now: datetime) -> dict[str, int]:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "reports").mkdir(exist_ok=True)
    (out_dir / "data").mkdir(exist_ok=True)
    active = [p for p in postings if p.status != Status.expired and "피드백제외" not in p.flags]
    active.sort(key=lambda p: (p.deadline is None, p.deadline or now))
    records = [public_record(p) for p in active]
    (out_dir / "data" / "postings.json").write_text(json.dumps(records, ensure_ascii=False, indent=1), encoding="utf-8")

    cards = "".join(
        f'<a class="row" href="{html.escape(r["url"])}" target="_blank" rel="noopener">'
        f'<div class="row-top"><span class="pill">{html.escape(r["field_name"])}</span>'
        f'<span class="org">{html.escape(r["org"])}</span>'
        + (f'<span>· {html.escape(" · ".join(r["region"]))}</span>' if r["region"] else "")
        + f'</div><div class="row-title">{html.escape(r["title"])}</div>'
        + (f'<div class="row-sum">{html.escape(r["summary"])}</div>' if r["summary"] else "")
        + f'{_dday(r, now)}</a>'
        for r in records
    ) or '<div class="empty">지금 열려 있는 공고가 없습니다.<br>새 공고가 올라오면 다음 날 아침 수집에 잡힙니다.</div>'

    hero = _hero(
        [("수집 범위", "부산 · 울산 · 경남"),
         ("대상", "대학 평생교육원"),
         ("갱신", f"{now.astimezone(KST):%Y-%m-%d %H:%M} KST")],
        "대학 평생교육원<br>강사 공고",
        f"활성 {len(records)}건",
    )
    index = f"""<div class="search"><input id="q" placeholder="기관, 제목, 분야, 지역으로 검색"></div>
<div class="list" id="t">{cards}</div>
<script>
const q=document.getElementById('q'),rows=[...document.querySelectorAll('#t .row')];
q.addEventListener('input',()=>{{const v=q.value.trim().toLowerCase();
rows.forEach(r=>r.style.display=!v||r.textContent.toLowerCase().includes(v)?'':'none')}});
</script>"""
    (out_dir / "index.html").write_text(
        _page("부·울·경 대학 평생교육원 강사공고", index, active="index", hero=hero), encoding="utf-8")

    report_files = sorted(reports_dir.glob("*.md"), reverse=True) if reports_dir.exists() else []
    for f in report_files:
        body = md_to_html(f.read_text(encoding="utf-8"))
        page = _page(f"일일 요약 {f.stem}", body, base="../", active="reports",
                     hero=_hero([("문서", "일일 요약"), ("날짜", f.stem)], "일일 리포트"))
        (out_dir / "reports" / f"{f.stem}.html").write_text(page, encoding="utf-8")
    links = "".join(f'<li><a href="./{f.stem}.html">{f.stem}</a></li>' for f in report_files) \
        or '<li class="empty">아직 없음</li>'
    (out_dir / "reports" / "index.html").write_text(
        _page("일일 리포트", f'<h1>일일 리포트 {len(report_files)}건</h1><ul class="archive">{links}</ul>',
              base="../", active="reports",
              hero=_hero([("문서", "아카이브"), ("갱신", f"{now.astimezone(KST):%Y-%m-%d} KST")], "일일 리포트")),
        encoding="utf-8")

    stats = compute_stats(postings, now, days=7)
    (out_dir / "stats.html").write_text(
        _page("주간 통계", md_to_html(stats.to_markdown()), active="stats",
              hero=_hero([("기간", "최근 7일"), ("갱신", f"{now.astimezone(KST):%Y-%m-%d} KST")], "주간 통계")),
        encoding="utf-8")
    (out_dir / ".nojekyll").write_text("", encoding="utf-8")
    return {"active": len(records), "reports": len(report_files)}


def _deadline_label(r: dict) -> str:
    if r["deadline_type"] == "until_filled":
        return "채용 시까지"
    if not r["deadline"]:
        return "확인 필요"
    return r["deadline"][:16].replace("T", " ")
