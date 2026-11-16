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
