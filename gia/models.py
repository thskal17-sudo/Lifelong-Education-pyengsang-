"""데이터 모델 (docs/DESIGN.md 12절)."""
from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class OrgType(str, Enum):
    local_gov = "local_gov"
    edu_office = "edu_office"
    local_public = "local_public"
    central_public = "central_public"
    university = "university"
    private = "private"
    portal = "portal"


ORG_TYPE_ORDER = [t.value for t in OrgType]


class Status(str, Enum):
    new = "new"
    updated = "updated"
    closing_soon = "closing_soon"
    expired = "expired"
    active = "active"


class DeadlineType(str, Enum):
    fixed = "fixed"
    until_filled = "until_filled"
    unknown = "unknown"


FIELD_NAMES: dict[str, str] = {
    "lifelong": "평생교육",
    "vocational": "직업훈련",
    "school": "학교·방과후",
    "arts": "문화예술",
    "sports": "체육",
    "it_digital": "IT·디지털",
    "counsel_welfare": "상담·복지",
    "safety_health": "안전·보건",
    "corporate": "기업교육",
    "language_kor": "한국어·다문화",
    "other": "기타",
}


class RawListing(BaseModel):
    """목록 단계에서 얻은 공고 후보."""

    source_id: str
    title: str
    url: str
    org_name: str | None = None
    posted_at: date | None = None
    deadline_text: str | None = None  # 목록/API가 마감일을 직접 주는 경우
    region_text: str | None = None  # 근무지 필드가 따로 있는 경우
    extra: dict[str, Any] = Field(default_factory=dict)


class RawPosting(RawListing):
    """상세 단계까지 채운 공고."""

    body_text: str = ""
    attachments: list[str] = Field(default_factory=list)
    fetched_at: datetime | None = None


class SourceRef(BaseModel):
    source_id: str
    url: str
    fetched_at: datetime


class Posting(BaseModel):
    id: str
    canonical_key: str
    title: str
    org_name: str
    org_type: OrgType
    field: str = "other"
    employment_type: str = "기타"
    region: list[str] = Field(default_factory=list)
    posted_at: date | None = None
    posted_at_inferred: bool = False
    deadline: datetime | None = None
    deadline_type: DeadlineType = DeadlineType.unknown
    deadline_text: str | None = None
    qualifications: list[str] = Field(default_factory=list)
    pay: str | None = None
    apply_method: str | None = None
    one_line_summary: str = ""
    relevance_score: int = 0
    score_reasons: list[str] = Field(default_factory=list)
    llm_confidence: float | None = None
    status: Status = Status.new
    flags: list[str] = Field(default_factory=list)
    sources: list[SourceRef] = Field(default_factory=list)
    attachments: list[str] = Field(default_factory=list)
    content_hash: str = ""
    first_seen_at: datetime
    last_seen_at: datetime
    last_reported_at: datetime | None = None
    reannouncement_of: str | None = None

    @property
    def primary_url(self) -> str:
        return self.sources[0].url if self.sources else ""


class SourceRunResult(BaseModel):
    source_id: str
    status: str = "ok"  # ok | fail | empty | unconfigured | skipped
    listed: int = 0
    new: int = 0
    updated: int = 0
    detail_fetched: int = 0
    llm_excluded: int = 0
    errors: list[str] = Field(default_factory=list)
    duration_ms: int = 0


class RunLog(BaseModel):
    run_id: str
    started_at: datetime
    finished_at: datetime | None = None
    sources: list[SourceRunResult] = Field(default_factory=list)
    totals: dict[str, int] = Field(default_factory=dict)
    llm_calls: int = 0
    llm_input_tokens: int = 0
    llm_output_tokens: int = 0
    llm_cache_read_tokens: int = 0
    llm_refusals: int = 0
    llm_errors: int = 0
    llm_excluded: int = 0
    notes: list[str] = Field(default_factory=list)

    def counts(self) -> dict[str, int]:
        out = {"ok": 0, "fail": 0, "empty": 0, "unconfigured": 0, "skipped": 0}
        for s in self.sources:
            out[s.status] = out.get(s.status, 0) + 1
        return out
