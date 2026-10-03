"""HTML 파서(lexbor)가 설정의 셀렉터를 그대로 읽는지 지킨다.

2026-10-04 에 selectolax 1.0 이 옛 Modest 백엔드를 지우면서 두 저장소의 수집·보고가
한꺼번에 멈췄다. lexbor 로 옮기면서 가장 걱정한 것은 파서가 바뀌어 셀렉터가 조용히
어긋나는 일이었다 — 멈추는 것보다 나쁘다. 실제로 저장된 픽스처에 설정의 셀렉터를
모두 걸어 보고 옮겼고, 그 확인을 여기에 남긴다.
"""
from __future__ import annotations

import glob
from pathlib import Path

import pytest
import yaml

from gia.collectors.html_list import HTMLParser

ROOT = Path(__file__).resolve().parents[1]


def configured_selectors() -> set[str]:
    """config/sources.yaml 이 실제로 쓰는 CSS 셀렉터 전부."""
    out: set[str] = set()
    data = yaml.safe_load((ROOT / "config" / "sources.yaml").read_text(encoding="utf-8"))
    for s in data.get("sources") or []:
        a = s.get("adapter") or {}
        for k, v in a.items():
            if k.endswith("_selector") and v:
                out.add(v)
        for k, v in (a.get("detail") or {}).items():
            if k.endswith("_selector") and v:
                out.add(v)
    return out


def test_uses_lexbor_backend():
    """옛 Modest 백엔드로 되돌아가지 않는다 — 그것은 selectolax 1.0 에서 사라졌다."""
    assert HTMLParser.__module__.startswith("selectolax.lexbor"), HTMLParser.__module__


def test_every_configured_selector_parses():
    """설정의 셀렉터가 모두 lexbor 에서 문법 오류 없이 돈다."""
    html = "<html><body><table><tr><td>x</td></tr></table></body></html>"
    tree = HTMLParser(html)
    bad = []
    for sel in sorted(configured_selectors()):
        try:
            tree.css(sel)
        except Exception as e:  # noqa: BLE001
            bad.append(f"{sel}: {e}")
    assert not bad, "lexbor 가 못 읽는 셀렉터:\n" + "\n".join(bad)


def test_implied_tbody_still_matches():
    """설정 상당수가 'tbody tr' 을 쓴다. 게시판 HTML 에 tbody 가 없어도 맞아야 한다."""
    tree = HTMLParser("<table class='t'><tr><td>A</td></tr><tr><td>B</td></tr></table>")
    assert len(tree.css("table.t tbody tr")) == 2


@pytest.mark.parametrize("path", sorted(glob.glob(str(ROOT / "tests" / "fixtures" / "*.html"))))
def test_fixtures_still_yield_rows(path: str):
    """저장된 게시판 픽스처에서 셀렉터가 여전히 뭔가를 찾는다 (0건이면 조용한 고장)."""
    tree = HTMLParser(Path(path).read_text(encoding="utf-8", errors="replace"))
    assert any(tree.css(sel) for sel in configured_selectors()), f"{Path(path).name}: 맞는 셀렉터가 하나도 없다"
