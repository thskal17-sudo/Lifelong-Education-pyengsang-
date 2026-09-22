from datetime import timedelta
from types import SimpleNamespace

import httpx

from gia.classify.llm import Extraction, LlmClassifier, LlmUsage
from gia.collectors.base import HttpClient
from gia.config import ClassifierSettings, ConfigBundle
from gia.pipeline import apply_extraction, collect
from gia.store import Store
from tests.conftest import FIXTURES, NOW, make_posting, make_source


class FakeMessages:
    """client.beta.messages 흉내: 제목에 따라 정해진 Extraction을 돌려준다."""

    def __init__(self, decide):
        self.decide = decide
        self.calls = []

    def parse(self, **kw):
        self.calls.append(kw)
        prompt = kw["messages"][0]["content"]
        result = self.decide(prompt)
        usage = SimpleNamespace(input_tokens=1200, output_tokens=150, cache_read_input_tokens=1000 if len(self.calls) > 1 else 0)
        if result == "refusal":
            return SimpleNamespace(stop_reason="refusal", parsed_output=None, usage=usage)
        return SimpleNamespace(stop_reason="end_turn", parsed_output=result, usage=usage)

    def create(self, **kw):
        self.calls.append(kw)
        return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text="오늘은 평생교육 분야가 많습니다.")], usage=SimpleNamespace(input_tokens=300, output_tokens=40, cache_read_input_tokens=0))


def fake_client(decide):
    return SimpleNamespace(beta=SimpleNamespace(messages=FakeMessages(decide)))


def _settings(**kw):
    kw.setdefault("llm_model", "claude-opus-5")
    return ClassifierSettings(llm_enabled=True, **kw)


def test_classify_returns_extraction_and_accounts_usage():
    ext = Extraction(is_instructor_job=True, confidence=0.9, field="sports", employment_type="시간강사", deadline="2026-10-01T18:00:00", one_line_summary="창원 수영강사 시간제 모집")
    client = fake_client(lambda prompt: ext)
    llm = LlmClassifier(_settings(), client=client)
    out = llm.classify("수영강사 모집", "창원시설공단", "local_public", "본문", None)
    assert out is ext
    assert out.deadline_datetime().isoformat() == "2026-10-01T18:00:00+09:00"
    assert llm.usage.calls == 1 and llm.usage.input_tokens == 1200
    kw = client.beta.messages.calls[0]
    assert kw["model"] == "claude-opus-5" and kw["output_format"] is Extraction
    assert kw["fallbacks"] == "default" and "server-side-fallback-2026-07-01" in kw["betas"]
    assert kw["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert kw["output_config"] == {"effort": "low"}


def test_refusal_budget_and_errors():
    llm = LlmClassifier(_settings(llm_max_calls_per_run=1), client=fake_client(lambda p: "refusal"))
    assert llm.classify("a", "b", "portal", "c") is None and llm.usage.refusals == 1
    assert llm.remaining == 0 and llm.classify("a", "b", "portal", "c") is None  # 상한

    def boom(_):
        raise RuntimeError("api down")
    llm2 = LlmClassifier(_settings(), client=fake_client(boom))
    assert llm2.classify("a", "b", "portal", "c") is None and llm2.usage.errors == 1


def test_no_fallback_params_for_other_models():
    llm = LlmClassifier(_settings(llm_model="claude-sonnet-5"), client=fake_client(lambda p: Extraction(is_instructor_job=True, confidence=1)))
    llm.classify("a", "b", "portal", "c")
    assert "fallbacks" not in llm._client.beta.messages.calls[0]


def test_apply_extraction_fills_missing_fields():
    p = make_posting("강사 모집", flags=["판별유보"], relevance_score=45)
    apply_extraction(p, Extraction(is_instructor_job=True, confidence=0.8, field="lifelong", employment_type="프리랜서", deadline="2026-09-30", work_location="김해", qualifications=["평생교육사"], pay="시간당 5만원", one_line_summary="김해 시민강좌 강사"))
    assert p.field == "lifelong" and p.employment_type == "프리랜서" and p.region == ["김해"]
    assert p.deadline.isoformat() == "2026-09-30T00:00:00+09:00"
    assert "판별유보" not in p.flags and p.relevance_score == 70 and p.pay == "시간당 5만원"


def test_pipeline_llm_stage_excludes_and_enriches(settings, tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_GO_KR_KEY", "k")
    settings.classifier = _settings()
    api = make_source("gojobs", "portal", type="api_json", endpoint="https://api.example.org/list", items_path="result",
                      params={"serviceKey": "${DATA_GO_KR_KEY}"},
                      field_map={"title": "recrutPbancTtl", "org_name": "instNm", "posted_at": "pbancBgngYmd", "deadline": "pbancEndYmd", "region": "workRgnNmLst", "url": "srcUrl", "body": "body"},
                      region_filter="@gyeongnam", detail={"fetch": False})
    bundle = ConfigBundle(settings=settings, sources=[api], aliases={})

    def handler(request):
        return httpx.Response(200, content=(FIXTURES / "api_list.json").read_bytes(), headers={"content-type": "application/json"})
    http = HttpClient(settings.collector, transport=httpx.MockTransport(handler))

    def decide(prompt):
        if "운영 담당자" in prompt:
            return Extraction(is_instructor_job=False, confidence=0.95, exclusion_reason="강사 아님")
        return Extraction(is_instructor_job=True, confidence=0.9, field="vocational", employment_type="시간강사", pay="시간당 4만원", one_line_summary="창원 폴리텍 전기 시간강사")
    llm = LlmClassifier(settings.classifier, client=fake_client(decide))
    store = Store(tmp_path / "data")
    run = collect(bundle, store, http, now=NOW, llm=llm)

    titles = [p.title for p in store.values()]
    assert titles == ["2026-2학기 시간강사(전기) 모집"]  # 운영 담당자(판단 유보 60점)는 LLM이 제외, 사무보조는 규칙(5점)이 제외
    p = store.values().__iter__().__next__()
    assert p.one_line_summary == "창원 폴리텍 전기 시간강사" and p.field == "vocational" and p.llm_confidence == 0.9
    assert run.llm_calls == 2 and run.llm_excluded == 1 and run.llm_cache_read_tokens == 1000
    assert "https://example.org/job/4" in store.excluded_urls and "https://example.org/job/3" in store.excluded_urls


def test_summarize_day():
    llm = LlmClassifier(_settings(), client=fake_client(lambda p: None))
    assert llm.summarize_day(["[lifelong] 김해시 · 강사 모집"]) == "오늘은 평생교육 분야가 많습니다."
    assert llm.summarize_day([]) is None
