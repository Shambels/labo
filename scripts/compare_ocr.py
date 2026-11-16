"""Docling's OCR (RapidOCR) vs the VLM on the scanned PDFs: time, and the dev evidence each one can show.

Needs the VLM transcriptions (scripts/transcribe.py). Docling's OCR runs here, on the CPU or GPU of DOCLING_DEVICE.
Usage: uv run python scripts/compare_ocr.py
"""
import time

from rag_calorvia import db
from rag_calorvia.config import settings
from rag_calorvia.etl.convert import get_converter
from rag_calorvia.etl.vision import targets_of, transcription
from rag_calorvia.evaluation.dataset import align_with_registry, load_questions
from rag_calorvia.evaluation.metrics import contains_all
from rag_calorvia.logs import setup_logging

setup_logging()
with db.connect(read_only=True) as conn:
    registry = db.load_registry(conn)
    scans = [d for d in db.load_vision_documents(conn) if d["source_type"] == "scan"]
questions = align_with_registry(load_questions("dev"), registry)

converter = get_converter(ocr=True)
texts, seconds = {"ocr": {}, "vlm": {}}, {"ocr": 0.0, "vlm": 0.0}
for document in scans:
    start = time.perf_counter()
    texts["ocr"][document["path"]] = converter.convert(settings.corpus_path / document["path"]).document.export_to_markdown()
    seconds["ocr"] += time.perf_counter() - start
    records = [transcription(t, compute=False) for t in targets_of(document)]
    texts["vlm"][document["path"]] = "\n".join(r["text"] for r in records)
    seconds["vlm"] += sum(r["seconds"] for r in records)

print(f"\n{len(scans)} scans. Time: Docling OCR {seconds['ocr']:.0f} s, VLM {seconds['vlm']:.0f} s\n")
print(f"{'question':9} {'type':16} {'OCR':>4} {'VLM':>4}  document · snippets")
found = {"ocr": 0, "vlm": 0}
items = 0
for question in questions:
    for evidence in question["evidence"]:
        if evidence["document"] not in texts["ocr"]:
            continue
        items += 1
        marks = []
        for reader in ("ocr", "vlm"):
            chunk = {"document": evidence["document"], "text": texts[reader][evidence["document"]]}
            ok = contains_all(chunk, evidence["document"], evidence["snippets"])
            found[reader] += ok
            marks.append("yes" if ok else "–")
        name = evidence["document"].split("/")[-1]
        print(f"{question['id']:9} {question['type']:16} {marks[0]:>4} {marks[1]:>4}  {name} · {evidence['snippets']}")
print(f"\nevidence items found: Docling OCR {found['ocr']}/{items}, VLM {found['vlm']}/{items}")
