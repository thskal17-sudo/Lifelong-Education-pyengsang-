"""LLM 판별·구조화 추출 (docs/DESIGN.md 7.2). Claude API, 구조화 출력, 프롬프트 캐싱, 거부 폴백."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from ..config import ClassifierSettings
from ..extract.deadline import KST
from ..models import FIELD_NAMES

log = logging.getLogger("gia.llm")
_PROMPT_PATH = Path(__file__).parent / "prompts" / "classifier_system.md"
_FALLBACK_MODELS = ("claude-opus-5", "claude-fable")  # 서버 측 폴백을 지원하는 모델 접두


class Extraction(BaseModel):
    """공고 한 건에 대한 LLM 추출 결과 (설계서 7.2 스키마)."""

    is_instructor_job: bool
    confidence: float = Field(ge=0, le=1)
    field: str = "other"
    employment_type: str = "기타"
    deadline: str | None = None
    deadline_type: str = "unknown"
    work_location: str | None = None
    qualifications: list[str] = Field(default_factory=list)
    pay: str | None = None
    apply_method: str | None = None
    one_line_summary: str = ""
    exclusion_reason: str | None = None

    def deadline_datetime(self) -> datetime | None:
        if not self.deadline:
            return None
        try:
            dt = datetime.fromisoformat(self.deadline.replace("Z", "+00:00"))
        except ValueError:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=KST)
        return dt.astimezone(KST)


@dataclass
class LlmUsage:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    refusals: int = 0
    errors: int = 0


def build_user_prompt(title: str, org_name: str, org_type: str, body: str, region_text: str | None) -> str:
    parts = [f"제목: {title}", f"기관: {org_name}", f"출처 유형: {org_type}"]
    if region_text:
        parts.append(f"근무지 필드: {region_text}")
    parts.append("본문:\n" + (body or "(본문 없음)")[:10000])
    return "\n".join(parts)


class LlmClassifier:
    def __init__(self, settings: ClassifierSettings, client: Any = None, usage: LlmUsage | None = None):
        self.settings = settings
        self._client = client
        self.usage = usage or LlmUsage()
        self.system_prompt = _PROMPT_PATH.read_text(encoding="utf-8")

    @classmethod
    def from_settings(cls, settings: ClassifierSettings) -> "LlmClassifier | None":
        """설정이 켜져 있고 API 키가 있을 때만 분류기를 만든다."""
        if not settings.llm_enabled:
            return None
        if not os.environ.get("ANTHROPIC_API_KEY"):
            log.warning("llm_enabled=true 이지만 ANTHROPIC_API_KEY 가 없어 규칙 판별만 사용")
            return None
        import anthropic

        return cls(settings, client=anthropic.Anthropic())

    @property
    def remaining(self) -> int:
        return max(0, self.settings.llm_max_calls_per_run - self.usage.calls)

    def _request_kwargs(self) -> dict[str, Any]:
        kw: dict[str, Any] = {
            "model": self.settings.llm_model,
            "max_tokens": 2048,
            "system": [{"type": "text", "text": self.system_prompt, "cache_control": {"type": "ephemeral"}}],
            "output_config": {"effort": self.settings.llm_effort},
        }
        if self.settings.llm_model.startswith(_FALLBACK_MODELS):
            kw["betas"] = ["server-side-fallback-2026-07-01"]
            kw["fallbacks"] = "default"
        return kw

    def classify(self, title: str, org_name: str, org_type: str, body: str, region_text: str | None = None) -> Extraction | None:
        """추출 결과, 또는 호출 불가·거부·오류 시 None (호출자는 규칙 결과를 유지)."""
        if self.remaining <= 0:
            return None
        prompt = build_user_prompt(title, org_name, org_type, body, region_text)
        try:
            resp = self._client.beta.messages.parse(
                messages=[{"role": "user", "content": prompt}],
                output_format=Extraction,
                **self._request_kwargs(),
            )
        except Exception as e:  # noqa: BLE001 - API 오류는 규칙 결과로 폴백
            self.usage.errors += 1
            log.warning("LLM 호출 실패: %s: %s", type(e).__name__, e)
            return None
        self.usage.calls += 1
        self._account(resp)
        if getattr(resp, "stop_reason", None) == "refusal":
            self.usage.refusals += 1
            return None
        parsed = getattr(resp, "parsed_output", None)
        if parsed is None:
            self.usage.errors += 1
            return None
        if parsed.field not in FIELD_NAMES:
            parsed.field = "other"
        return parsed

    def summarize_day(self, lines: list[str]) -> str | None:
        """일일 총평(3문장 이내). 설정 report.daily_overview_llm 이 켜졌을 때만 호출."""
        if not lines or self.remaining <= 0:
            return None
        kw = self._request_kwargs()
        kw["system"] = "부산·울산·경남 대학 평생교육원 강사 공고 일일 요약의 총평을 씁니다. 분야·지역·마감 경향을 한국어 3문장 이내로, 수치는 입력에 있는 것만 씁니다."
        kw["max_tokens"] = 512
        try:
            resp = self._client.beta.messages.create(messages=[{"role": "user", "content": "오늘 공고 목록:\n" + "\n".join(lines[:60])}], **kw)
        except Exception as e:  # noqa: BLE001
            self.usage.errors += 1
            log.warning("총평 생성 실패: %s", e)
            return None
        self.usage.calls += 1
        self._account(resp)
        if getattr(resp, "stop_reason", None) == "refusal":
            self.usage.refusals += 1
            return None
        return "".join(getattr(b, "text", "") for b in getattr(resp, "content", []) if getattr(b, "type", "") == "text").strip() or None

    def _account(self, resp: Any) -> None:
        u = getattr(resp, "usage", None)
        if u is None:
            return
        self.usage.input_tokens += int(getattr(u, "input_tokens", 0) or 0)
        self.usage.output_tokens += int(getattr(u, "output_tokens", 0) or 0)
        self.usage.cache_read_tokens += int(getattr(u, "cache_read_input_tokens", 0) or 0)
