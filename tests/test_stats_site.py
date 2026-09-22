from datetime import timedelta
from pathlib import Path

from gia.models import OrgType, Status
from gia.site import build_site, md_to_html, public_record
from gia.stats import compute_stats
from tests.conftest import NOW, make_posting


def _postings():
    a = make_posting("수영강사 모집", org="창원시설공단", field="sports", region=["창원"], deadline=NOW + timedelta(days=3))
    b = make_posting("시민강좌 강사 모집", org="김해시", org_type=OrgType.local_gov, field="lifelong", region=["김해"], deadline=NOW + timedelta(days=20), first_seen_at=NOW - timedelta(days=10), last_seen_at=NOW)
    c = make_posting("지난 공고", org="김해시", org_type=OrgType.local_gov, field="lifelong", deadline=NOW - timedelta(days=1), status=Status.expired)
    d = make_posting("오탐 공고", org="밀양시", flags=["피드백제외"], status=Status.expired)
    return [a, b, c, d]


def test_compute_stats():
    s = compute_stats(_postings(), NOW, days=7)
    assert s.total == 2  # a(신규), c(만료지만 최근 7일 신규) — b는 10일 전, d는 피드백 제외
    assert s.active_total == 2 and s.closing_next_week == 1
    assert s.by_field["sports"] == 1 and s.by_org_type["local_public"] == 1
    md = s.to_markdown()
    assert "| 체육 | 1 |" in md and "지방 출자출연" in md


def test_public_record_has_no_body_or_pii():
    r = public_record(_postings()[0])
    assert set(r) >= {"id", "title", "org", "url", "deadline", "summary"}
    assert "body" not in r and "sources" not in r


def test_md_to_html_covers_report_constructs():
    md = "# 제목\n\n신규 **2건**\n\n## 섹션\n\n1. **[체육] 기관 · 공고** — D-1\n   마감 09.22(화)\n   → https://x.org/a (출처: 포털)\n\n| 구분 | 값 |\n|---|---|\n| 실행 | 06:30 |\n\n> 총평입니다"
    html = md_to_html(md)
    assert "<h1>제목</h1>" in html and "<b>2건</b>" in html
    assert "<li><b>[체육] 기관 · 공고</b> — D-1<br>마감 09.22(화)<br>→ <a href=\"https://x.org/a\">https://x.org/a</a> (출처: 포털)</li>" in html
    assert "<table>" in html and "<th>구분</th>" in html and "<td>06:30</td>" in html
    assert "<blockquote>총평입니다</blockquote>" in html


def test_build_site(tmp_path):
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "2026-09-21.md").write_text("# 경남 강사 구인공고 일일 요약 — 2026-09-21 (월)\n\n신규 **1건**\n", encoding="utf-8")
    out = tmp_path / "site"
    info = build_site(_postings(), reports, out, NOW)
    assert info == {"active": 2, "reports": 1}
    index = (out / "index.html").read_text(encoding="utf-8")
    assert "활성 2건" in index and "수영강사 모집" in index and "오탐 공고" not in index and "지난 공고" not in index
    assert (out / "data" / "postings.json").exists() and (out / ".nojekyll").exists()
    assert "일일 요약" in (out / "reports" / "2026-09-21.html").read_text(encoding="utf-8")
    assert 'href="./2026-09-21.html"' in (out / "reports" / "index.html").read_text(encoding="utf-8")
    assert "주간 통계" in (out / "stats.html").read_text(encoding="utf-8")
