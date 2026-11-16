"""Hand-made cases for the metrics: each expected value can be checked on paper. Ported from exercise 3."""
import math

import pytest

from rag_calorvia.evaluation.metrics import (
    answer_scores,
    chunk_body,
    cited_passages,
    is_refusal,
    jaccard,
    judge_chunk,
    normalize,
    normalize_numbers,
    redundancy_scores,
    retrieval_scores,
    shingles,
)

# Two complementary facts (0 and 1); fact 0 has two interchangeable sources; one useful-only passage (grade 1)
QUESTION = {
    "evidence": [
        {"document": "codir_0209.docx", "snippets": ["reportée au 1er juin 2026"], "grade": 2, "fact": 0},
        {"document": "copil_05.docx", "snippets": ["go-live le 1er juin"], "grade": 2, "fact": 0},
        {"document": "codir_0518.docx", "snippets": ["Gand le 15 juin"], "grade": 2, "fact": 1},
        {"document": "newsletter.html", "snippets": ["projet Atlas"], "grade": 1, "fact": None},
    ],
    "traps": [{"document": "codir_1201.docx", "snippets": ["fixée au 1er avril 2026"]}],
}


def chunk(document, text):
    return {"document": document, "text": text}


NOISE = chunk("x.docx", "Menu du restaurant de Seneffe")
TRAP = chunk("codir_1201.docx", "La mise en production est fixée au 1er avril 2026.")


# --- normalization --------------------------------------------------------------------------------
@pytest.mark.parametrize("raw, expected", [
    ("4 568 unités", "4568 unités"),
    ("4 568", "4568"),            # no-break space, as Excel and Word write it
    ("1 250 000 €", "1250000 €"),  # narrow no-break space
    ("41,5 %", "41.5 %"),
    ("du 13 au 28 novembre", "du 13 au 28 novembre"),  # two numbers, not a thousands group
])
def test_normalize_numbers(raw, expected):
    assert normalize_numbers(raw) == expected


def test_normalize_ignores_whitespace_and_number_rendering():
    assert normalize("Production :\n 4 568  unités, TRS 81,4 %") == normalize("Production : 4568 unités, TRS 81.4 %")


# --- judge_chunk ------------------------------------------------------------------------------------
def test_judge_chunk_needs_the_right_document():
    # The same sentence recalled in another document proves nothing
    assert judge_chunk(chunk("codir_0209.docx", "La date est reportée au 1er juin 2026."), QUESTION) == [0]
    assert judge_chunk(chunk("newsletter.html", "La date est reportée au 1er juin 2026."), QUESTION) == []


def test_judge_chunk_needs_every_snippet():
    question = {"evidence": [{"document": "r.xlsx", "snippets": ["Flandre", "4568"], "grade": 2, "fact": 0}]}
    assert judge_chunk(chunk("r.xlsx", "Région : Flandre · CA : 4 568 k€"), question) == [0]
    assert judge_chunk(chunk("r.xlsx", "Région : Flandre · CA : 3 990 k€"), question) == []


# --- retrieval metrics ------------------------------------------------------------------------------
def test_one_fact_found_at_rank_2():
    scores = retrieval_scores([NOISE, chunk("codir_0209.docx", "reportée au 1er juin 2026"), NOISE], QUESTION, top_k=3)
    assert scores["hit@3"] == 1
    assert scores["mrr@3"] == 0.5
    assert scores["recall@3"] == 0.5  # fact 0 found, fact 1 (Ghent) missing


def test_interchangeable_sources_count_as_one_fact():
    chunks = [chunk("codir_0209.docx", "reportée au 1er juin 2026"), chunk("copil_05.docx", "go-live le 1er juin"), NOISE]
    assert retrieval_scores(chunks, QUESTION, top_k=3)["recall@3"] == 0.5


def test_all_facts_found():
    chunks = [chunk("codir_0518.docx", "puis Gand le 15 juin"), chunk("copil_05.docx", "go-live le 1er juin"), NOISE]
    scores = retrieval_scores(chunks, QUESTION, top_k=3)
    assert scores["recall@3"] == 1
    assert scores["mrr@3"] == 1


def test_grade_1_alone_is_not_a_hit():
    scores = retrieval_scores([chunk("newsletter.html", "Le projet Atlas avance"), NOISE, NOISE], QUESTION, top_k=3)
    assert scores["hit@3"] == 0 and scores["recall@3"] == 0
    assert scores["ndcg@3"] > 0  # but nDCG gives it some credit


def test_ndcg_by_hand():
    # Only the grade-1 chunk, at rank 2: DCG = 1/log2(3); ideal top 3 = grades 2, 2, 2
    scores = retrieval_scores([NOISE, chunk("newsletter.html", "projet Atlas"), NOISE], QUESTION, top_k=3)
    ideal = 2 / math.log2(2) + 2 / math.log2(3) + 2 / math.log2(4)
    assert scores["ndcg@3"] == pytest.approx((1 / math.log2(3)) / ideal)


def test_duplicate_chunks_are_credited_once():
    same = chunk("codir_0209.docx", "reportée au 1er juin 2026")
    chunks = [same, same, same, chunk("copil_05.docx", "go-live le 1er juin"), chunk("codir_0518.docx", "Gand le 15 juin")]
    assert retrieval_scores(chunks, QUESTION, top_k=5)["ndcg@5"] <= 1


def test_metrics_only_up_to_top_k():
    scores = retrieval_scores([NOISE] * 5, QUESTION, top_k=5)
    expected = {f"{m}@{k}" for m in ("hit", "mrr", "recall", "ndcg", "trap_hit") for k in (3, 5)}
    assert set(scores) == expected


# --- traps --------------------------------------------------------------------------------------------
def test_trap_hit_depends_on_rank():
    scores = retrieval_scores([NOISE, NOISE, NOISE, TRAP, NOISE], QUESTION, top_k=5)
    assert scores["trap_hit@3"] == 0
    assert scores["trap_hit@5"] == 1


def test_trap_needs_its_document():
    # The new value's minute recalling the old value is not the trap: only the outdated document is
    recall_in_new_minute = chunk("codir_0209.docx", "Pour rappel, la mise en production était fixée au 1er avril 2026.")
    assert retrieval_scores([recall_in_new_minute], QUESTION, top_k=3)["trap_hit@3"] == 0


def test_no_trap_score_without_traps():
    question = {"evidence": QUESTION["evidence"], "traps": []}
    assert not any(k.startswith("trap_hit") for k in retrieval_scores([TRAP], question, top_k=3))


def test_out_of_corpus_has_no_retrieval_score():
    assert retrieval_scores([NOISE] * 5, {"evidence": [], "traps": []}, top_k=5) == {}


# --- answers ------------------------------------------------------------------------------------------
def test_refusal_is_the_strict_sentence_whatever_the_case():
    assert is_refusal("Je ne sais pas.")
    assert is_refusal("JE NE SAIS PAS")
    assert not is_refusal("L'ERP démarre le 1er juin 2026.")


def test_answer_and_citation_scores():
    assert answer_scores("Je ne sais pas.", [], QUESTION) == {"refusal": 1.0}
    chunks = [NOISE, chunk("codir_0209.docx", "reportée au 1er juin 2026"), NOISE]
    # [2] exists and is relevant, [3] exists but is noise, [7] doesn't exist
    scores = answer_scores("Le 1er juin 2026 [2][3][7].", chunks, QUESTION)
    assert scores["citation_valid"] == pytest.approx(2 / 3)
    assert scores["citation_relevant"] == 0.5
    assert cited_passages("Le 1er juin [2], Gand le 15 [1][3].") == {1, 2, 3}


# --- redundancy ---------------------------------------------------------------------------------------
def test_chunk_body_strips_the_context_line():
    text = "[PV du CODIR du 13 octobre 2025 · 00_Direction/CODIR/2025]\nLe CODIR valide la hausse de 3,5 %."
    assert chunk_body(text) == "Le CODIR valide la hausse de 3,5 %."
    assert chunk_body("[1] n'est pas une ligne de contexte\nsuite") == "[1] n'est pas une ligne de contexte\nsuite"


def test_jaccard():
    assert jaccard(shingles("a b c d"), shingles("a b c d")) == 1
    assert jaccard(shingles("a b c d"), shingles("e f g h")) == 0
    assert jaccard(shingles("a b c d"), shingles("a b c e")) == 1 / 3  # {abc, bcd} vs {abc, bce}


def test_same_text_in_two_documents_is_redundant():
    # Unlike the hospital, there is no per-patient scope: the same paragraph in two files is a duplicate
    same = "À propos de Calorvia : fabricant belge de pompes à chaleur et de groupes de ventilation."
    chunks = [chunk("cp_fr.docx", "[CP]\n" + same), chunk("cp_l4.docx", "[CP L4]\n" + same)]
    fillers = ["Budget approuvé par le CA.", "Vitesse limitée à six km/h.", "Présérie de la ligne L4 en juin."]
    chunks += [chunk(f"d{i}.docx", text) for i, text in enumerate(fillers)]  # no shingle in common with anything
    scores = redundancy_scores(chunks, top_k=5)
    assert scores["near_duplicates@5"] == 1
    assert scores["redundancy@5"] == 1 / 10  # one identical pair out of 10
    assert scores["documents@5"] == 5


def test_redundancy_only_up_to_top_k():
    assert set(redundancy_scores([NOISE] * 3, top_k=3)) == set()
    assert {k.split("@")[1] for k in redundancy_scores([NOISE] * 10, top_k=10)} == {"5", "10"}
