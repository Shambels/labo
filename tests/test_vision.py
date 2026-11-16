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


def test_labels_of_the_three_kinds_of_targets():
    from rag_calorvia.etl.chunk import target_label
    assert target_label(Target("a.png", "image")) == "Image"
    assert target_label(Target("s.pdf", "scan_page", page=1)) == "Page 2 (scan)"
    assert target_label(Target("r.pdf", "embedded", page=0, index=0)) == "Graphique de la page 1"


def test_vision_chunks_of_an_image(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "vision_path", tmp_path)
    monkeypatch.setattr(settings, "vlm_model", "m")
    cache_path(Target("a.png", "image"), "m", TRANSCRIBE_PROMPT).write_text(json.dumps({"text": "Achats : Céline Moreau"}))
    document = {"path": "a.png", "source_type": "image", "format": "png", "language": "fr", "doc_date": None,
                **{f: None for f in ["department", "doc_type", "doc_label", "date_end", "date_precision",
                                     "date_source", "version", "status"]}}
    [chunk] = vision_chunks(document, "[Organigramme · a]", 200, get_tokenizer("bge-m3"))
    assert chunk["text"] == "[Organigramme · a]\nImage\nAchats : Céline Moreau"
    assert chunk["image_path"] == "a.png" and chunk["page"] is None


def test_answer_images_follow_the_citations():
    from rag_calorvia.rag.images import answer_images
    chunks = [{"text": "PV texte"},
              {"image_path": "org.png", "page": None},
              {"image_path": "scan.pdf", "page": 0},
              {"image_path": "org.png", "page": None}]
    assert answer_images("Céline Moreau [2][4].", chunks) == [("org.png", None)]       # only cited, no duplicates
    assert answer_images("Rien de cité.", chunks) == [("org.png", None), ("scan.pdf", 0)]  # no citation: all images
    assert answer_images("Texte seulement [1].", chunks) == []


def test_collection_name_records_the_vision_budget():
    from rag_calorvia.etl.index import collection_name
    config = {"chunking": {"max_tokens": 256, "context_line": True, "vision": True}, "embedder": {"model": "bge-m3"}}
    assert collection_name(config).endswith("__vision")
    config["chunking"]["vision_max_tokens"] = 1024
    assert collection_name(config).endswith("__vision-1024")
