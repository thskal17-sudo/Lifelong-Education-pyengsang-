"""설정 로딩 (docs/DESIGN.md 13절)."""
from __future__ import annotations

import os
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from .models import OrgType


class ReportSettings(BaseModel):
    send_time_kst: str = "07:30"
    weekdays_only: bool = False
    telegram_max_items: int = 15
    closing_soon_days: int = 3
    daily_overview_llm: bool = False
    recheck_active_days: int = 3
    weekly_stats_weekday: int = 0  # 0=월요일, -1이면 주간 통계 섹션 비활성


class ClassifierSettings(BaseModel):
    include_threshold: int = 70
    review_threshold: int = 30
    include_review_without_llm: bool = True
    llm_enabled: bool = False
    llm_model: str = "claude-opus-5"
    llm_effort: str = "low"
    llm_max_calls_per_run: int = 60


class CollectorSettings(BaseModel):
    default_pages: int = 2
    default_days: int = 14
    backfill_days: int = 60
    per_domain_delay_sec: float = 1.5
    request_timeout_sec: float = 20
    source_time_budget_sec: float = 180
    concurrency: int = 4
    respect_robots: bool = True
    user_agent: str = "GyeongnamInstructorBot/0.1 (+https://github.com/thskal17-sudo/Gyeongnam-Instructor-Announcement)"
    attachment_max_mb: int = 10
    max_detail_errors_per_source: int = 5
    attachment_max_files: int = 3
    attachment_extensions: list[str] = Field(default_factory=lambda: [".hwp", ".hwpx", ".pdf", ".docx"])


class InterestSettings(BaseModel):
    weights: dict[str, float] = Field(default_factory=dict)
    keywords: list[str] = Field(default_factory=list)


class NotifySettings(BaseModel):
    channels: list[str] = Field(default_factory=lambda: ["telegram"])


class Settings(BaseModel):
    timezone: str = "Asia/Seoul"
    report: ReportSettings = Field(default_factory=ReportSettings)
    classifier: ClassifierSettings = Field(default_factory=ClassifierSettings)
    collector: CollectorSettings = Field(default_factory=CollectorSettings)
    interests: InterestSettings = Field(default_factory=InterestSettings)
    notify: NotifySettings = Field(default_factory=NotifySettings)


class SourceConfig(BaseModel):
    id: str
    name: str
    org_type: OrgType
    tier: int = 3
    enabled: bool = True
    verified: bool = False
    tos_checked: bool = False
    schedule: str = "daily"
    homepage: str | None = None
    region_hint: list[str] = Field(default_factory=list)
    adapter: dict[str, Any] = Field(default_factory=dict)
    notes: str | None = None

    def unconfigured_reason(self) -> str | None:
        """어댑터 설정이 아직 채워지지 않았으면 이유를 돌려준다."""
        if not self.adapter.get("type"):
            return "adapter.type 없음"
        todo = _find_todo(self.adapter)
        if todo:
            return f"미설정 값: {todo}"
        return None


def _find_todo(obj: Any, path: str = "adapter") -> str | None:
    if isinstance(obj, str):
        return path if obj.strip().upper() == "TODO" else None
    if isinstance(obj, dict):
        for k, v in obj.items():
            hit = _find_todo(v, f"{path}.{k}")
            if hit:
                return hit
    if isinstance(obj, list):
        for i, v in enumerate(obj):
            hit = _find_todo(v, f"{path}[{i}]")
            if hit:
                return hit
    return None


def deep_merge(base: dict, override: dict) -> dict:
    out = deepcopy(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = deepcopy(v)
    return out


def load_settings(path: Path) -> Settings:
    if not path.exists():
        return Settings()
    with path.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return Settings.model_validate(raw)


def load_sources(path: Path) -> list[SourceConfig]:
    with path.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    defaults = raw.get("defaults", {}) or {}
    out: list[SourceConfig] = []
    seen: set[str] = set()
    for item in raw.get("sources", []) or []:
        merged = deep_merge(defaults, item)
        cfg = SourceConfig.model_validate(merged)
        if cfg.id in seen:
            raise ValueError(f"중복된 source id: {cfg.id}")
        seen.add(cfg.id)
        out.append(cfg)
    return out


def load_aliases(path: Path) -> dict[str, list[str]]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return {str(k): [str(x) for x in (v or [])] for k, v in raw.items()}


class MissingSecret(Exception):
    pass


_ENV_RE = re.compile(r"\$\{(\w+)\}")


def resolve_env(obj: Any) -> Any:
    """문자열 안의 ${VAR}를 환경변수로 치환한다. 없으면 MissingSecret."""
    if isinstance(obj, str):
        def _sub(m: re.Match) -> str:
            val = os.environ.get(m.group(1))
            if val is None or val == "":
                raise MissingSecret(f"환경변수 {m.group(1)} 없음")
            return val
        return _ENV_RE.sub(_sub, obj)
    if isinstance(obj, dict):
        return {k: resolve_env(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [resolve_env(v) for v in obj]
    return obj


class ConfigBundle(BaseModel):
    settings: Settings
    sources: list[SourceConfig]
    aliases: dict[str, list[str]]


def load_bundle(config_dir: Path) -> ConfigBundle:
    return ConfigBundle(
        settings=load_settings(config_dir / "settings.yaml"),
        sources=load_sources(config_dir / "sources.yaml"),
        aliases=load_aliases(config_dir / "org_aliases.yaml"),
    )
