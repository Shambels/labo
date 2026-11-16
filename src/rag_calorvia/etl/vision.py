"""Images and scans read by a vision model (VLM, step 7), once: every transcription is cached in data/vision/.

Three cases:
- images (PNG, JPG): org charts, plans, nameplates, whiteboards, charts, schedules, invoices and delivery notes;
- scanned PDFs (no text layer): each page rendered as an image;
- images inside a text PDF: the charts whose values are not in the PDF's text.
"""
import base64
import hashlib
import io
import json
import logging
import time
from dataclasses import dataclass
from functools import cache

import pymupdf
from openai import OpenAI
from PIL import Image

from rag_calorvia.config import settings

logger = logging.getLogger(__name__)

TRANSCRIBE_PROMPT = """Tu transcris des documents d'entreprise pour un moteur de recherche.
1. Recopie tout le texte visible, exactement comme il est écrit : nombres, codes, dates, unités et
   annotations manuscrites compris. Rends les tableaux en Markdown.
2. Puis, sous le titre « Description », décris en trois phrases au plus le type d'image (organigramme,
   plan, graphique, photo, facture...) et ce qu'elle montre qui n'est pas écrit : les rattachements
   d'un organigramme, la valeur la plus haute d'un graphique, la position des éléments d'un plan.
N'invente rien : si un élément est illisible, écris [illisible]."""

MAX_SIDE = 1600        # pixels: larger images cost tokens and time without being more legible
SCAN_DPI = 150         # rendering of scanned pages
MIN_EMBEDDED_SIDE = 200  # smaller images inside a PDF are logos and icons


@dataclass(frozen=True)
class Target:
    """One image to transcribe: a file, a page of a scan, or the n-th image of a text PDF."""
    path: str              # relative to the corpus
    kind: str              # image, scan_page, embedded
    page: int | None = None  # 0-based page of a PDF
    index: int | None = None  # embedded image number in the PDF


@cache
def get_vlm():
    return OpenAI(base_url=settings.vlm_url, api_key="EMPTY")


def image_to_data_url(image, max_side=MAX_SIDE):
    """A PIL image, resized if needed, as a base64 JPEG 'data:' URL accepted by the OpenAI API."""
    image = image.convert("RGB")
    image.thumbnail((max_side, max_side))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=90)
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode()


def page_image(path, page, dpi=SCAN_DPI):
    """One page of a PDF as a PIL image."""
    with pymupdf.open(path) as pdf:
        pixmap = pdf[page].get_pixmap(dpi=dpi)
    return Image.open(io.BytesIO(pixmap.tobytes("png")))


def pdf_images(path, min_side=MIN_EMBEDDED_SIDE):
    """Images embedded in a PDF, at least min_side pixels on each side: [(page, PIL image)]."""
    found = []
    with pymupdf.open(path) as pdf:
        for page_number, page in enumerate(pdf):
            for xref, *_ in page.get_images():
                image = Image.open(io.BytesIO(pdf.extract_image(xref)["image"]))
                if min(image.size) >= min_side:
                    found.append((page_number, image))
    return found


def load_image(target):
    path = settings.corpus_path / target.path
    if target.kind == "image":
        return Image.open(path)
    if target.kind == "scan_page":
        return page_image(path, target.page)
    return pdf_images(path)[target.index][1]


def targets_of(document):
    """The images to transcribe for one registry document (empty for a plain text document)."""
    path = settings.corpus_path / document["path"]
    if document["source_type"] == "image":
        return [Target(document["path"], "image")]
    if document["source_type"] == "scan":
        return [Target(document["path"], "scan_page", page=p) for p in range(document["page_count"])]
    if document["format"] == "pdf":
        return [Target(document["path"], "embedded", page=page, index=i) for i, (page, _) in enumerate(pdf_images(path))]
    return []


def cache_path(target, model, prompt):
    """data/vision/<key>.json; the key includes the model and the prompt: changing either transcribes again."""
    key = hashlib.sha256(f"{target.path}|{target.kind}|{target.page}|{target.index}|{model}|{prompt}".encode()).hexdigest()[:16]
    return settings.vision_path / f"{key}.json"


def describe(image, model, prompt=TRANSCRIBE_PROMPT, max_tokens=1500):
    """The VLM's transcription and description of one image. Temperature 0: a transcription, not creativity."""
    response = get_vlm().chat.completions.create(
        model=model, temperature=0, max_tokens=max_tokens,
        messages=[{"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": image_to_data_url(image)}},
        ]}],
    )
    choice = response.choices[0]
    if choice.finish_reason == "length":
        logger.warning("transcription cut at %d tokens", max_tokens)
    return (choice.message.content or "").strip()


def transcription(target, model=None, prompt=TRANSCRIBE_PROMPT, compute=True):
    """The cached transcription of a target ({'text', 'seconds', ...}); computed and stored if missing.

    compute=False: only read the cache (None if absent), so chunking never calls the VLM by accident.
    """
    model = model or settings.vlm_model
    path = cache_path(target, model, prompt)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    if not compute:
        return None
    started = time.perf_counter()
    text = describe(load_image(target), model, prompt)
    record = {"path": target.path, "kind": target.kind, "page": target.page, "index": target.index, "model": model,
              "prompt": prompt, "seconds": round(time.perf_counter() - started, 1), "text": text}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)  # atomic, as for the Docling conversions
    return record
