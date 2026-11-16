"""The registry: one row per file of the corpus, with what we know about it and whether it is indexed.

Two fingerprints per file:
- sha256: the bytes of the file. Two copies of a DOCX or a PDF almost never share it, because the
  container stores its own dates (docProps/core.xml in Office files, CreationDate and /ID in PDFs);
- content_hash: the normalized text of the document, so a copy is recognised whatever its packaging.
"""
import hashlib
import logging
from datetime import date
import re
import tomllib
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path

import pymupdf

from rag_calorvia.config import settings
from rag_calorvia.etl.convert import DOCLING_FORMATS, file_format, load_conversion
from rag_calorvia.etl.metadata import extract_metadata

logger = logging.getLogger(__name__)

EXCLUSIONS_PATH = Path("exclusions.toml")


@dataclass
class Document:
    path: str                     # relative to the corpus root: the id of the document everywhere
    format: str
    size_bytes: int
    sha256: str
    content_hash: str
    page_count: int | None = None
    has_text_layer: bool | None = None  # PDFs only: False for a scan
    text_chars: int = 0               # characters of text Docling found (0 for images and scans)
    duplicate_of: str | None = None
    excluded_reason: str | None = None
    # Metadata (etl/metadata.py)
    department: str | None = None
    doc_type: str | None = None
    doc_label: str | None = None      # French, for the context line of the chunks
    doc_date: date | None = None
    date_end: date | None = None
    date_precision: str | None = None  # day, month, quarter, year, range
    date_source: str | None = None     # filename, content, photo
    version: str | None = None
    status: str | None = None          # template, copy, archive, draft, signed, approved, or None
    markers: list[str] | None = None
    language: str | None = None        # of the whole document; per chunk in step 5
    source_type: str | None = None     # text, table, image, scan


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def normalize_text(text):
    """The letters and digits of a text, lower-cased: what stays equal when only the layout changes."""
    text = unicodedata.normalize("NFKC", text).casefold()
    return re.sub(r"[\W_]+", "", text)  # drops spaces, line breaks and punctuation


def pdf_facts(path):
    """(page count, has a text layer) of a PDF."""
    with pymupdf.open(path) as pdf:
        return pdf.page_count, any(page.get_text().strip() for page in pdf)


def describe(relative_path):
    """Everything the inventory records about one file, before exclusions."""
    path = settings.corpus_path / relative_path
    data = path.read_bytes()
    fmt = file_format(path)
    document = Document(path=relative_path, format=fmt, size_bytes=len(data), sha256=sha256_bytes(data), content_hash="")

    text = ""
    if fmt in DOCLING_FORMATS:
        converted = load_conversion(relative_path)
        if converted is None:
            raise FileNotFoundError(f"no conversion for {relative_path}: run the conversion first")
        text = converted.export_to_text()
        if fmt == "pptx":
            document.page_count = converted.num_pages()
    if fmt == "pdf":
        document.page_count, document.has_text_layer = pdf_facts(path)

    for field, value in extract_metadata(relative_path, fmt, text, document.has_text_layer).items():
        setattr(document, field, value)

    normalized = normalize_text(text)
    document.text_chars = len(text.strip())
    # No text (image, scan): the bytes are the only fingerprint. Hashing the empty text would make
    # every image and scan a "duplicate" of each other.
    document.content_hash = sha256_bytes(normalized.encode()) if normalized else document.sha256
    return document


def load_rules(path=EXCLUSIONS_PATH):
    """The hand-reviewed exclusion rules: [{'path', 'reason', 'note'}]."""
    with open(path, "rb") as f:
        return tomllib.load(f)["rule"]


def rule_reason(relative_path, rules):
    """The reason of the first rule matching a path (a file, or a folder ending with '/'), or None."""
    for rule in rules:
        if relative_path == rule["path"] or (rule["path"].endswith("/") and relative_path.startswith(rule["path"])):
            return rule["reason"]
    return None


def is_empty(document):
    """A document Docling should have read but that has no text. A scan isn't empty: it needs a VLM."""
    return document.format in DOCLING_FORMATS and document.has_text_layer is not False and document.text_chars == 0


def canonical_rank(document):
    """Sort key: which copy of a duplicate group we keep. Smallest wins.

    Outside the archives first (a copy in 99_Archives/Doublons is the copy), then not a PDF (the
    DOCX it was exported from has exact headings and tables, a PDF needs layout analysis), then the
    shortest path (a document's home folder rather than an annex), then alphabetical order.
    """
    return (document.path.startswith("99_Archives/"), document.format == "pdf", len(document.path), document.path)


def apply_exclusions(documents, rules):
    """Set excluded_reason (and duplicate_of) on every document, in order: rules, empty, duplicates.

    Duplicates are grouped among the documents still kept, so a template or a noise file never
    becomes the copy we keep.
    """
    for document in documents:
        document.excluded_reason = rule_reason(document.path, rules)
        if document.excluded_reason is None and is_empty(document):
            document.excluded_reason = "empty"

    groups = {}
    for document in documents:
        if document.excluded_reason is None:
            groups.setdefault(document.content_hash, []).append(document)
    for group in groups.values():
        kept, *copies = sorted(group, key=canonical_rank)
        for copy in copies:
            copy.excluded_reason, copy.duplicate_of = "duplicate", kept.path
    return documents


def corpus_files():
    """Relative paths of every file of the corpus, sorted."""
    return sorted(str(p.relative_to(settings.corpus_path)) for p in settings.corpus_path.rglob("*") if p.is_file())


def build_inventory():
    """Describe every file of the corpus and decide what is excluded. Needs the Docling conversions."""
    documents = [describe(path) for path in corpus_files()]
    return apply_exclusions(documents, load_rules())


def as_rows(documents):
    return [asdict(document) for document in documents]
