"""The experiment comparison page: its logic as functions, then the page itself in local mode."""
from pathlib import Path

import psycopg
import pytest
from streamlit.testing.v1 import AppTest

from rag_calorvia.config import settings
from rag_calorvia.evaluation import compare

PAGE = str(Path(__file__).parents[1] / "app" / "experiments.py")
QUESTIONS = [{"id": "Q1", "type": "factual", "evidence": []}, {"id": "Q2", "type": "multilingual", "evidence": []},
             {"id": "Q3", "type": "factual", "evidence": []}]
SCORES = {"a": {"Q1": {"recall@5": 1.0, "trap_hit@5": 1.0}, "Q2": {"recall@5": 0.5}, "Q3": {"recall@5": 1.0}},
          "b": {"Q1": {"recall@5": 1.0, "trap_hit@5": 0.0}, "Q2": {"recall@5": 1.0}, "Q3": {"recall@5": 1.0}}}


def test_the_metric_table_has_one_row_per_group_and_all_last():
    rows = compare.metric_table(SCORES, QUESTIONS, {}, "recall@5", "type")
    assert [r["group"] for r in rows] == ["factual", "multilingual", "all"]
    assert rows[1]["a"] == 0.5 and rows[1]["b"] == 1.0 and rows[-1]["a n"] == 3
    assert [r["group"] for r in compare.metric_table(SCORES, QUESTIONS, {}, "recall@5", "all")] == ["all"]


def test_the_best_run_respects_the_metric_direction_and_ties():
    assert compare.best_run({"a": 0.5, "b": 1.0}, ["a", "b"], "recall@5") == "b"
    assert compare.best_run({"a": 1.0, "b": 0.0}, ["a", "b"], "trap_hit@5") == "b"   # lower is better
    assert compare.best_run({"a": 1.0, "b": 1.0}, ["a", "b"], "recall@5") is None     # a tie names no one
    assert compare.best_run({"a": 1.0, "b": None}, ["a", "b"], "recall@5") is None    # one value is no comparison


def test_only_the_questions_that_changed_are_listed():
    assert compare.question_diffs(SCORES, "recall@5", QUESTIONS) == [
        {"question": "Q2", "type": "multilingual", "a": 0.5, "b": 1.0}]
    assert [d["question"] for d in compare.question_diffs(SCORES, "trap_hit@5", QUESTIONS)] == ["Q1"]


def test_the_settings_diff_shows_only_what_differs():
    prompt = "x" * 500
    diff = compare.config_diff({
        "a": {"name": "a", "search": {"top_k": 5, "translate": ["nl"]}, "generation": {"system_prompt_text": prompt}},
        "b": {"name": "b", "search": {"top_k": 5}, "generation": {"system_prompt_text": prompt + "y"}}})
    assert [d["setting"] for d in diff] == ["generation.system_prompt_text", "search.translate"]   # not name, not top_k
    assert diff[1] == {"setting": "search.translate", "a": '["nl"]', "b": "(absent)"}
    assert diff[0]["a"].startswith("500 characters, sha ")                                   # a prompt by its hash


def test_text_to_sql_lists_questions_right_in_one_run_and_wrong_in_another():
    results = {1: {"E01": {"ok": True, "category": "simple_erp"}, "E02": {"ok": True, "category": "simple_erp"}},
               2: {"E01": {"ok": False, "category": "simple_erp"}, "E02": {"ok": True, "category": "simple_erp"}}}
    assert compare.t2sql_diffs(results) == [{"question": "E01", "category": "simple_erp", 1: "✓", 2: "✗"}]


@pytest.fixture
def results_database():
    try:
        with psycopg.connect(settings.postgres_url, connect_timeout=3) as conn:
            conn.execute("SELECT 1 FROM experiments LIMIT 1")
    except psycopg.Error:
        pytest.skip("the course PostgreSQL (5432) is not running")


def test_the_page_opens_on_the_final_and_the_configuration_in_use(results_database):
    at = AppTest.from_file(PAGE, default_timeout=120).run()   # local mode: .env sets no API_KEYS
    assert not at.exception
    chosen = [m for m in at.multiselect if m.label == "Compare"][0]
    labels = [chosen.format_func(v) for v in chosen.value]
    assert any("status_filter__retrieval" in label for label in labels)
    assert any("★ in use" in label for label in labels)


def test_the_page_asks_for_an_admin_key_once_keys_are_set(results_database, monkeypatch):
    from text2sql_calorvia.config import settings as agent_settings
    monkeypatch.setattr(agent_settings, "api_keys", "alice:key-a")
    at = AppTest.from_file(PAGE, default_timeout=60).run()
    assert at.text_input[0].label == "Access key" and not at.dataframe
