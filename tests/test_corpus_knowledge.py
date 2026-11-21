"""Step 41: the miss analysis, the corpus description, the semantic layer, the series, the contextual chunks."""
import importlib.util
import sys
from pathlib import Path

from rag_calorvia.rag.generate import load_system_prompt


def load_script(name, argv):
    """A script's functions, without running its command line (its argparse sees `argv`)."""
    spec = importlib.util.spec_from_file_location(name, Path("scripts") / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    old, sys.argv = sys.argv, [name, *argv]
    try:
        spec.loader.exec_module(module)
    except SystemExit:
        pass
    finally:
        sys.argv = old
    return module


def test_the_corpus_description_comes_after_the_rules():
    rules = {"generation": {"system_prompt": "prompts/tools_complete.txt"}}
    with_corpus = {"generation": {**rules["generation"], "corpus": "prompts/corpus.txt"}}
    plain, described = load_system_prompt(rules), load_system_prompt(with_corpus)
    assert described.startswith(plain) and len(described) > len(plain)
    assert "Gand" in described and "Gent" in described and "plus récent" in described
    assert "fiche de non-conformité" in described   # the details of rule 4 per kind of document


# --- the semantic layer -------------------------------------------------------------------------------------------
import json

from qdrant_client import models

from rag_calorvia.etl.entities import apply_review, merge_entities, normalize
from rag_calorvia.rag import entities as entities_module
from rag_calorvia.rag.entities import card, entity_documents, find_entities
from rag_calorvia.rag.search import hybrid_request


def mention(name, kind="personne", aliases=(), description=""):
    return {"nom": name, "type": kind, "alias": list(aliases), "description": description}


def test_normalize_ignores_case_accents_and_punctuation():
    assert normalize("Aéris-12") == normalize("AERIS 12") == "aeris 12"


def test_mentions_sharing_a_name_or_an_alias_merge_and_the_newest_description_leads():
    found = {
        "a.docx": [mention("Gand", "site", ["Gent"], "Usine de ventilation"), mention("Pieter De Smet")],
        "b.docx": [mention("Gent", "site", [], "Fabriek van ventilatie"), mention("Pieter De Smet", description="Directeur du site de Gand")],
        "c.docx": [mention("Gand", "site", description="Usine de ventilation")],
    }
    merged = {e["name"]: e for e in merge_entities(found, {"a.docx": "2025-01-01", "b.docx": "2026-01-01"})}
    assert set(merged) == {"Gand", "Pieter De Smet"}
    assert merged["Gand"]["aliases"] == ["Gent"] and merged["Gand"]["documents"] == ["a.docx", "b.docx", "c.docx"]
    assert [d["text"] for d in merged["Gand"]["descriptions"]] == ["Fabriek van ventilatie", "Usine de ventilation"]


def test_an_alias_two_people_claim_merges_nothing_and_is_dropped():
    found = {"a": [mention("Laurent Dewit", aliases=["CFO"])], "b": [mention("Claire Dumont", aliases=["CFO"])]}
    merged = merge_entities(found)
    assert len(merged) == 2 and all(e["aliases"] == [] for e in merged)


def test_the_review_drops_merges_renames_and_adds_aliases():
    entities = merge_entities({"a": [mention("Atlas", "projet"), mention("Projet ERP", "projet"), mention("Salle Meuse", "site")]})
    review = {"drop": ["Salle Meuse"], "merge": {"Atlas": ["Projet ERP"]}, "rename": {"Atlas": "Projet Atlas"},
              "aliases": {"Projet Atlas": ["Praxio"]}}
    (atlas,) = apply_review(entities, review)
    assert atlas["name"] == "Projet Atlas" and set(atlas["aliases"]) == {"Projet ERP", "Atlas", "Praxio"}


LAYER = [
    {"name": "Aéris 12", "kind": "produit", "aliases": ["Aeris12"], "documents": ["rappel.docx", "pv.docx"],
     "descriptions": [{"text": "Pompe à chaleur rappelée", "document": "pv.docx", "date": "2026-03-02"}]},
    {"name": "Aéris", "kind": "produit", "aliases": [], "documents": [f"d{i}" for i in range(40)],
     "descriptions": [{"text": "Gamme de pompes à chaleur", "document": "d0", "date": None}]},
    {"name": "Pieter De Smet", "kind": "personne", "aliases": [], "documents": ["02_RH/Confidentiel/salaires.xlsx"],
     "descriptions": [{"text": "Directeur du site de Gand", "document": "02_RH/Confidentiel/salaires.xlsx", "date": None}]},
]


def layer(tmp_path, monkeypatch, readable=lambda role, path: True):
    path = tmp_path / "entities.json"
    path.write_text(json.dumps(LAYER), encoding="utf-8")
    entities_module.load_entities.cache_clear()
    entities_module.keys_of.cache_clear()
    monkeypatch.setattr(entities_module, "can_read", readable)
    return str(path)


def test_the_longest_name_wins_and_a_span_is_matched_once(tmp_path, monkeypatch):
    path = layer(tmp_path, monkeypatch)
    assert [e["name"] for e in find_entities("Où en est le rappel de l'AERIS 12 ?", path)] == ["Aéris 12"]
    assert [e["name"] for e in find_entities("La gamme Aéris et l'Aéris 12", path)] == ["Aéris", "Aéris 12"]
    assert find_entities("Quel est l'effectif ?", path) == []


def test_only_specific_entities_narrow_the_search(tmp_path, monkeypatch):
    path = layer(tmp_path, monkeypatch)
    named = find_entities("La gamme Aéris et l'Aéris 12", path)
    assert entity_documents(named, {"search": {"entity_max_documents": 15}}) == ["rappel.docx", "pv.docx"]


def test_the_card_names_what_the_entities_are_and_hides_what_the_role_cannot_read(tmp_path, monkeypatch):
    path = layer(tmp_path, monkeypatch, readable=lambda role, p: role is None or "Confidentiel" not in p)
    named = find_entities("Pieter De Smet a-t-il validé le rappel de l'Aéris 12 ?", path)
    full = card(named)
    assert full["text"].splitlines()[1:] == [
        "- Pieter De Smet (personne) : Directeur du site de Gand (source : salaires)",
        "- Aéris 12 (produit ; aussi : Aeris12) : Pompe à chaleur rappelée (source : pv, 2026-03-02)"]
    assert "Pieter" not in card(named, role="commercial")["text"]
    assert entity_documents(named, {"search": {}}, role="commercial") == ["rappel.docx", "pv.docx"]


def test_the_entities_documents_add_one_restricted_dense_search(monkeypatch):
    monkeypatch.setattr("rag_calorvia.rag.search.dense_vectors", lambda texts, config: [[0.1]] * len(list(texts)))
    config = {"search": {"candidates": 30, "fusion": "rrf", "rrf_k": 60}}
    status = models.Filter(must_not=[models.FieldCondition(key="status", match=models.MatchAny(any=["draft"]))])
    plain = hybrid_request({"fr": "q"}, config, status)["prefetch"]
    wider = hybrid_request({"fr": "q"}, config, status, documents=["pv.docx"])["prefetch"]
    assert len(plain) == 2 and len(wider) == 3
    assert wider[2].filter.must[0].key == "document" and wider[2].filter.must_not == status.must_not
