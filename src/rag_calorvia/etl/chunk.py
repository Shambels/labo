"""Chunking: converted documents -> chunks ready to embed. Depends on [chunking] and [embedder] of the config.

Each chunk = context line + Docling headings + text. The context line says which document the chunk comes from
(type, date, file, folder): a row of a CODIR action table is useless if it doesn't say which meeting it is from.
"""
from functools import cache

from docling_core.transforms.chunker.hybrid_chunker import HybridChunker
from docling_core.transforms.chunker.tokenizer.huggingface import HuggingFaceTokenizer
from transformers import AutoTokenizer

from rag_calorvia import db
from rag_calorvia.config import settings
from rag_calorvia.etl.convert import load_conversion
from rag_calorvia.etl.metadata import detect_language

MONTHS_FR = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
             "novembre", "décembre"]

# The payload of every chunk: the registry fields the searches may filter on, and what the LLM and the eval need
PAYLOAD_FIELDS = ["department", "doc_type", "doc_label", "doc_date", "date_end", "date_precision", "date_source",
                  "version", "status", "source_type", "format"]

DEFAULT_LANGUAGE = "fr"  # most of the corpus; used when neither the chunk nor its document has a reliable language


@cache
def get_tokenizer(model):
    """The embedder's own tokenizer: chunk sizes are counted in the tokens the embedder will see."""
    return AutoTokenizer.from_pretrained(settings.models_path / "embedder" / model)


def count_tokens(text, tokenizer):
    return len(tokenizer.encode(text, add_special_tokens=False))


def french_date(document):
    """The date of a document as a French phrase, following its precision: 'du 13 octobre 2025', 'de mars 2026'..."""
    start, end, precision = document["doc_date"], document["date_end"], document["date_precision"]
    if start is None:
        return ""
    if precision == "day":
        day = "1er" if start.day == 1 else str(start.day)
        prefix = "prise le" if document["date_source"] == "photo" else "du"  # a photo's date is when it was taken
        return f" {prefix} {day} {MONTHS_FR[start.month - 1]} {start.year}"
    if precision == "month":
        return f" de {MONTHS_FR[start.month - 1]} {start.year}"
    if precision == "quarter":
        return f" du T{(start.month - 1) // 3 + 1} {start.year}"
    if precision == "year":
        return f" {start.year}"
    return f" {start.year}-{end.year}"  # range


def context_line(document):
    """'[PV du CODIR du 13 octobre 2025 · PV_CODIR_2025-10-13 · 00_Direction/CODIR/2025]'.

    The file name is kept even when the label says the same: it holds what the label can't ('projet v1',
    'signé', 'FINAL', 'Tarif 2026'), for the lexical search and for the LLM.
    """
    path = document["path"]
    folder, _, name = path.rpartition("/")
    stem = name.rsplit(".", 1)[0]
    return f"[{document['doc_label']}{french_date(document)} · {stem} · {folder}]"


def chunk_language(body, document_language):
    """The language of a chunk: detected on its own text (not the context line, which is always French), else its
    document's, else French. A French minute quoting a Dutch report has Dutch chunks; a short chunk ('Néant.')
    is too short to detect and inherits its document's language."""
    return detect_language(body) or document_language or DEFAULT_LANGUAGE


def chunk_document(document, config):
    """The chunks of one registry document: dicts with the payload fields, chunk_index and text.

    text = context line + headings + chunk text, under [chunking] max_tokens.
    """
    tokenizer = get_tokenizer(config["embedder"]["model"])
    line = context_line(document) if config["chunking"]["context_line"] else None
    # HybridChunker counts headings + text; the context line is added afterwards, so reserve its tokens
    reserved = count_tokens(line, tokenizer) + 1 if line else 0  # +1: the newline
    chunker = HybridChunker(
        tokenizer=HuggingFaceTokenizer(tokenizer=tokenizer, max_tokens=config["chunking"]["max_tokens"] - reserved)
    )
    converted = load_conversion(document["path"])
    payload = {"document": document["path"], "doc_language": document["language"]} | {
        field: (value.isoformat() if hasattr(value, "isoformat") else value)  # dates as ISO strings for Qdrant
        for field, value in ((f, document[f]) for f in PAYLOAD_FIELDS)
    }
    chunks = []
    for chunk in chunker.chunk(converted):
        if not chunk.text.strip():
            continue
        body = "\n".join([*(chunk.meta.headings or []), chunk.text])
        chunks.append({**payload, "chunk_index": len(chunks), "language": chunk_language(body, document["language"]),
                       "text": "\n".join(p for p in [line, body] if p)})
    return chunks


def chunk_corpus(config):
    """The chunks of every indexed text document of the registry (excluded files, images and scans left out)."""
    with db.connect(read_only=True) as conn:
        documents = db.load_indexable_documents(conn)
    return [chunk for document in documents for chunk in chunk_document(document, config)]
