"""Docling: convert the text documents of the corpus to DoclingDocument JSON files, once.

Images and scanned pages are not read here: they need a vision model (step 7).
"""
import logging
from pathlib import Path

from docling.datamodel.accelerator_options import AcceleratorOptions
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions, RapidOcrOptions
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling_core.types.doc import DoclingDocument

from rag_calorvia.config import settings

logger = logging.getLogger(__name__)

# The formats Docling reads from their own text (or text layer). Images are left to the VLM.
DOCLING_FORMATS = {
    "docx": InputFormat.DOCX,
    "pdf": InputFormat.PDF,
    "pptx": InputFormat.PPTX,
    "xlsx": InputFormat.XLSX,
    "html": InputFormat.HTML,
    "md": InputFormat.MD,
    "csv": InputFormat.CSV,
}


def file_format(path):
    """Lower-case extension without the dot: 'PV.DOCX' -> 'docx'."""
    return Path(path).suffix.lower().lstrip(".")


def ocr_options():
    """RapidOCR (PP-OCR, ONNX) with the models already on disk: no download at run time."""
    models = settings.docling_models_path / "RapidOcr"
    return RapidOcrOptions(
        backend="onnxruntime",
        det_model_path=str(models / "PP-OCRv6_det_small.onnx"),
        cls_model_path=str(models / "ch_ppocr_mobile_v2.0_cls_mobile.onnx"),
        rec_model_path=str(models / "PP-OCRv6_rec_small.onnx"),
        rec_keys_path=str(models / "ppocrv6_dict.txt"),
    )


def get_converter(ocr=False):
    """A converter that only uses the local Docling models, with OCR off by default.

    OCR off: native PDFs have a text layer, and scans are read by the VLM (step 7). ocr=True is the comparison
    point the statement asks for (Docling's OCR vs the VLM on the scans); a scan converted without it is empty.
    """
    pdf_options = PdfPipelineOptions(
        artifacts_path=settings.docling_models_path,  # layout and table models: no download
        do_ocr=ocr,
        **({"ocr_options": ocr_options()} if ocr else {}),  # the field refuses None: only set it with OCR on
        do_table_structure=True,
        accelerator_options=AcceleratorOptions(device=settings.docling_device),
    )
    return DocumentConverter(
        allowed_formats=list(DOCLING_FORMATS.values()),
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pdf_options)},
    )


def conversion_path(relative_path):
    """Where a conversion is stored: the corpus tree mirrored under data/conversions/, plus '.json'.

    Mirroring the tree (not just the file name) matters: two files of the corpus can share a name.
    """
    return settings.conversions_path / f"{relative_path}.json"


def convert_documents(relative_paths, force=False):
    """Convert the documents that have no conversion yet. Returns the relative paths that failed."""
    todo = [p for p in relative_paths if force or not conversion_path(p).exists()]
    logger.info("%d documents, %d to convert", len(relative_paths), len(todo))
    if not todo:
        return []

    converter = get_converter()
    failures = []
    for i, relative_path in enumerate(todo, 1):
        try:
            result = converter.convert(settings.corpus_path / relative_path)
        except Exception:
            logger.exception("conversion failed: %s", relative_path)
            failures.append(relative_path)
            continue
        target = conversion_path(relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".tmp")
        result.document.save_as_json(tmp)
        tmp.replace(target)  # atomic: a crash never leaves a half-written file that would be skipped next time
        logger.info("[%d/%d] %s", i, len(todo), relative_path)
    return failures


def load_conversion(relative_path):
    """The DoclingDocument of a converted document, or None if it has no conversion."""
    path = conversion_path(relative_path)
    return DoclingDocument.load_from_json(path) if path.exists() else None
