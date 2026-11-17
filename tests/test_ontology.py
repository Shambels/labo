"""The certified ontology as the agent's knowledge (step 12 → 13, D49)."""
from text2sql_calorvia import ontology


def test_terms_are_found_by_source_and_table_without_case():
    terms = ontology.terms_for("erp", "VTE_FACT")
    assert [t["term"] for t in terms] == ["Customer Invoice and Credit Note (facture et avoir client)"]
    assert "POSITIFS" in terms[0]["definition"] and terms[0]["certified"]
    assert ontology.terms_for("erp", "PAR_CODE") == []


def test_every_certified_term_and_metric_maps_to_a_source():
    data = ontology.load()
    assert len(data["terms"]) == 27 and len(data["metrics"]) == 8
    assert {t["source"] for t in data["terms"] + data["metrics"]} == {"erp", "compta", "paie"}


def test_the_glossary_carries_definitions_and_reference_sql():
    glossary = ontology.glossary()
    assert "**Net result (résultat net)** (compta, ligne_ecriture)" in glossary
    assert "l.numero_compte <> '693000'" in glossary


def test_the_card_of_a_table_carries_its_certified_term(sources):
    from text2sql_calorvia.cards import get_table_card
    assert get_table_card("compta", "ligne_ecriture")["ontology_terms"][0]["term"].startswith("Accounting Entry Line")
