import json

import pytest

from rag_calorvia.config import settings
from rag_calorvia.etl.chunk import get_tokenizer, split_text, vision_chunks
from rag_calorvia.etl.vision import TRANSCRIBE_PROMPT, Target, cache_path, transcription


def test_cache_key_depends_on_target_model_and_prompt():
    image = Target("02_RH/Organigrammes/Organigramme direction 2026-04.png", "image")
    page1, page2 = Target("x.pdf", "scan_page", page=0), Target("x.pdf", "scan_page", page=1)
    assert cache_path(image, "m", "p") == cache_path(image, "m", "p")
    assert len({cache_path(image, "m", "p"), cache_path(image, "other", "p"), cache_path(image, "m", "other")}) == 3
    assert cache_path(page1, "m", "p") != cache_path(page2, "m", "p")


def test_chunking_reads_the_cache_and_never_calls_the_vlm(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "vision_path", tmp_path)
    target = Target("a.png", "image")
    assert transcription(target, model="m", compute=False) is None  # absent: None, no VLM call
    cache_path(target, "m", TRANSCRIBE_PROMPT).write_text(json.dumps({"text": "Achats : Céline Moreau", "seconds": 4.2}))
    assert transcription(target, model="m", compute=False)["text"] == "Achats : Céline Moreau"


def test_split_text_keeps_paragraphs_under_the_budget():
    tokenizer = get_tokenizer("bge-m3")
    text = "\n\n".join(f"Ligne {i} : valeur {i * 10} unités" for i in range(40))
    pieces = split_text(text, 50, tokenizer)
    assert len(pieces) > 1
    assert all(len(tokenizer.encode(p, add_special_tokens=False)) <= 50 for p in pieces)
    assert "".join(pieces).replace("\n", "") == text.replace("\n", "")  # nothing lost, order kept


def test_missing_transcription_is_an_error(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "vision_path", tmp_path)
    document = {"path": "a.png", "source_type": "image", "format": "png", "language": None, "doc_date": None,
                **{f: None for f in ["department", "doc_type", "doc_label", "date_end", "date_precision",
                                     "date_source", "version", "status"]}}
    with pytest.raises(FileNotFoundError, match="transcribe.py"):
        vision_chunks(document, "[Image]", 200, get_tokenizer("bge-m3"))
