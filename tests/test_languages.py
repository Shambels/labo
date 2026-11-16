from rag_calorvia.etl.chunk import chunk_language
from rag_calorvia.etl.index import bm25, collection_name, sparse_language

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
