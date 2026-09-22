from datetime import timedelta

from gia.__main__ import main
from gia.feedback import append_feedback, apply_feedback, feedback_path, load_feedback
from gia.models import Status
from gia.report.build import select_postings
from gia.store import Store
from tests.conftest import NOW, make_posting


def test_feedback_hides_posting_and_blocks_recollect(tmp_path, bundle):
    store = Store(tmp_path / "data")
    p = make_posting("강사 모집", deadline=NOW + timedelta(days=10))
    store.upsert(p)
    path = feedback_path(store.data_dir)
    append_feedback(path, p.id, "false_positive", "수강생 모집임", NOW)
    append_feedback(path, "unknown", "false_positive", "", NOW)
    entries = load_feedback(path)
    assert len(entries) == 2
    assert apply_feedback(store, entries, NOW) == 1
    assert apply_feedback(store, entries, NOW) == 0  # 중복 적용 없음
    assert p.status == Status.expired and "피드백제외" in p.flags
    assert p.sources[0].url in store.excluded_urls
    assert select_postings(bundle, store, NOW).new == []


def test_eval_command_on_seed_set(capsys):
    code = main(["--config-dir", "config", "--data-dir", "/nonexistent-data", "eval", "--labeled", "tests/eval/labeled.jsonl"])
    out = capsys.readouterr().out
    assert "정밀도" in out
    assert code == 0, out
