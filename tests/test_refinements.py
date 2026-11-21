"""Step 40: ties in the reranker's scores, a score floor beyond the first 5, the siblings, rule 8, prompt v3."""
from qdrant_client import models

from rag_calorvia.etl.vision import PROMPTS
from rag_calorvia.rag import rerank as rerank_module
from rag_calorvia.rag import siblings as siblings_module
from rag_calorvia.rag.rerank import above_floor, rerank, sort_key
from rag_calorvia.rag.siblings import add_siblings, pick, with_filter


def config(**reranker):
    return {"reranker": {"model": "bge-reranker", **reranker}, "search": {"top_k": 10}}


def test_saturated_scores_keep_the_search_order(monkeypatch):
    """0.9999 and 0.9991 are the same to the reranker: the search's better candidate stays first."""
    chunks = [{"text": f"c{i}"} for i in range(4)]
    monkeypatch.setattr(rerank_module, "score", lambda model, query, texts: [(3, 0.9999), (2, 0.9995), (0, 0.9991), (1, 0.5)])
    assert [c["text"] for c in rerank("q", chunks, config())] == ["c3", "c2", "c0", "c1"]
    assert [c["text"] for c in rerank("q", chunks, config(saturation=0.99))] == ["c0", "c2", "c3", "c1"]


def test_without_saturation_the_order_is_the_score_alone():
    pairs = [(0, 0.2), (1, 0.9), (2, 0.9), (3, 0.95)]
    assert [i for i, _ in sorted(pairs, key=sort_key())] == [3, 1, 2, 0]


def test_the_floor_only_applies_beyond_the_first_chunks():
    top = [{"rerank_score": s} for s in (0.9, 0.05, 0.8, 0.7, 0.6, 0.5, 0.09, 0.1, 0.3, 0.01)]
    kept = above_floor(top, {"min_score": 0.1, "min_score_from": 5})
    assert [c["rerank_score"] for c in kept] == [0.9, 0.05, 0.8, 0.7, 0.6, 0.5, 0.1, 0.3]
    assert above_floor(top, {}) == top


def sibling(document, score, date=None, precision="day"):
    return {"document": document, "rerank_score": score, "doc_date": date, "date_precision": precision if date else None}


def test_siblings_are_the_newest_documents_that_still_score_well():
    scored = [sibling("faq", 0.71), sibling("launch minutes", 0.70, "2025-12-08"), sibling("8D", 0.63, "2025-12-01"),
              sibling("closure minutes", 0.585, "2026-03-02"), sibling("weak", 0.3, "2026-06-01"),
              sibling("yearly", 0.9, "2026-12-31", precision="year")]
    assert [s["document"] for s in pick(scored, 2, 0.5)] == ["closure minutes", "launch minutes"]


def test_siblings_keep_the_question_filter():
    status = models.Filter(must=[models.FieldCondition(key="access", match=models.MatchValue(value="hr"))],
                           must_not=[models.FieldCondition(key="status", match=models.MatchAny(any=["draft"]))])
    combined = with_filter(status, ["a.docx"])
    assert len(combined.must) == 2 and combined.must_not == status.must_not
    assert with_filter(None, ["a.docx"]).must[0].key == "document"


def test_siblings_are_added_after_the_chunks(monkeypatch):
    chunks = [{"document": "pv.docx", "chunk_index": 11, "text": "décisions"}]
    found = [{"document": "pv.docx", "chunk_index": 6, "text": "211 unités sur 214", "doc_date": "2026-03-02",
              "date_precision": "day"},
             {"document": "pv.docx", "chunk_index": 9, "text": "tour de table", "doc_date": "2026-03-02",
              "date_precision": "day"}]
    monkeypatch.setattr(siblings_module, "fetch_siblings", lambda chunks, config, query_filter: found)
    monkeypatch.setattr(siblings_module, "score_in_languages",
                        lambda model, question, texts, versions, indexes: [(0, 0.585), (1, 0.01)])
    out = add_siblings("Où en est le rappel ?", chunks, config(siblings=2))
    assert [c["chunk_index"] for c in out] == [11, 6] and out[1]["sibling"] and out[1]["text"] == "211 unités sur 214"
    assert add_siblings("q", chunks, config()) == chunks   # off by default


def test_rule_8_and_prompt_v3():
    with open("prompts/tools_readings.txt", encoding="utf-8") as f:
        readings = f.read()
    with open("prompts/tools_complete.txt", encoding="utf-8") as f:
        assert readings.startswith(f.read())
    assert "8. Si un mot de la question peut se comprendre de deux façons" in readings
    assert "regroupe chaque case sous la case dont elle dépend" in PROMPTS["v3"]
    assert "N'écris rien pour un lien sans texte" in PROMPTS["v3"]


def test_the_fresh_set_is_held_out_and_never_cites_a_dev_or_test_document():
    """Step 40: a third set, on documents no dev or test question cites; read only when asked for."""
    import json

    import pytest

    from rag_calorvia.evaluation.dataset import load_questions
    with pytest.raises(PermissionError):
        load_questions("fresh")
    fresh = load_questions("fresh", allow_test=True)
    assert len(fresh) == 35 and len({q["id"] for q in fresh}) == 35
    with open("data/calorvia_eval.json", encoding="utf-8") as f:
        cited = {e["document"].replace("'", "_") for q in json.load(f) for e in q["evidence"] + (q.get("traps") or [])}
    # each question's first document; another copy of the same fact may be cited (F028: Q102's monthly report)
    assert not {q["evidence"][0]["document"] for q in fresh if q["evidence"]} & cited
