from datetime import date

import pytest

from rag_calorvia.etl.chunk import context_line, french_date
from rag_calorvia.evaluation.report import evidence_format, summarize


def document(path="00_Direction/CODIR/2025/PV_CODIR_2025-10-13.docx", label="PV du CODIR", start=date(2025, 10, 13),
             end=None, precision="day", source="filename"):
    return {"path": path, "doc_label": label, "doc_date": start, "date_end": end or start,
            "date_precision": precision, "date_source": source}


def test_context_line_of_a_codir_minute():
    assert context_line(document()) == "[PV du CODIR du 13 octobre 2025 · PV_CODIR_2025-10-13 · 00_Direction/CODIR/2025]"


@pytest.mark.parametrize("doc, expected", [
    (document(start=date(2025, 9, 1)), " du 1er septembre 2025"),
    (document(start=date(2026, 3, 1), end=date(2026, 3, 31), precision="month"), " de mars 2026"),
    (document(start=date(2025, 10, 1), end=date(2025, 12, 31), precision="quarter"), " du T4 2025"),
    (document(start=date(2026, 1, 1), end=date(2026, 12, 31), precision="year"), " 2026"),
    (document(start=date(2025, 1, 1), end=date(2026, 12, 31), precision="range"), " 2025-2026"),
    (document(start=date(2026, 3, 11), source="photo"), " prise le 11 mars 2026"),
    (document(start=None), ""),
])
def test_french_dates_follow_the_precision(doc, expected):
    assert french_date(doc) == expected


def test_the_file_name_keeps_what_the_label_cannot_say():
    draft = document(path="00_Direction/Conseil_administration/Projets_PV/Projet PV CA 2025-11-18.docx",
                     label="PV du conseil d'administration", start=date(2025, 11, 18))
    assert "Projet PV CA 2025-11-18" in context_line(draft)


REGISTRY = {
    "a.docx": {"format": "docx", "source_type": "text"},
    "b.xlsx": {"format": "xlsx", "source_type": "table"},
    "s.pdf": {"format": "pdf", "source_type": "scan"},
}


def q(id_, type_, *documents):
    return {"id": id_, "type": type_, "evidence": [{"document": d, "grade": 2, "snippets": [], "fact": 0} for d in documents]}


def test_evidence_format():
    assert evidence_format(q("Q1", "factual", "a.docx"), REGISTRY) == "docx"
    assert evidence_format(q("Q2", "scan_ocr", "s.pdf"), REGISTRY) == "scan"
    assert evidence_format(q("Q3", "multi_doc", "a.docx", "b.xlsx"), REGISTRY) == "mixed"
    assert evidence_format(q("Q4", "out_of_corpus"), REGISTRY) == "none"


def test_summarize_skips_questions_without_the_metric():
    questions = [q("Q1", "factual", "a.docx"), q("Q2", "factual", "a.docx"), q("Q3", "out_of_corpus")]
    scores = {"base": {"Q1": {"recall@5": 1.0}, "Q2": {"recall@5": 0.0}, "Q3": {"refusal": 1.0}}}
    summary = summarize(scores, questions, REGISTRY, "recall@5")
    assert summary["factual"]["base"] == (0.5, 2)
    assert "out_of_corpus" not in summary
    assert summary["all"]["base"] == (0.5, 2)


def test_refusals_are_not_judged_on_faithfulness():
    from rag_calorvia.evaluation.judge import METRIC_NAMES, metrics_for
    question = {"type": "image_only"}
    assert "faithfulness" not in metrics_for(question, "Je ne sais pas.")
    assert "correctness" in metrics_for(question, "Je ne sais pas.")
    assert metrics_for(question, "Le numéro est BRV-19-04417 [1].") == METRIC_NAMES
    assert metrics_for({"type": "out_of_corpus"}, "Je ne sais pas.") == ["correctness"]
