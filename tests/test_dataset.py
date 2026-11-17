import json

import pytest

from rag_calorvia.evaluation.coverage import evidence_status, question_coverage
from rag_calorvia.evaluation.dataset import align_with_registry, is_test, judge_sample, load_questions


def q(id_, type_="factual", evidence=(), traps=()):
    return {"id": id_, "type": type_, "evidence": list(evidence), "traps": list(traps)}


@pytest.fixture
def eval_file(tmp_path):
    path = tmp_path / "eval.json"
    path.write_text(json.dumps([q(f"Q{i:03d}") for i in range(1, 21)]), encoding="utf-8")
    return path


def test_multiples_of_5_are_the_test_set():
    assert is_test("Q005") and is_test("Q155")
    assert not is_test("Q001") and not is_test("Q156")


def test_dev_split_by_default(eval_file):
    ids = [x["id"] for x in load_questions(path=eval_file)]
    assert len(ids) == 16 and "Q005" not in ids


def test_test_set_needs_explicit_permission(eval_file):
    with pytest.raises(PermissionError):
        load_questions("test", path=eval_file)
    assert len(load_questions("test", allow_test=True, path=eval_file)) == 4
    assert len(load_questions("all", allow_test=True, path=eval_file)) == 20


def test_judge_sample_takes_the_first_two_of_each_type():
    questions = [q("Q003", "a"), q("Q001", "a"), q("Q002", "a"), q("Q004", "b")]
    assert [x["id"] for x in judge_sample(questions)] == ["Q001", "Q002", "Q004"]


REGISTRY = {
    "05_Commercial/Tarifs/Tarif 2026.xlsx": {"duplicate_of": None, "excluded_reason": None, "source_type": "table"},
    "99_Archives/Doublons/Copie de Tarif 2026.xlsx": {
        "duplicate_of": "05_Commercial/Tarifs/Tarif 2026.xlsx", "excluded_reason": "duplicate", "source_type": "table"},
    "03_Production/Procedures/MO-SEN-12 Test d_etancheite Aeris.pdf": {
        "duplicate_of": None, "excluded_reason": None, "source_type": "text"},
    "02_RH/Organigrammes/Organigramme direction 2026-04.png": {
        "duplicate_of": None, "excluded_reason": None, "source_type": "image"},
    "02_RH/Confidentiel/Entretiens annuels 2025 - synthese.xlsx": {
        "duplicate_of": None, "excluded_reason": "personal_data", "source_type": "table"},
}


def ev(document, snippets=("x",), fact=0, grade=2):
    return {"document": document, "snippets": list(snippets), "grade": grade, "fact": fact}


def test_duplicates_are_mapped_to_the_kept_copy_and_merged():
    question = q("Q001", evidence=[ev("99_Archives/Doublons/Copie de Tarif 2026.xlsx", ["7 130"]),
                                   ev("05_Commercial/Tarifs/Tarif 2026.xlsx", ["7 130"])])
    [aligned] = align_with_registry([question], REGISTRY)
    assert aligned["evidence"] == [ev("05_Commercial/Tarifs/Tarif 2026.xlsx", ["7 130"])]


def test_apostrophes_follow_the_corpus_file_names():
    question = q("Q001", evidence=[ev("03_Production/Procedures/MO-SEN-12 Test d'etancheite Aeris.pdf")])
    [aligned] = align_with_registry([question], REGISTRY)
    assert aligned["evidence"][0]["document"] == "03_Production/Procedures/MO-SEN-12 Test d_etancheite Aeris.pdf"


def test_traps_are_aligned_too():
    question = q("Q001", traps=[{"document": "99_Archives/Doublons/Copie de Tarif 2026.xlsx", "snippets": ["v1"]}])
    [aligned] = align_with_registry([question], REGISTRY)
    assert aligned["traps"][0]["document"] == "05_Commercial/Tarifs/Tarif 2026.xlsx"


def test_evidence_status():
    def text(path):  # images have no text until they are transcribed
        return "" if path.endswith(".png") else "Tarif 2026 · Aéris 6 : 7 130 €"
    assert evidence_status(ev("05_Commercial/Tarifs/Tarif 2026.xlsx", ["7130"]), REGISTRY, text) == "found"
    assert evidence_status(ev("05_Commercial/Tarifs/Tarif 2026.xlsx", ["9999"]), REGISTRY, text) == "not_in_text"
    assert evidence_status(ev("02_RH/Organigrammes/Organigramme direction 2026-04.png"), REGISTRY, text) == "needs_vision"
    assert evidence_status(ev("02_RH/Confidentiel/Entretiens annuels 2025 - synthese.xlsx"), REGISTRY, text) == "excluded"
    assert evidence_status(ev("nowhere.docx"), REGISTRY, text) == "missing"


def test_a_question_is_reachable_only_if_every_fact_is_found():
    question = q("Q001", evidence=[ev("05_Commercial/Tarifs/Tarif 2026.xlsx", ["7130"], fact=0),
                                   ev("02_RH/Organigrammes/Organigramme direction 2026-04.png", fact=1)])
    reachable, statuses = question_coverage(question, REGISTRY, lambda path: "" if path.endswith(".png") else "7 130")
    assert not reachable and statuses == {"found": 1, "needs_vision": 1}


def test_a_transcribed_image_is_checked_like_text():
    image = ev("02_RH/Organigrammes/Organigramme direction 2026-04.png", ["Céline Moreau"])
    assert evidence_status(image, REGISTRY, lambda path: "Achats : Céline Moreau") == "found"
    assert evidence_status(image, REGISTRY, lambda path: "Achats : C. Moreau") == "not_in_text"


def test_split_of_a_config():
    from rag_calorvia.evaluation.runner import split_of
    assert split_of({"name": "time_rules"}) == "dev"  # every tuning run, and every config stored so far
    assert split_of({"name": "time_rules__test", "evaluation": {"split": "test"}}) == "test"
