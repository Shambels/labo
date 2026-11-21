"""Chunking: converted documents -> chunks ready to embed. Depends on [chunking] and [embedder] of the config.

Each chunk = context line + Docling headings + text. The context line says which document the chunk comes from
(type, date, file, folder): a row of a CODIR action table is useless if it doesn't say which meeting it is from.

Step 30: [chunking] tables = "markdown" writes the tables of Docling documents as compact Markdown tables instead of
Docling's default "row, column = value" sentences. Those sentences take their column names from the row Docling reads
as the header: when it reads the first data row as the header (Q093's two-column report table), every sentence repeats
that row's value and the row label is lost. A Markdown table keeps every row as written.
"""
from functools import cache

from docling_core.transforms.chunker.hierarchical_chunker import ChunkingDocSerializer, ChunkingSerializerProvider
from docling_core.transforms.chunker.hybrid_chunker import HybridChunker
from docling_core.transforms.chunker.tokenizer.huggingface import HuggingFaceTokenizer
from docling_core.transforms.serializer.markdown import MarkdownParams, MarkdownTableSerializer
from transformers import AutoTokenizer

from rag_calorvia import db
from rag_calorvia.config import settings
from rag_calorvia.etl.contextual import add_contexts, contextualizes
from rag_calorvia.etl.convert import load_conversion
from rag_calorvia.etl.excel import workbook_pieces
from rag_calorvia.etl.metadata import detect_language, issuer
from rag_calorvia.etl.translate import translates_chunks, with_french
from rag_calorvia.etl.vision import PROMPTS, targets_of, transcription
from rag_calorvia.rag.permissions import allowed_roles

MONTHS_FR = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
             "novembre", "décembre"]

# The payload of every chunk: the registry fields the searches may filter on, and what the LLM and the eval need
PAYLOAD_FIELDS = ["department", "doc_type", "doc_label", "doc_date", "date_end", "date_precision", "date_source",
                  "version", "status", "source_type", "format"]

ACCESS_FIELD = "allowed_roles"  # the roles that may read a chunk (D77); not part of the index fingerprint

class MarkdownTables(ChunkingSerializerProvider):
    """Docling's chunking serializer, with tables as compact Markdown (no padding: it would spend the token budget)."""

    def get_serializer(self, doc):
        return ChunkingDocSerializer(doc=doc, table_serializer=MarkdownTableSerializer(),
                                     params=MarkdownParams(compact_tables=True))


def markdown_tables(config):
    return config["chunking"].get("tables", "docling") == "markdown"


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


def context_line(document, with_issuer=False):
    """'[PV du CODIR du 13 octobre 2025 · PV_CODIR_2025-10-13 · 00_Direction/CODIR/2025]'.

    The file name is kept even when the label says the same: it holds what the label can't ('projet v1',
    'signé', 'FINAL', 'Tarif 2026'), for the lexical search and for the LLM.

    with_issuer ([chunking] issuer = true, step 34): who wrote it, after the label: '[Conditions générales de vente
    2026 · Calorvia SA · ...]'. The reranker read "les conditions de paiement de Calorvia" as a supplier's offer
    addressed to Calorvia SA (0.77), and Calorvia's own terms, which never name the company, as off-topic (0.02).
    """
    path = document["path"]
    folder, _, name = path.rpartition("/")
    stem = name.rsplit(".", 1)[0]
    who = issuer(document.get("doc_type")) if with_issuer else None
    return f"[{document['doc_label']}{french_date(document)}{f' · {who}' if who else ''} · {stem} · {folder}]"


def chunk_language(body, document_language):
    """The language of a chunk: detected on its own text (not the context line, which is always French), else its
    document's, else French. A French minute quoting a Dutch report has Dutch chunks; a short chunk ('Néant.')
    is too short to detect and inherits its document's language."""
    return detect_language(body) or document_language or DEFAULT_LANGUAGE


def document_payload(document):
    """The registry fields every chunk of a document carries."""
    return {"document": document["path"], "doc_language": document["language"]} | {
        field: (value.isoformat() if hasattr(value, "isoformat") else value)  # dates as ISO strings for Qdrant
        for field, value in ((f, document[f]) for f in PAYLOAD_FIELDS)
    }


def reads_with_openpyxl(document, config):
    """[chunking] excel = "openpyxl" (step 6): workbooks are read by etl/excel.py instead of Docling."""
    return document["format"] == "xlsx" and config["chunking"].get("excel", "docling") == "openpyxl"


def chunk_workbook(document, config, line, budget, tokenizer):
    """The chunks of a workbook read with openpyxl: rows, tables, summaries and text, each with its sheet and row."""
    payload = document_payload(document)
    pieces = workbook_pieces(settings.corpus_path / document["path"],
                             fits=lambda text: count_tokens(text, tokenizer) <= budget)
    return [
        {**payload, "chunk_index": i, "sheet": piece["sheet"], "row": piece["row"], "piece": piece["kind"],
         "language": chunk_language(piece["text"], document["language"]),
         "text": "\n".join(p for p in [line, piece["text"]] if p)}
        for i, piece in enumerate(pieces)
    ]


def vision_prompt(config):
    """Which transcriptions to index: [chunking] vision_prompt, "v1" (step 7) by default."""
    return config["chunking"].get("vision_prompt", "v1")


def vision_model(config):
    """Which VLM's transcriptions to index: [chunking] vision_model (step 37), else settings.vlm_model (qwen3.5-9b)."""
    return config["chunking"].get("vision_model")


def uses_vision(config):
    """[chunking] vision = true (step 7): images, scans and charts in PDFs are indexed from their transcriptions."""
    return config["chunking"].get("vision", False)


def split_text(text, budget, tokenizer):
    """Consecutive paragraphs (then lines, for a long paragraph) grouped into pieces of at most `budget` tokens."""
    units = []
    for paragraph in text.split("\n\n"):
        if count_tokens(paragraph, tokenizer) <= budget:
            units.append(paragraph)
        else:
            units.extend(paragraph.splitlines())
    pieces, current = [], ""
    for unit in (u for u in units if u.strip()):
        candidate = f"{current}\n\n{unit}" if current else unit
        if current and count_tokens(candidate, tokenizer) > budget:
            pieces.append(current)
            candidate = unit
        current = candidate
    return pieces + ([current] if current else [])


def target_label(target):
    """The line naming what a transcription is: 'Image', 'Page 2 (scan)', 'Graphique de la page 1'."""
    if target.kind == "image":
        return "Image"
    if target.kind == "scan_page":
        return f"Page {target.page + 1} (scan)"
    return f"Graphique de la page {target.page + 1}"


def vision_chunks(document, line, budget, tokenizer, start_index=0, prompt="v1", model=None):
    """Chunks from the cached transcriptions of a document's images (its own image, scanned pages, embedded charts).

    The transcriptions must exist (scripts/transcribe.py): chunking never calls the VLM. prompt: which transcriptions,
    [chunking] vision_prompt (step 35: "v2" also copies the text on a diagram's links). model: which VLM made them,
    [chunking] vision_model (step 37); None: settings.vlm_model.
    """
    payload = document_payload(document)
    chunks = []
    for target in targets_of(document):
        record = transcription(target, model=model, prompt=PROMPTS[prompt], compute=False)
        if record is None:
            raise FileNotFoundError(f"no transcription for {target} with prompt {prompt}: "
                                    f"run scripts/transcribe.py --prompt {prompt}"
                                    + (f" --model {model}" if model else "") + " with the VLM first")
        label = target_label(target)
        head = "\n".join(p for p in [line, label] if p)
        reserve = count_tokens(label, tokenizer) + 1
        for piece in split_text(record["text"], budget - reserve, tokenizer):
            chunks.append({**payload, "chunk_index": start_index + len(chunks), "image_path": document["path"],
                           "page": target.page, "piece": target.kind,
                           "language": chunk_language(piece, document["language"]),
                           "text": f"{head}\n{piece}"})
    return chunks


def chunk_document(document, config):
    """The chunks of one registry document: dicts with the payload fields, chunk_index and text.

    text = context line + headings + chunk text, under [chunking] max_tokens.
    """
    tokenizer = get_tokenizer(config["embedder"]["model"])
    line = context_line(document, config["chunking"].get("issuer", False)) if config["chunking"]["context_line"] else None
    # The chunkers count headings + text; the context line is added afterwards, so reserve its tokens
    reserved = count_tokens(line, tokenizer) + 1 if line else 0  # +1: the newline
    budget = config["chunking"]["max_tokens"] - reserved
    # An image is one unit of meaning: an org chart cut in two separates a person from their manager (Q056).
    # [chunking] vision_max_tokens gives transcriptions their own, larger budget; default: the same as text.
    vision_budget = config["chunking"].get("vision_max_tokens", config["chunking"]["max_tokens"]) - reserved
    if reads_with_openpyxl(document, config):
        return chunk_workbook(document, config, line, budget, tokenizer)
    if document["source_type"] in ("image", "scan"):  # only reached with [chunking] vision = true
        return vision_chunks(document, line, vision_budget, tokenizer, prompt=vision_prompt(config),
                             model=vision_model(config))
    chunker = HybridChunker(tokenizer=HuggingFaceTokenizer(tokenizer=tokenizer, max_tokens=budget),
                            **({"serializer_provider": MarkdownTables()} if markdown_tables(config) else {}))
    converted = load_conversion(document["path"])
    payload = document_payload(document)
    chunks = []
    for chunk in chunker.chunk(converted):
        if not chunk.text.strip():
            continue
        body = "\n".join([*(chunk.meta.headings or []), chunk.text])
        chunks.append({**payload, "chunk_index": len(chunks), "language": chunk_language(body, document["language"]),
                       "text": "\n".join(p for p in [line, body] if p)})
    if uses_vision(config) and document["format"] == "pdf":  # charts inside a text PDF
        chunks += vision_chunks(document, line, vision_budget, tokenizer, start_index=len(chunks),
                                prompt=vision_prompt(config), model=vision_model(config))
    return chunks


def chunk_corpus(config):
    """The chunks of every indexed document of the registry: text documents, plus images and scans with vision."""
    with db.connect(read_only=True) as conn:
        documents = db.load_indexable_documents(conn)
        if uses_vision(config):
            documents += [d for d in db.load_vision_documents(conn) if d["source_type"] in ("image", "scan")]
    chunks = [{**chunk, ACCESS_FIELD: allowed_roles(document["path"])}
              for document in documents for chunk in chunk_document(document, config)]
    if translates_chunks(config):   # step 30g: a French search text for the nl/en chunks, from the cache only
        chunks = [with_french(chunk, config) for chunk in chunks]
    if contextualizes(config):   # step 41: a sentence placing each chunk in its document, from the cache only
        chunks = add_contexts(chunks, config)
    return chunks
