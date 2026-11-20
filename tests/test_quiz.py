"""The quiz game: questions from QUIZ.md and the YAML files, grading, XP that can't be farmed, redo, phases, page."""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from labo_quiz import engine
from labo_quiz.engine import Progress, Question, grade, level, pick, stats

PAGE = str(Path(__file__).parents[1] / "app" / "quiz.py")


@pytest.fixture
def progress(tmp_path):
    return Progress(tmp_path / "progress.json")


def q(qid, kind="choice", phase="A", **kw):
    return Question(id=qid, phase=phase, section=kw.pop("section", "step-01"), title="t", kind=kind, prompt="?",
                    explain="because", **kw)


# --- the question bank --------------------------------------------------------------------------------------------
def test_every_quiz_md_question_and_every_overlay_is_loaded():
    questions = engine.load_questions()
    quiz_md = Path(engine.QUIZ_MD).read_text(encoding="utf-8").count("<summary>Answer</summary>")
    assert sum(1 for x in questions if x.phase != engine.CODE_PHASE) == quiz_md
    ids = {x.id for x in questions}
    assert len(ids) == len(questions)
    import yaml
    assert set(yaml.safe_load(Path(engine.CHOICES).read_text())) <= ids          # no overlay points nowhere
    assert {x.phase for x in questions} == set(engine.PHASES)


def test_code_questions_are_well_formed():
    for x in (x for x in engine.load_questions() if x.phase == engine.CODE_PHASE):
        assert x.node and x.explain and x.files, x.id
        if x.kind == "order":
            assert len(x.correct) >= 3
        elif x.kind == "match":
            assert len(x.pairs) >= 3 and len({r for _, r in x.pairs}) == len(x.pairs)   # each right side once
        else:
            assert x.correct and x.wrong and not set(x.correct) & set(x.wrong)


def test_options_are_shuffled_the_same_way_every_time():
    x = q("x", correct=["right"], wrong=["a", "b", "c"])
    assert x.options() == x.options() and sorted(x.options()) == ["a", "b", "c", "right"]


# --- grading ------------------------------------------------------------------------------------------------------
def test_each_kind_is_graded():
    assert grade(q("c", correct=["r"], wrong=["w"]), "r") == "right"
    assert grade(q("c", correct=["r"], wrong=["w"]), "w") == "wrong"
    multi = q("m", kind="multi", correct=["a", "b"], wrong=["c"])
    assert grade(multi, ["b", "a"]) == "right" and grade(multi, ["a"]) == "wrong" and grade(multi, ["a", "b", "c"]) == "wrong"
    order = q("o", kind="order", correct=["1", "2", "3"])
    assert grade(order, ["1", "2", "3"]) == "right" and grade(order, ["2", "1", "3"]) == "wrong"
    match = q("p", kind="match", pairs=[["x", "1"], ["y", "2"]])
    assert grade(match, {"x": "1", "y": "2"}) == "right" and grade(match, {"x": "2", "y": "1"}) == "wrong"
    with pytest.raises(ValueError):
        grade(q("open", kind="open"), "anything")


# --- XP and progress ----------------------------------------------------------------------------------------------
def test_xp_rewards_progress_not_replays(progress):
    assert progress.record("a", "right") == 10                # first try
    assert progress.record("a", "right") == 0                 # replaying a known question earns nothing
    assert progress.record("b", "wrong") == 0
    assert progress.record("b", "right") == 5                 # right after a miss
    assert progress.record("c", "partial") == 3
    assert progress.record("c", "right") == 2                 # the rest of the retry points
    assert progress.record("c", "wrong") == 0 and progress.state("c")["best"] == "right"
    assert progress.xp == 20


def test_a_streak_of_five_earns_a_bonus_and_a_miss_resets_it(progress):
    for i in range(4):
        progress.record(f"s{i}", "right")
    assert progress.record("s4", "right") == 10 + 10 and progress.streak == 5
    progress.record("s5", "wrong")
    assert progress.streak == 0 and progress.best_streak == 5


def test_progress_survives_a_restart(progress):
    progress.record("a", "right")
    again = Progress(progress.path)
    assert again.xp == 10 and again.state("a")["attempts"] == 1 and len(again.history) == 1


def test_redo_failed_keeps_only_questions_last_answered_wrong_or_partly(progress):
    questions = [q("a"), q("b"), q("c"), q("d", phase="B")]
    progress.record("a", "right")
    progress.record("b", "wrong")
    progress.record("c", "partial")
    assert [x.id for x in pick(questions, progress, "failed")] == ["b", "c"]
    assert [x.id for x in pick(questions, progress, "new")] == ["d"]
    assert [x.id for x in pick(questions, progress, "all", phases=["B"])] == ["d"]
    progress.record("b", "right")
    assert [x.id for x in pick(questions, progress, "failed")] == ["c"]


def test_a_phase_is_mastered_when_every_question_was_tried_and_80_percent_are_right(progress):
    questions = [q(f"q{i}") for i in range(5)]
    for i in range(4):
        progress.record(f"q{i}", "right")
    assert not stats(questions, progress, lambda x: x.phase)["A"]["mastered"]   # one never tried
    progress.record("q4", "wrong")
    s = stats(questions, progress, lambda x: x.phase)["A"]
    assert s["mastered"] and s["mastery"] == 0.8
    assert ("🏅", "Phase A mastered") in [(b[0], b[1]) for b in engine.badges(questions, progress)]


def test_levels():
    assert level(0)[:2] == (1, "Stagiaire") and level(150)[:3] == (2, "Analyste", 50)
    assert level(10_000)[3] is None                          # the top level has no next


# --- the page ---------------------------------------------------------------------------------------------------
def test_the_page_opens_and_plays_a_question(tmp_path, monkeypatch):
    monkeypatch.setenv("QUIZ_PROGRESS", str(tmp_path / "progress.json"))
    at = AppTest.from_file(PAGE, default_timeout=60).run()
    assert not at.exception
    at.button(key="start").click().run()
    assert not at.exception and at.session_state["queue"]
