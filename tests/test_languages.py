import pytest

from rag_calorvia.etl.chunk import chunk_language
from rag_calorvia.etl.index import bm25, collection_name, sparse_language
from rag_calorvia.rag import rerank as rerank_module
from rag_calorvia.rag.translate import TRANSLATION_PROMPT, translation_prompt

CONFIG = {"chunking": {"max_tokens": 256, "context_line": True}, "embedder": {"model": "bge-m3"}}


def test_chunk_language_is_detected_on_the_chunk_itself():
    dutch = "Vanaf vandaag geldt een maximumsnelheid van 6 km/u in de gangen van het magazijn."
    assert chunk_language(dutch, "fr") == "nl"  # a Dutch passage in a French document


def test_short_chunks_inherit_their_document_language_then_french():
    assert chunk_language("Néant.", "nl") == "nl"
    assert chunk_language("Néant.", None) == "fr"


def test_bm25_uses_the_stemmer_of_the_language():
    assert bm25("magazijnen", "nl").options["language"] == "dutch"
    assert bm25("entrepôts").options["language"] == "french"   # default: French
    assert bm25("x", "xx").options["language"] == "french"     # unknown language: French


def test_sparse_language_and_collection_name_follow_the_config():
    chunk = {"language": "nl"}
    assert sparse_language(chunk, CONFIG) == "fr"
    per_chunk = {**CONFIG, "sparse": {"language": "per_chunk"}}
    assert sparse_language(chunk, per_chunk) == "nl"
    assert collection_name(CONFIG) == "calorvia__bge-m3__256"
    assert collection_name(per_chunk) == "calorvia__bge-m3__256__bm25-per-language"


def test_parse_translations():
    from rag_calorvia.rag.translate import parse_translations
    content = '{"nl": "Wat is de maximumsnelheid in Gent?", "en": "What is the speed limit in Ghent?", "de": "x"}'
    assert parse_translations(content, ["nl", "en"]) == {
        "nl": "Wat is de maximumsnelheid in Gent?", "en": "What is the speed limit in Ghent?"}  # 'de' not asked
    assert parse_translations("not json", ["nl"]) == {}
    assert parse_translations('["nl"]', ["nl"]) == {}
    assert parse_translations('{"nl": ""}', ["nl"]) == {}


def test_no_translation_without_the_option():
    from rag_calorvia.rag.translate import translate_question
    assert translate_question("Quand ?", {"search": {}}) == {"fr": "Quand ?"}  # no LLM call


def test_the_fingerprint_changes_with_any_chunk_text():
    from rag_calorvia.etl.index import fingerprint
    chunks = [{"document": "a.xlsx", "chunk_index": 0, "text": "Heures : 620"}]
    same = [dict(chunks[0])]
    changed = [{**chunks[0], "text": "Heures de formation à la sécurité : 620"}]
    assert fingerprint(chunks) == fingerprint(same)
    assert fingerprint(chunks) != fingerprint(changed)


def test_status_filter_builds_a_must_not_condition():
    from rag_calorvia.rag.pipeline import status_filter
    assert status_filter({"search": {}}) is None
    flt = status_filter({"search": {"exclude_status": ["draft", "archive"]}})
    [condition] = flt.must_not
    assert condition.key == "status" and condition.match.any == ["draft", "archive"]


def test_chronological_context_order():
    from rag_calorvia.rag.pipeline import context_order
    chunks = [{"id": 1, "doc_date": "2026-02-09"}, {"id": 2, "doc_date": None}, {"id": 3, "doc_date": "2025-12-01"},
              {"id": 4, "doc_date": "2026-02-09"}]
    assert context_order(chunks, {"generation": {}}) == chunks  # default: the reranker's order
    ordered = context_order(chunks, {"generation": {"order": "chronological"}})
    assert [c["id"] for c in ordered] == [2, 3, 1, 4]  # undated first, then oldest; same date keeps rank order


def test_parse_reference_date():
    from datetime import date
    from rag_calorvia.rag.reference_date import parse_reference
    assert parse_reference('{"date": "2025-12-31"}') == date(2025, 12, 31)
    assert parse_reference('{"date": null}') is None
    assert parse_reference('{"date": "2026-02-30"}') is None   # not a real date
    assert parse_reference("pas du JSON") is None


def test_question_filter_combines_status_and_date():
    from datetime import date
    from rag_calorvia.rag.pipeline import question_filter
    config = {"search": {"exclude_status": ["draft"]}}
    assert question_filter({"search": {}}, None) is None
    only_status = question_filter(config, None)
    assert only_status.must_not and not only_status.must
    both = question_filter(config, date(2025, 12, 31))
    [date_part] = both.must
    assert date_part.should[0].range.lte.date() == date(2025, 12, 31) and both.must_not


# --- step 30: reranking in the chunk's language, translation glossary ----------------------------------------------
RERANK = {"reranker": {"model": "bge-reranker"}, "search": {"top_k": 2}}
VERSIONS = {"fr": "Combien coûte le contrat ?", "nl": "Hoeveel kost het contract?", "en": "How much is the contract?"}
CHUNKS = [{"text": "a", "language": "fr"}, {"text": "b", "language": "nl"}, {"text": "c", "language": "de"},
          {"text": "d", "language": "nl"}]


@pytest.fixture
def calls(monkeypatch):
    """The reranker replaced: each text scores by its letter, and every (query, texts) call is recorded."""
    seen = []

    def score(model, query, texts):
        seen.append((query, texts))
        return [(i, {"a": 0.4, "b": 0.9, "c": 0.1, "d": 0.6}[t]) for i, t in enumerate(texts)]
    monkeypatch.setattr(rerank_module, "score", score)
    return seen


def test_by_default_every_chunk_is_scored_against_the_french_question(calls):
    ranked = rerank_module.rerank(VERSIONS["fr"], CHUNKS, RERANK, VERSIONS)
    assert calls == [(VERSIONS["fr"], ["a", "b", "c", "d"])] and [c["text"] for c in ranked] == ["b", "d"]


def test_query_language_chunk_scores_each_chunk_in_its_language(calls):
    config = {**RERANK, "reranker": {"model": "bge-reranker", "query_language": "chunk"}}
    ranked = rerank_module.rerank(VERSIONS["fr"], CHUNKS, config, VERSIONS)
    assert sorted(calls) == sorted([(VERSIONS["fr"], ["a", "c"]), (VERSIONS["nl"], ["b", "d"])])  # German: French
    assert [(c["text"], c["rerank_score"]) for c in ranked] == [("b", 0.9), ("d", 0.6)]       # one merged ranking


def test_without_translations_query_language_changes_nothing(calls):
    config = {**RERANK, "reranker": {"model": "bge-reranker", "query_language": "chunk"}}
    rerank_module.rerank(VERSIONS["fr"], CHUNKS, config, {"fr": VERSIONS["fr"]})
    assert calls == [(VERSIONS["fr"], ["a", "b", "c", "d"])]


def test_the_glossary_is_added_to_the_translation_prompt_only_when_configured():
    assert translation_prompt({"search": {}}) == TRANSLATION_PROMPT
    prompt = translation_prompt({"search": {"glossary": "prompts/glossary_translation.txt"}})
    assert prompt.startswith(TRANSLATION_PROMPT) and "chariot élévateur → heftruck" in prompt


def test_translated_search_false_keeps_the_translations_for_the_reranker_only(monkeypatch):
    from rag_calorvia.rag import pipeline
    seen = {}
    monkeypatch.setattr(pipeline, "translate_question", lambda q, c: VERSIONS)
    monkeypatch.setattr(pipeline, "reference_date", lambda q, c: None)
    monkeypatch.setattr(pipeline, "search", lambda q, c, query_filter, versions: seen.setdefault("search", versions) and [])
    monkeypatch.setattr(pipeline, "rerank", lambda q, chunks, c, versions: seen.setdefault("rerank", versions) and [])
    config = {"search": {"translated_search": False}}
    pipeline.retrieve(VERSIONS["fr"], config)
    assert seen == {"search": {"fr": VERSIONS["fr"]}, "rerank": VERSIONS}
