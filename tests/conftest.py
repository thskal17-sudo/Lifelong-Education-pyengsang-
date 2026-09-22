from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from gia.config import ClassifierSettings, CollectorSettings, ConfigBundle, Settings, SourceConfig
from gia.extract.deadline import KST
from gia.models import OrgType, Posting, SourceRef, Status

NOW = datetime(2026, 9, 21, 6, 30, tzinfo=KST)
FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def now() -> datetime:
    return NOW


@pytest.fixture
def settings() -> Settings:
    s = Settings()
    s.collector = CollectorSettings(per_domain_delay_sec=0, respect_robots=False, concurrency=2)
    s.classifier = ClassifierSettings()
    return s


def make_source(id: str = "test", org_type: str = "local_public", **adapter) -> SourceConfig:
    return SourceConfig(id=id, name=f"{id} 기관", org_type=OrgType(org_type), tier=1, adapter=adapter, region_hint=["경남"])


@pytest.fixture
def bundle(settings) -> ConfigBundle:
    return ConfigBundle(settings=settings, sources=[], aliases={"경남테크노파크": ["경남TP"]})


def make_posting(title: str, org: str = "경남인재평생교육진흥원", deadline: datetime | None = None, now: datetime = NOW, **kw) -> Posting:
    from gia.dedupe import canonical_key
    key = canonical_key(org, title)
    base = dict(
        id=key[:12], canonical_key=key, title=title, org_name=org, org_type=OrgType.local_public,
        deadline=deadline, sources=[SourceRef(source_id="src", url=f"https://example.org/{key[:6]}", fetched_at=now)],
        first_seen_at=now, last_seen_at=now, status=Status.new, relevance_score=80,
    )
    base.update(kw)
    return Posting(**base)
