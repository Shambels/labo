"""The certified ontology as the agent's knowledge (step 12 → 13, D49)."""
from text2sql_calorvia import ontology


def test_terms_are_found_by_source_and_table_without_case():
    terms = ontology.terms_for("erp", "VTE_FACT")
    assert [t["term"] for t in terms] == ["Customer Invoice and Credit Note (facture et avoir client)"]
    assert "POSITIFS" in terms[0]["definition"] and terms[0]["certified"]
    assert ontology.terms_for("erp", "PAR_CODE") == []


def test_every_certified_term_and_metric_maps_to_a_source():
    data = ontology.load()
    assert len(data["terms"]) == 28 and len(data["metrics"]) == 11
    assert {t["source"] for t in data["terms"] + data["metrics"]} == {"erp", "compta", "paie"}


def test_the_glossary_carries_definitions_and_reference_sql():
    glossary = ontology.glossary()
    assert "**Net result (résultat net)** (compta, ligne_ecriture)" in glossary
    assert "l.numero_compte <> '693000'" in glossary


def test_the_card_of_a_table_carries_its_certified_term(sources):
    from text2sql_calorvia.cards import get_table_card
    assert get_table_card("compta", "ligne_ecriture")["ontology_terms"][0]["term"].startswith("Accounting Entry Line")


def test_a_word_with_several_readings_gets_the_ones_the_answer_left_out():
    note = ontology.other_readings("Quel est le résultat de mars 2026 ?", "Le résultat net est de 10 €.")
    assert "EBITDA" in note and "résultat d'exploitation" in note and "résultat net ;" not in note
    assert "dites-le-moi" in note


def test_a_question_that_settles_the_reading_gets_no_note():
    assert ontology.other_readings("Quel est le résultat net de 2025 ?", "10 €") == ""
    assert ontology.other_readings("Quel est le chiffre d'affaires net facturé de mars ?", "10 €") == ""
    assert ontology.other_readings("Le chiffre d’affaires est-il le même dans l'ERP ?", "10 €") == ""


def test_an_answer_naming_every_reading_gets_no_note():
    answer = "Facturé dans l'ERP : 10 €. Comptabilisé : 10 €."
    assert ontology.other_readings("Quel est le chiffre d'affaires de mai ?", answer) == ""


def test_a_question_without_such_a_word_gets_no_note():
    assert ontology.other_readings("Combien de factures en avril ?", "570") == ""


def test_every_reading_of_a_business_word_is_usable():
    for word in ontology.load()["business_words"]:
        assert len(word["readings"]) >= 2 and word["patterns"]
        assert all(r["label"] and r["names"] and r["source"] in {"erp", "compta", "paie"} for r in word["readings"])
