"""CLI: gia collect | report | probe | status."""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

from .collectors.base import FetchError, HttpClient
from .collectors.registry import build_adapter
from .config import load_bundle
from .extract.deadline import KST, parse_deadline
from .classify.rules import score_posting
from .models import Status
from .classify.llm import LlmClassifier
from .feedback import LABELS, append_feedback, feedback_path, load_feedback
from .pipeline import build_posting, collect, enrich_attachments
from .report.build import email_subject, render_email, render_markdown, render_telegram, select_postings, write_report
from .site import build_site
from .stats import compute_stats
from .store import Store


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="gia", description="부산·울산·경남 대학 평생교육원 강사 공고 수집·일일 요약")
    p.add_argument("--config-dir", default="config")
    p.add_argument("--data-dir", default="data")
    p.add_argument("--reports-dir", default="reports")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("collect", help="수집·판별·저장")
    c.add_argument("--sources", help="쉼표로 구분한 source id 목록")
    c.add_argument("--dry-run", action="store_true", help="저장하지 않음")
    c.add_argument("--backfill-days", type=int, default=0)
    c.add_argument("--light", action="store_true", help="schedule=daily_light 소스만")
    c.add_argument("--refetch", action="store_true", help="이미 알던 URL도 상세를 다시 가져와 재파싱 (파서 수정 후 저장 데이터 보정)")

    r = sub.add_parser("report", help="요약본 생성(및 발송)")
    r.add_argument("--send", action="store_true", help="채널로 발송하고 보고 상태를 기록")
    r.add_argument("--mark", action="store_true", help="발송 없이 보고 상태만 기록")
    r.add_argument("--print", dest="print_md", action="store_true", help="Markdown을 표준출력으로")
    r.add_argument("--notify-test", action="store_true",
                   help="공고가 없어도 알림을 한 번 보내 채널이 살아 있는지 확인 (제목에 [테스트] 표시)")

    pr = sub.add_parser("probe", help="소스 하나를 시험 수집")
    pr.add_argument("source_id")
    pr.add_argument("--limit", type=int, default=5)
    pr.add_argument("--detail", action="store_true", help="첫 건의 상세·마감일·점수까지 표시")
    pr.add_argument("--ignore-keywords", action="store_true", help="keywords 필터를 무시하고 목록 전부 표시 (셀렉터 확인용)")
    pr.add_argument("--save-fixture", action="store_true", help="목록(및 첫 상세) 응답을 tests/fixtures/live/<id>/ 에 저장")

    so = sub.add_parser("sources", help="소스별 설정 상태")
    so.add_argument("--tier", type=int)
    so.add_argument("--all", action="store_true", help="비활성 소스도 표시")

    fb = sub.add_parser("feedback", help="오탐·미탐 피드백 기록 (다음 수집부터 반영)")
    fb.add_argument("posting_id", nargs="?", help="공고 id (리포트 링크 옆 12자리) — 생략하면 목록 표시")
    fb.add_argument("label", nargs="?", choices=LABELS)
    fb.add_argument("--note", default="")

    ev = sub.add_parser("eval", help="라벨 데이터로 판별 정밀도·재현율 측정")
    ev.add_argument("--labeled", default="tests/eval/labeled.jsonl")
    ev.add_argument("--llm", action="store_true", help="LLM 판별까지 포함 (ANTHROPIC_API_KEY 필요)")

    st = sub.add_parser("stats", help="최근 N일 통계")
    st.add_argument("--days", type=int, default=7)

    si = sub.add_parser("site", help="GitHub Pages용 정적 아카이브 생성")
    si.add_argument("--out", default="site")

    sub.add_parser("status", help="저장소 요약")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(levelname)s %(name)s: %(message)s", stream=sys.stderr)
    bundle = load_bundle(Path(args.config_dir))
    store = Store(Path(args.data_dir)).load()
    now = datetime.now(KST)

    if args.cmd == "collect":
        http = HttpClient(bundle.settings.collector)
        try:
            only = [s.strip() for s in args.sources.split(",")] if args.sources else None
            run = collect(bundle, store, http, only=only, dry_run=args.dry_run, backfill_days=args.backfill_days or None, now=now, light=args.light, refetch=args.refetch)
        finally:
            http.close()
        c = run.counts()
        print(f"[collect] 소스 정상 {c['ok']} / 0건 {c['empty']} / 실패 {c['fail']} / 미설정 {c['unconfigured']} · 신규 {run.totals.get('new',0)} · 병합 {run.totals.get('merged',0)}")
        for s in run.sources:
            if s.status in ("fail", "unconfigured"):
                print(f"  - {s.source_id}: {s.status} {s.errors[0] if s.errors else ''}")
        return 0

    if args.cmd == "report":
        data = select_postings(bundle, store, now)
        if bundle.settings.report.daily_overview_llm and (data.new or data.closing):
            llm = LlmClassifier.from_settings(bundle.settings.classifier)
            if llm:
                lines = [f"[{p.field}] {p.org_name} · {p.title} · 마감 {p.deadline.date() if p.deadline else '미상'} · {', '.join(p.region) or '지역 미상'}" for p in data.closing + data.new]
                data.overview = llm.summarize_day(lines)
        md = render_markdown(data, now)
        path = write_report(md, Path(args.reports_dir), now)
        if args.print_md or not (args.send or args.mark):
            print(md)
        print(f"[report] {path} · 신규 {len(data.new)} · 마감임박 {len(data.closing)} · 변경 {len(data.updated)}", file=sys.stderr)
        failures: list[str] = []
        if args.send:
            channels = bundle.settings.notify.channels
            if "telegram" in channels:
                token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
                if not token or not chat:
                    failures.append("telegram: TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID 없음")
                else:
                    from .notify.telegram import send_telegram
                    try:
                        n = send_telegram(token, chat, render_telegram(data, now))
                        print(f"[report] 텔레그램 {n}개 메시지 전송", file=sys.stderr)
                    except Exception as e:  # noqa: BLE001
                        failures.append(f"telegram: {e}")
            if "email" in channels:
                from .notify.email import SmtpConfig, send_email
                cfg = SmtpConfig.from_env(os.environ)
                if cfg is None:
                    failures.append("email: SMTP_HOST/EMAIL_TO 없음")
                else:
                    try:
                        n = send_email(cfg, email_subject(data, now), render_email(data, now), md)
                        print(f"[report] 이메일 {n}명에게 전송", file=sys.stderr)
                    except Exception as e:  # noqa: BLE001
                        failures.append(f"email: {e}")
            if "github" in channels:
                repo, token = os.environ.get("GITHUB_REPOSITORY"), os.environ.get("GITHUB_TOKEN")
                if not repo or not token:
                    failures.append("github: GITHUB_REPOSITORY/GITHUB_TOKEN 없음")
                elif not (data.new or data.closing or args.notify_test):
                    # 조용한 날에는 열지 않는다. 매일 이슈가 열리면 알림이 배경 소음이 된다
                    print("[report] 깃허브 이슈 생략(신규·마감임박 없음)", file=sys.stderr)
                else:
                    from .notify.github_issue import (
                        default_assignees, issue_body, send_issue,
                    )
                    subject = email_subject(data, now)
                    if args.notify_test:
                        subject = "[테스트] " + subject
                    try:
                        who = os.environ.get("NOTIFY_ASSIGNEES", "")
                        assignees = ([w.strip() for w in who.split(",") if w.strip()]
                                     if who else default_assignees(repo))
                        url = send_issue(repo, token, subject,
                                         issue_body(md, os.environ.get("SITE_URL", "")),
                                         labels=["공고"], assignees=assignees)
                        print(f"[report] 깃허브 이슈 {url}", file=sys.stderr)
                    except Exception as e:  # noqa: BLE001
                        failures.append(f"github: {e}")
            for ch in channels:
                if ch not in ("telegram", "email", "github"):
                    failures.append(f"{ch}: 지원하지 않는 채널")
            for f in failures:
                print(f"[report] 발송 실패 {f}", file=sys.stderr)
        if args.send or args.mark:
            store.mark_reported(data.keys(), now, bundle.settings.report.closing_soon_days)
            store.save()
        sent_any = args.send and len(failures) < len(bundle.settings.notify.channels)
        return 0 if (not args.send or sent_any) else 1

    if args.cmd == "probe":
        cfg = next((s for s in bundle.sources if s.id == args.source_id), None)
        if cfg is None:
            print(f"소스 없음: {args.source_id}", file=sys.stderr)
            return 2
        if args.ignore_keywords:
            cfg.adapter = {**cfg.adapter, "keywords": []}
            print("[probe] keywords 무시: 목록 전부 표시")
        http = HttpClient(bundle.settings.collector)
        try:
            if args.save_fixture:
                _save_fixture(cfg, http, Path("tests/fixtures/live") / cfg.id)
                if cfg.unconfigured_reason():
                    print(f"[probe] 설정 미완료({cfg.unconfigured_reason()}) — 응답 저장만 수행")
                    return 0
            adapter = build_adapter(cfg, http, bundle.settings.collector, since=now.date() - timedelta(days=bundle.settings.collector.default_days))
            try:
                listings = adapter.fetch_list()
            except FetchError as e:
                print(f"[probe] {cfg.name}: 목록 실패 — {e}", file=sys.stderr)
                return 1
            print(f"[probe] {cfg.name}: 목록 {len(listings)}건")
            for l in listings[: args.limit]:
                print(f"  - {l.posted_at or '????-??-??'} | {l.org_name or ''} | {l.title} | {l.url}")
            if args.detail and listings:
                raw = adapter.fetch_detail(listings[0])
                enrich_attachments(raw, http, bundle.settings.collector)  # collect 와 같은 본문(첨부 텍스트 포함)으로 판정
                if raw.extra.get("attachment_errors"):
                    print(f"[detail] 첨부 추출 실패: {raw.extra['attachment_errors']}")
                res = parse_deadline(raw.body_text, raw.posted_at)
                rule = score_posting(raw.title, raw.body_text, raw.region_text, raw.org_name or cfg.name)
                print(f"[detail] 본문 {len(raw.body_text)}자 · 마감 {res.deadline} ({res.deadline_type.value}, '{res.text}') · 점수 {rule.score} {rule.reasons} · 분야 {rule.field}")
                if res.deadline is None:
                    # 마감일을 못 찾았을 때: 날짜·접수 문맥이 있는 줄을 보여줘 파서 보강 근거로 삼는다
                    import re as _re
                    pat = _re.compile(r"\d{4}\s*[.\-/년]\s*\d{1,2}|\d{1,2}\s*[.\-/월]\s*\d{1,2}|접수|마감|모집기간|까지")
                    hits = [ln.strip() for ln in raw.body_text.splitlines() if pat.search(ln)]
                    for ln in hits[:12]:
                        print(f"  [date?] {ln[:160]}")
                p = build_posting(raw, cfg, bundle, now)
                print(f"[posting] {'포함' if p else '제외'}: {p.title if p else ''}")
        finally:
            http.close()
        return 0

    if args.cmd == "sources":
        rows = [s for s in bundle.sources if (args.all or s.enabled) and (args.tier is None or s.tier == args.tier)]
        ready = sum(1 for s in rows if s.unconfigured_reason() is None)
        print(f"소스 {len(rows)}건 · 실행 가능 {ready} · 미설정 {len(rows) - ready} · 검증됨 {sum(1 for s in rows if s.verified)}")
        for s in rows:
            state = "검증됨" if s.verified else ("실행가능" if s.unconfigured_reason() is None else f"미설정: {s.unconfigured_reason()}")
            flag = "" if s.enabled else " (비활성)"
            print(f"  T{s.tier} {s.id:<24} {s.adapter.get('type','-'):<10} {state}{flag}  — {s.name}")
        return 0

    if args.cmd == "feedback":
        path = feedback_path(Path(args.data_dir))
        if not args.posting_id:
            entries = load_feedback(path)
            print(f"피드백 {len(entries)}건 ({path})")
            for e in entries[-20:]:
                print(f"  {e['at'][:10]} {e['id']} {e['label']} {e.get('note','')}")
            return 0
        if not args.label:
            print("label 필요: " + ", ".join(LABELS), file=sys.stderr)
            return 2
        p = next((x for x in store.values() if x.id == args.posting_id), None)
        if p is None:
            print(f"공고 id 없음: {args.posting_id}", file=sys.stderr)
            return 2
        append_feedback(path, args.posting_id, args.label, args.note, now)
        print(f"기록: {p.org_name} · {p.title} → {args.label}. 다음 collect 실행 시 반영됩니다.")
        return 0

    if args.cmd == "eval":
        return _eval(bundle, Path(args.labeled), use_llm=args.llm)

    if args.cmd == "stats":
        print(compute_stats(store.values(), now, args.days).to_markdown())
        return 0

    if args.cmd == "site":
        info = build_site(list(store.values()), Path(args.reports_dir), Path(args.out), now)
        print(f"[site] {args.out}/ 생성 · 활성 공고 {info['active']}건 · 리포트 {info['reports']}개")
        return 0

    if args.cmd == "status":
        by = {s.value: 0 for s in Status}
        for p in store.values():
            by[p.status.value] += 1
        print(f"공고 {len(store.postings)}건 · " + " · ".join(f"{k} {v}" for k, v in by.items()))
        print(f"마지막 수집 {store.state.get('last_run_at', '-')} · 마지막 보고 {store.state.get('last_report_at', '-')}")
        return 0
    return 1


def _eval(bundle, labeled: Path, use_llm: bool) -> int:
    """라벨 세트에 파이프라인과 같은 판별 정책을 적용해 정밀도·재현율을 계산한다."""
    import json

    from .classify.rules import score_posting

    cs = bundle.settings.classifier
    rows = [json.loads(l) for l in labeled.read_text(encoding="utf-8").splitlines() if l.strip()]
    llm = None
    if use_llm:
        llm = LlmClassifier(cs.model_copy(update={"llm_enabled": True}), client=__import__("anthropic").Anthropic()) if os.environ.get("ANTHROPIC_API_KEY") else None
        if llm is None:
            print("ANTHROPIC_API_KEY 없음: 규칙만 평가", file=sys.stderr)
    tp = fp = fn = tn = 0
    wrong: list[str] = []
    for r in rows:
        rule = score_posting(r["title"], r.get("body", ""), r.get("region_text"), r.get("org_name"))
        pred = rule.score >= cs.include_threshold or (rule.score >= cs.review_threshold and cs.include_review_without_llm and llm is None)
        if llm is not None and rule.score >= cs.review_threshold:
            ext = llm.classify(r["title"], r.get("org_name", ""), "unknown", r.get("body", ""), r.get("region_text"))
            if ext is not None:
                pred = ext.is_instructor_job
            elif rule.score < cs.include_threshold:
                pred = cs.include_review_without_llm
        truth = bool(r["label"])
        if pred and truth:
            tp += 1
        elif pred and not truth:
            fp += 1
            wrong.append(f"오탐 {r['id']} ({rule.score}) {r['title']}")
        elif not pred and truth:
            fn += 1
            wrong.append(f"미탐 {r['id']} ({rule.score}) {r['title']}")
        else:
            tn += 1
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    print(f"평가 {len(rows)}건 · 정밀도 {precision:.2f} · 재현율 {recall:.2f} · F1 {f1:.2f} · (TP {tp} FP {fp} FN {fn} TN {tn})" + (f" · LLM 호출 {llm.usage.calls}" if llm else ""))
    for w in wrong:
        print("  " + w)
    ok = precision >= 0.9 and recall >= 0.85
    print("목표(정밀도 ≥ 0.90, 재현율 ≥ 0.85): " + ("충족" if ok else "미달"))
    return 0 if ok else 1


def _save_fixture(cfg, http: HttpClient, out_dir: Path) -> None:
    """설정된 목록 URL/엔드포인트의 원본 응답을 저장한다 (셀렉터·field_map 결정용)."""
    from .collectors.base import substitute_placeholders
    from .config import resolve_env

    a = cfg.adapter
    out_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.now(KST).date()
    if a.get("type") == "api_json" and str(a.get("endpoint", "")).upper() != "TODO":
        ra = substitute_placeholders(resolve_env(a), today, today - timedelta(days=14))
        params = dict(ra.get("params") or {})
        paging = ra.get("paging") or {}
        if paging.get("page_param"):
            params[paging["page_param"]] = 1
        if paging.get("size_param"):
            params[paging["size_param"]] = int(paging.get("size") or 100)
        r = http.get(ra["endpoint"], params=params)
        ext = "xml" if (ra.get("format") or "json") == "xml" else "json"
        (out_dir / f"list.{ext}").write_bytes(r.content)
        print(f"[probe] 저장: {out_dir / f'list.{ext}'} ({len(r.content)} bytes, HTTP {r.status_code})")
    elif a.get("type") == "html_list" and str(a.get("list_url", "")).upper() != "TODO":
        url = str(a["list_url"]).replace("{page}", "1")
        r = http.get(url)
        (out_dir / "list.html").write_bytes(r.content)
        print(f"[probe] 저장: {out_dir / 'list.html'} ({len(r.content)} bytes, HTTP {r.status_code}, charset {r.encoding})")
    else:
        print("[probe] list_url/endpoint 가 TODO 라서 저장할 수 없음")


if __name__ == "__main__":
    sys.exit(main())
