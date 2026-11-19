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
    monkeypatch.setattr(pipeline, "rerank", lambda q, chunks, c, versions, translate: seen.setdefault("rerank", versions) and [])
    config = {"search": {"translated_search": False}, "reranker": {}}
    pipeline.retrieve(VERSIONS["fr"], config)
    assert seen == {"search": {"fr": VERSIONS["fr"]}, "rerank": VERSIONS}


ON_DEMAND = {"reranker": {"model": "bge-reranker", "query_language": "chunk", "translate_window": 2},
             "search": {"top_k": 2}}


def test_on_demand_no_translation_when_the_french_top_is_all_french(calls):
    asked = []
    chunks = [{"text": "a", "language": "fr"}, {"text": "b", "language": "fr"}, {"text": "c", "language": "nl"}]
    ranked = rerank_module.rerank(VERSIONS["fr"], chunks, ON_DEMAND, translate=lambda langs: asked.append(langs))
    assert asked == [] and len(calls) == 1 and [c["text"] for c in ranked] == ["b", "a"]   # c (0.1) is 3rd


def test_on_demand_translates_the_languages_present_and_rescores_only_the_others(calls):
    asked = []

    def translate(languages):
        asked.append(languages)
        return VERSIONS
    ranked = rerank_module.rerank(VERSIONS["fr"], CHUNKS, ON_DEMAND, translate=translate)   # b (nl, 0.9) is 1st
    assert asked == [["de", "nl"]]
    assert calls[1:] == [(VERSIONS["nl"], ["b", "d"])]           # German has no version: it keeps its French score
    assert [(c["text"], c["rerank_score"]) for c in ranked] == [("b", 0.9), ("d", 0.6)]


def test_translate_question_can_be_limited_to_the_languages_needed(monkeypatch):
    from rag_calorvia.rag import translate as translate_module

    class LLM:
        class chat:
            class completions:
                @staticmethod
                def create(**kwargs):
                    class Message:
                        content = '{"nl": "vraag", "en": "question"}'
                    return type("R", (), {"choices": [type("C", (), {"message": Message})]})
    monkeypatch.setattr(translate_module, "get_llm", lambda: LLM)
    config = {"search": {"translate": ["nl", "en"]}, "generation": {"model": "m"}}
    assert translate_module.translate_question("q", config, ["nl", "de"]) == {"fr": "q", "nl": "vraag"}


# --- step 30f: Docling tables as Markdown ------------------------------------------------------------------------------
def report_with_a_table():
    """Q093's case: a two-column table whose first row is read as the header."""
    from docling_core.types.doc import DoclingDocument, TableCell, TableData
    rows = [["Simulation d'hameçonnage (mai)", "Taux de clic : 4 %"], ["Incidents", "Aucun incident majeur"]]
    cells = [TableCell(text=text, start_row_offset_idx=r, end_row_offset_idx=r + 1, start_col_offset_idx=c,
                       end_col_offset_idx=c + 1, column_header=(r == 0))
             for r, row in enumerate(rows) for c, text in enumerate(row)]
    doc = DoclingDocument(name="rapport")
    doc.add_table(data=TableData(num_rows=2, num_cols=2, table_cells=cells))
    return doc


def table_text(config):
    from docling_core.transforms.chunker.hybrid_chunker import HybridChunker
    from docling_core.transforms.chunker.tokenizer.huggingface import HuggingFaceTokenizer
    from rag_calorvia.etl.chunk import MarkdownTables, get_tokenizer, markdown_tables
    tokenizer = HuggingFaceTokenizer(tokenizer=get_tokenizer("bge-m3"), max_tokens=256)
    chunker = HybridChunker(tokenizer=tokenizer,
                            **({"serializer_provider": MarkdownTables()} if markdown_tables(config) else {}))
    return "\n".join(c.text for c in chunker.chunk(report_with_a_table()))


def test_markdown_tables_keep_the_row_read_as_header():
    # Docling's default: the first row became the column names, its label is gone, its value is read as a header
    assert table_text({"chunking": {}}) == "Incidents, Taux de clic : 4 % = Aucun incident majeur"
    markdown = table_text({"chunking": {"tables": "markdown"}})
    assert "| Simulation d'hameçonnage (mai) | Taux de clic : 4 % |" in markdown
    assert "| Incidents | Aucun incident majeur |" in markdown and "  |" not in markdown            # compact


def test_markdown_tables_get_their_own_index():
    assert collection_name({**CONFIG, "chunking": {**CONFIG["chunking"], "tables": "markdown"}}) == \
        "calorvia__bge-m3__256__md-tables"


# --- step 30g: nl/en chunks searched in French ------------------------------------------------------------------------
FR_CONFIG = {"chunking": {"context_line": True, "translate_to": "fr"}, "generation": {"model": "m"}}
DUTCH = {"document": "contract.pdf", "chunk_index": 4, "language": "nl",
         "text": "[Contrat · Onderhoudscontract heftrucks]\n4. Prijs\n18 400 euro excl. btw per jaar."}


@pytest.fixture
def cache(tmp_path, monkeypatch):
    from rag_calorvia.etl import translate
    monkeypatch.setattr(translate.settings, "translations_path", tmp_path)

    def store(body, french):
        import json
        path = translate.cache_path(body, "m", translate.prompt())
        path.write_text(json.dumps({"translation": french}), encoding="utf-8")
    return store


def test_a_dutch_chunk_is_searched_in_french_and_read_in_dutch(cache):
    from rag_calorvia.etl.translate import search_text, with_french
    cache("4. Prijs\n18 400 euro excl. btw per jaar.", "4. Prix\n18 400 euros HT par an.")
    chunk = with_french(DUTCH, FR_CONFIG)
    assert chunk["search_text"] == "[Contrat · Onderhoudscontract heftrucks]\n4. Prix\n18 400 euros HT par an."
    assert chunk["text"] == DUTCH["text"] and search_text(chunk) == chunk["search_text"]   # the generator's text


def test_french_chunks_are_left_alone_and_a_missing_translation_stops_the_index(cache):
    from rag_calorvia.etl.translate import MissingTranslation, search_text, with_french
    french = {**DUTCH, "language": "fr"}
    assert with_french(french, FR_CONFIG) is french and search_text(french) == french["text"]
    with pytest.raises(MissingTranslation):
        with_french(DUTCH, FR_CONFIG)


def test_a_translated_chunk_is_stemmed_in_french_and_indexed_apart():
    per_chunk = {**CONFIG, "sparse": {"language": "per_chunk"}}
    assert sparse_language({"language": "nl", "search_text": "x"}, per_chunk) == "fr"
    assert sparse_language({"language": "nl"}, per_chunk) == "nl"
    assert collection_name({**CONFIG, "chunking": {**CONFIG["chunking"], "translate_to": "fr"}}) == \
        "calorvia__bge-m3__256__fr-chunks"


def test_the_reranker_reads_the_french_search_text(calls):
    chunks = [{"text": "z", "search_text": "b", "language": "nl"}, {"text": "a", "language": "fr"}]
    ranked = rerank_module.rerank(VERSIONS["fr"], chunks, RERANK)
    assert calls == [(VERSIONS["fr"], ["b", "a"])] and ranked[0]["text"] == "z"   # scored on b, returned as written
