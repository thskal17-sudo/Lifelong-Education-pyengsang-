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

_STYLE = """
body{font-family:-apple-system,'Apple SD Gothic Neo','Malgun Gothic',sans-serif;max-width:960px;margin:0 auto;padding:16px;color:#222;line-height:1.5}
a{color:#0b57d0}table{border-collapse:collapse;width:100%}th,td{border-bottom:1px solid #e5e5e5;padding:6px 8px;text-align:left;vertical-align:top}
th{background:#f6f7f9}input{width:100%;padding:8px;font-size:15px;margin:8px 0 12px}small{color:#666}.tag{background:#eef2f7;border-radius:4px;padding:1px 6px;font-size:12px}
blockquote{border-left:3px solid #ccc;margin:0;padding:4px 12px;color:#555}nav a{margin-right:12px}
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


def _page(title: str, body: str, nav: str = "") -> str:
    return f"""<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title><style>{_STYLE}</style></head><body>
<nav><a href="./index.html">활성 공고</a><a href="./reports/index.html">일일 리포트</a><a href="./stats.html">주간 통계</a></nav>
{body}
<p><small>제목·요약·원문 링크만 게시합니다. 본문은 원문에서 확인하세요.</small></p>
</body></html>"""


def build_site(postings, reports_dir: Path, out_dir: Path, now: datetime) -> dict[str, int]:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "reports").mkdir(exist_ok=True)
    (out_dir / "data").mkdir(exist_ok=True)
    active = [p for p in postings if p.status != Status.expired and "피드백제외" not in p.flags]
    active.sort(key=lambda p: (p.deadline is None, p.deadline or now))
    records = [public_record(p) for p in active]
    (out_dir / "data" / "postings.json").write_text(json.dumps(records, ensure_ascii=False, indent=1), encoding="utf-8")

    rows = "".join(
        f"<tr><td><span class='tag'>{html.escape(r['field_name'])}</span></td><td>{html.escape(r['org'])}</td>"
        f"<td><a href=\"{html.escape(r['url'])}\">{html.escape(r['title'])}</a>{('<br><small>' + html.escape(r['summary']) + '</small>') if r['summary'] else ''}</td>"
        f"<td>{html.escape(_deadline_label(r))}</td><td>{html.escape(', '.join(r['region']) or '-')}</td></tr>"
        for r in records
    )
    index = f"""<h1>부·울·경 대학 평생교육원 강사공고 — 활성 {len(records)}건</h1>
<p><small>갱신 {now.astimezone(KST):%Y-%m-%d %H:%M} KST</small></p>
<input id="q" placeholder="기관, 제목, 분야, 지역으로 검색" autofocus>
<table id="t"><tr><th>분야</th><th>기관</th><th>공고</th><th>마감</th><th>지역</th></tr>{rows}</table>
<script>
const q=document.getElementById('q'),rows=[...document.querySelectorAll('#t tr')].slice(1);
q.addEventListener('input',()=>{{const v=q.value.trim().toLowerCase();rows.forEach(r=>r.style.display=!v||r.textContent.toLowerCase().includes(v)?'':'none')}});
</script>"""
    (out_dir / "index.html").write_text(_page("부·울·경 대학 평생교육원 강사공고", index), encoding="utf-8")

    report_files = sorted(reports_dir.glob("*.md"), reverse=True) if reports_dir.exists() else []
    for f in report_files:
        body = md_to_html(f.read_text(encoding="utf-8"))
        (out_dir / "reports" / f"{f.stem}.html").write_text(_page(f"일일 요약 {f.stem}", body).replace('href="./', 'href="../'), encoding="utf-8")
    links = "".join(f"<li><a href=\"./{f.stem}.html\">{f.stem}</a></li>" for f in report_files) or "<li>아직 없음</li>"
    (out_dir / "reports" / "index.html").write_text(_page("일일 리포트", f"<h1>일일 리포트</h1><ul>{links}</ul>").replace('href="./', 'href="../').replace('href="../{', 'href="./{'), encoding="utf-8")
    # 리포트 목록 페이지의 자기 링크 보정
    idx = out_dir / "reports" / "index.html"
    idx.write_text(idx.read_text(encoding="utf-8").replace('href="../20', 'href="./20'), encoding="utf-8")

    stats = compute_stats(postings, now, days=7)
    (out_dir / "stats.html").write_text(_page("주간 통계", "<h1>주간 통계</h1>" + md_to_html(stats.to_markdown())), encoding="utf-8")
    (out_dir / ".nojekyll").write_text("", encoding="utf-8")
    return {"active": len(records), "reports": len(report_files)}


def _deadline_label(r: dict) -> str:
    if r["deadline_type"] == "until_filled":
        return "채용 시까지"
    if not r["deadline"]:
        return "확인 필요"
    return r["deadline"][:16].replace("T", " ")
