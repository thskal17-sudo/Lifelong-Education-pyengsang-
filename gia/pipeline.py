"""수집·판별·저장 파이프라인 (docs/DESIGN.md 11.2)."""
from __future__ import annotations

import hashlib
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from urllib.parse import unquote, urlsplit

from .classify.llm import Extraction, LlmClassifier
from .classify.rules import score_posting
from .collectors.base import FetchError, HttpClient, UnconfiguredSource
from .collectors.registry import build_adapter
from .config import ConfigBundle, MissingSecret, SourceConfig
from .dedupe import canonical_key, find_duplicate, merge
from .feedback import apply_feedback, feedback_path, load_feedback
from .extract.attachments import extract_text, file_extension
from .extract.deadline import KST, DeadlineType, parse_deadline, parse_known_format
from .models import Posting, RawPosting, RunLog, SourceRef, SourceRunResult, Status
from .models import FIELD_NAMES
from .normalize import clean_url, extract_regions, mask_pii, normalize_title, standardize_org
from .store import Store

log = logging.getLogger("gia")


@dataclass
class SourceOutcome:
    result: SourceRunResult
    postings: list[Posting] = field(default_factory=list)
    touched: list[str] = field(default_factory=list)  # 이미 알던 URL (last_seen 갱신)
    excluded: list[str] = field(default_factory=list)  # 규칙 점수 미달 URL
    bodies: dict[str, tuple[str, str | None]] = field(default_factory=dict)  # canonical_key → (본문, 근무지 필드) — LLM 입력용


def build_posting(raw: RawPosting, cfg: SourceConfig, bundle: ConfigBundle, now: datetime) -> Posting | None:
    """RawPosting → Posting. 관련성이 낮으면 None."""
    cs = bundle.settings.classifier
    title, flags = normalize_title(raw.title)
    org = standardize_org(raw.org_name or cfg.adapter.get("org_name") or cfg.name, bundle.aliases)  # adapter.org_name: 게시판 이름 대신 쓸 기관명
    body = mask_pii(raw.body_text or "")
    rule = score_posting(title, body, raw.region_text, org)
    if rule.score < cs.review_threshold:
        return None
    if rule.score < cs.include_threshold:
        # 판단 유보 구간: LLM이 켜져 있으면 LLM 단계로 넘기고, 아니면 설정에 따라 플래그를 달아 포함하거나 제외
        if not cs.llm_enabled and not cs.include_review_without_llm:
            return None
        flags.append("판별유보")

    posted = raw.posted_at
    inferred = posted is None
    ref = posted or now.date()
    deadline_dt, dtype, dtext = None, DeadlineType.unknown, None
    if raw.deadline_text:
        deadline_dt = parse_known_format(raw.deadline_text)
        if deadline_dt:
            dtype, dtext = DeadlineType.fixed, raw.deadline_text
        else:
            res = parse_deadline(raw.deadline_text, ref)
            deadline_dt, dtype, dtext = res.deadline, res.deadline_type, res.text
    if deadline_dt is None and dtype != DeadlineType.until_filled:
        res = parse_deadline(body, ref)
        if res.deadline is None and res.deadline_type == DeadlineType.unknown:
            res = parse_deadline(title, ref)
        deadline_dt, dtype, dtext = res.deadline, res.deadline_type, res.text

    if raw.extra.get("attachment_errors"):
        flags.append("첨부추출실패")
    regions = extract_regions(" ".join([title, org, raw.region_text or "", body[:3000]]))
    if not regions and cfg.region_hint and cfg.org_type.value != "portal":
        regions = [r if r != "경상남도" else "경남" for r in cfg.region_hint][:1]

    key = canonical_key(org, title)
    content_hash = hashlib.sha1(f"{title}|{deadline_dt.isoformat() if deadline_dt else ''}|{body[:5000]}".encode()).hexdigest()
    return Posting(
        id=key[:12], canonical_key=key, title=title, org_name=org, org_type=cfg.org_type,
        field=rule.field, employment_type=rule.employment_type, region=regions,
        posted_at=posted, posted_at_inferred=inferred,
        deadline=deadline_dt, deadline_type=dtype, deadline_text=dtext,
        relevance_score=rule.score, score_reasons=rule.reasons, flags=flags,
        sources=[SourceRef(source_id=cfg.id, url=clean_url(raw.url), fetched_at=raw.fetched_at or now)],
        attachments=list(raw.attachments), content_hash=content_hash,
        first_seen_at=now, last_seen_at=now, status=Status.new,
    )


def enrich_attachments(raw: RawPosting, http: HttpClient, cs) -> None:
    """첨부파일 텍스트를 본문 뒤에 붙인다. 실패는 extra['attachment_errors']에 기록."""
    if cs.attachment_max_files <= 0 or not raw.attachments:
        return
    allowed = {e.lower() for e in cs.attachment_extensions}
    picked = [u for u in raw.attachments if file_extension(u) in allowed or file_extension(u) == ""][: cs.attachment_max_files]
    parts: list[str] = []
    errors: list[str] = []
    for u in picked:
        try:
            data, header_name = http.download(u, cs.attachment_max_mb * 1024 * 1024)
        except FetchError as e:
            errors.append(str(e)[:200])
            continue
        name = header_name or unquote(urlsplit(u).path.rsplit("/", 1)[-1]) or "attachment"
        if file_extension(name) not in allowed:
            errors.append(f"{name}: 지원하지 않는 형식")
            continue
        res = extract_text(data, name)
        if res.ok:
            parts.append(f"[첨부: {name}]\n{res.text[:8000]}")
        else:
            errors.append(f"{name}: {res.error}")
    if parts:
        raw.body_text = ((raw.body_text or "") + "\n\n" + "\n\n".join(parts)).strip()
    if errors:
        raw.extra["attachment_errors"] = errors


def run_source(cfg: SourceConfig, bundle: ConfigBundle, store: Store, http: HttpClient, now: datetime, since: date | None,
               refetch: bool = False) -> SourceOutcome:
    """refetch=True면 이미 알던 URL도 상세를 다시 가져와 재파싱한다 (파서 수정 후 저장된 공고를 바로잡을 때)."""
    cs = bundle.settings.collector
    res = SourceRunResult(source_id=cfg.id)
    out = SourceOutcome(result=res)
    t0 = time.monotonic()
    try:
        adapter = build_adapter(cfg, http, cs, since=since)
    except UnconfiguredSource as e:
        res.status, res.errors = "unconfigured", [str(e)]
        return out
    try:
        listings = adapter.fetch_list()
    except MissingSecret as e:
        res.status, res.errors = "unconfigured", [str(e)]
        return out
    except (FetchError, Exception) as e:  # noqa: BLE001 - 소스 격리
        res.status, res.errors = "fail", [f"목록 실패: {type(e).__name__}: {e}"[:300]]
        log.warning("[%s] %s", cfg.id, res.errors[0])
        adapter.close()
        return out
    res.listed = len(listings)
    if not listings:
        res.status = "empty"
    recheck_before = now - timedelta(days=bundle.settings.report.recheck_active_days)
    for l in listings:
        if time.monotonic() - t0 > cs.source_time_budget_sec:
            res.errors.append("시간 예산 초과: 나머지 목록 건너뜀")
            break
        url = clean_url(l.url)
        if url in store.excluded_urls:
            continue
        existing = store.by_url(url)
        if existing and not refetch and not (existing.status != Status.expired and existing.last_seen_at < recheck_before):
            out.touched.append(existing.canonical_key)
            continue
        try:
            raw = adapter.fetch_detail(l)
        except (FetchError, Exception) as e:  # noqa: BLE001
            res.errors.append(f"상세 실패 {url}: {e}"[:300])
            if len(res.errors) >= cs.max_detail_errors_per_source:
                res.errors.append("상세 오류 누적으로 소스 중단")
                res.status = "fail"
                break
            continue
        res.detail_fetched += 1
        enrich_attachments(raw, http, cs)
        p = build_posting(raw, cfg, bundle, now)
        if p:
            out.postings.append(p)
            out.bodies[p.canonical_key] = (mask_pii(raw.body_text or ""), raw.region_text)
        else:
            out.excluded.append(url)
    adapter.close()
    res.duration_ms = int((time.monotonic() - t0) * 1000)
    return out


def apply_extraction(p: Posting, ext: Extraction) -> None:
    """LLM 추출 결과를 Posting에 반영한다 (규칙 결과를 보강, 마감일은 규칙이 못 찾았을 때만)."""
    if ext.field in FIELD_NAMES and ext.field != "other":
        p.field = ext.field
    if ext.employment_type in ("시간강사", "기간제", "프리랜서", "용역", "기타") and ext.employment_type != "기타":
        p.employment_type = ext.employment_type
    dl = ext.deadline_datetime()
    if p.deadline is None and dl is not None:
        p.deadline = dl
        p.deadline_type = DeadlineType.fixed
        p.deadline_text = p.deadline_text or ext.deadline
    elif p.deadline is None and ext.deadline_type == "until_filled":
        p.deadline_type = DeadlineType.until_filled
    if not p.region and ext.work_location:
        p.region = extract_regions(ext.work_location) or [ext.work_location[:10]]
    p.qualifications = [q[:40] for q in ext.qualifications[:3]]
    p.pay = (ext.pay or None) and ext.pay[:40]
    p.apply_method = ext.apply_method
    p.one_line_summary = ext.one_line_summary[:60]
    p.llm_confidence = ext.confidence
    if "판별유보" in p.flags and ext.confidence >= 0.7:
        p.flags.remove("판별유보")
        p.relevance_score = max(p.relevance_score, 70)
    p.score_reasons.append(f"LLM 확신도 {ext.confidence:.2f}")


def run_llm_stage(outcomes: list[SourceOutcome], llm: LlmClassifier, bundle: ConfigBundle, store: Store, now: datetime) -> None:
    """판단 유보 건을 우선, 그다음 확정 포함 건 순으로 LLM 호출 상한까지 판별·추출한다."""
    cfg_by_id = {s.id: s for s in bundle.sources}
    queue: list[tuple[int, SourceOutcome, Posting]] = []
    for oc in outcomes:
        for p in oc.postings:
            priority = 0 if "판별유보" in p.flags else 1
            queue.append((priority, oc, p))
    queue.sort(key=lambda t: (t[0], -t[2].relevance_score))
    for _, oc, p in queue:
        if llm.remaining <= 0:
            break
        body, region_text = oc.bodies.get(p.canonical_key, ("", None))
        cfg = cfg_by_id.get(p.sources[0].source_id) if p.sources else None
        ext = llm.classify(p.title, p.org_name, cfg.org_type.value if cfg else p.org_type.value, body, region_text)
        if ext is None:
            continue
        if not ext.is_instructor_job:
            oc.postings.remove(p)
            oc.result.llm_excluded += 1
            for s in p.sources:
                store.mark_excluded(s.url, now)
            log.info("[llm] 제외: %s · %s (%s)", p.org_name, p.title, ext.exclusion_reason)
            continue
        apply_extraction(p, ext)


def collect(bundle: ConfigBundle, store: Store, http: HttpClient, only: list[str] | None = None,
            dry_run: bool = False, backfill_days: int | None = None, now: datetime | None = None,
            light: bool = False, llm: LlmClassifier | None = None, refetch: bool = False) -> RunLog:
    now = now or datetime.now(KST)
    cs = bundle.settings.collector
    since = now.date() - timedelta(days=backfill_days if backfill_days else cs.default_days)
    selected = [s for s in bundle.sources if s.enabled and (only is None or s.id in only) and (not light or s.schedule == "daily_light")]
    run = RunLog(run_id=now.strftime("%Y-%m-%dT%H-%M"), started_at=now)
    if backfill_days:
        run.notes.append(f"백필 {backfill_days}일")
    if refetch:
        run.notes.append("재수집: 이미 알던 URL도 상세를 다시 파싱")

    fb_applied = apply_feedback(store, load_feedback(feedback_path(store.data_dir)), now)
    if fb_applied:
        run.notes.append(f"피드백 적용 {fb_applied}건")

    with ThreadPoolExecutor(max_workers=max(1, cs.concurrency)) as ex:
        outcomes = list(ex.map(lambda c: run_source(c, bundle, store, http, now, since, refetch=refetch), selected))

    llm = llm if llm is not None else LlmClassifier.from_settings(bundle.settings.classifier)
    if llm is not None:
        run_llm_stage(outcomes, llm, bundle, store, now)
        u = llm.usage
        run.llm_calls, run.llm_input_tokens, run.llm_output_tokens = u.calls, u.input_tokens, u.output_tokens
        run.llm_cache_read_tokens, run.llm_refusals, run.llm_errors = u.cache_read_tokens, u.refusals, u.errors
        run.llm_excluded = sum(oc.result.llm_excluded for oc in outcomes)
        if llm.remaining <= 0:
            run.notes.append(f"LLM 호출 상한({bundle.settings.classifier.llm_max_calls_per_run}) 도달: 이후 건은 규칙 판별만 적용")

    counts = {"new": 0, "updated": 0, "merged": 0}
    batch: list[Posting] = []
    for oc in outcomes:
        for u in oc.excluded:
            store.mark_excluded(u, now)
        for k in oc.touched:
            p = store.get(k)
            if p:
                p.last_seen_at = now
        for p in oc.postings:
            # 같은 URL 을 이미 알고 있으면 그 공고다 (기관명·제목 정규화가 바뀌어 canonical_key 가 달라져도 중복 생성 방지)
            dup = next((d for d in (store.by_url(s.url) for s in p.sources) if d is not None), None)
            if dup is None:
                dup = find_duplicate(p, list(store.values()) + batch)
            if dup is None:
                batch.append(p)
                store.upsert(p)
                counts["new"] += 1
                oc.result.new += 1
                continue
            same_url = {s.url for s in p.sources} & {s.url for s in dup.sources}
            if dup.status == Status.expired and "재공고" in p.flags and not same_url:
                # 같은 URL을 다시 파싱한 것(재수집)은 재공고가 아니라 같은 공고다
                p.reannouncement_of = dup.id
                batch.append(p)
                store.upsert(p)
                counts["new"] += 1
                oc.result.new += 1
                continue
            merged, changed = merge(dup, p, now, prefer_incoming=refetch)
            if changed and merged.last_reported_at is not None:
                merged.status = Status.updated
                counts["updated"] += 1
                oc.result.updated += 1
            elif changed and merged.status != Status.expired:
                merged.status = Status.new  # 아직 한 번도 보고되지 않은 건은 신규로 보고
            counts["merged"] += 1
            store.upsert(merged)
            if dup in batch:
                batch[batch.index(dup)] = merged
        run.sources.append(oc.result)

    store.refresh_statuses(now, bundle.settings.report.closing_soon_days)
    counts["closing_soon"] = sum(1 for p in store.values() if p.status == Status.closing_soon)
    counts["expired"] = sum(1 for p in store.values() if p.status == Status.expired)
    run.totals = counts
    run.finished_at = datetime.now(KST)
    store.state["last_run_at"] = now.isoformat()
    if not dry_run:
        store.save()
        store.save_run(run)
    return run
