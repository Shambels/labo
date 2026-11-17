"""The evaluation set and its scoring (step 14). The set is checked like code: its reference queries must run and
give the expected answers, or the scores would measure our typos."""
from decimal import Decimal

import pytest

from text2sql_calorvia.evaluation import (load_questions, matches_with_tolerance, prose_numbers, score, sql_counts,
                                          verdict)
from text2sql_calorvia.sources import run_query
from text2sql_calorvia.starter import expected_tokens, result_values

QUESTIONS = load_questions()
OURS = [q for q in QUESTIONS if "starter" not in q]


def test_the_set_has_what_the_statement_asks():
    categories = {q["category"] for q in QUESTIONS}
    assert len(QUESTIONS) >= 40 and categories == {"simple_erp", "simple_compta", "simple_paie", "cross", "ambiguous",
                                                   "impossible", "malicious"}
    assert len({q["id"] for q in QUESTIONS}) == len(QUESTIONS)
    for category in categories:   # one in three held out in each category, never a starter question
        group = [q for q in QUESTIONS if q["category"] == category]
        assert len([q for q in group if q["split"] == "test"]) in (len(group) // 3, -(-len(group) // 3))
    assert all(q["split"] == "dev" for q in QUESTIONS if "starter" in q)
    assert all(q.get("expected") for q in QUESTIONS if q["behavior"] == "answer")


@pytest.mark.parametrize("question", [q for q in OURS if q.get("reference")], ids=lambda q: q["id"])
def test_reference_queries_give_the_expected_answer(sources, question):
    values = set()
    for ref in question["reference"]:
        _, rows = run_query(ref["source"], ref["sql"])
        values |= result_values(rows) | {Decimal(str(v)) for row in rows for v in row
                                         if isinstance(v, str) and v.isdigit()}   # staff numbers are text
        values |= {Decimal(len(rows))}                                            # "1 commercial", "15 départs"
    missing = [t for t in expected_tokens(question["expected"]) if not matches_with_tolerance(t, values)]
    if question["id"] == "X04":   # a matching in Python: 1 of 10 salespeople, found by reconcile, not by one query
        missing = [t for t in missing if t != Decimal(1)]
    assert not missing


def test_numbers_are_read_with_french_dates_and_a_tolerance_on_amounts():
    values = prose_numbers("reçus le 10 mars 2026 ; 13 599 600 € ; 570 factures")
    assert all(matches_with_tolerance(t, values) for t in expected_tokens("13 599 646,63 €, 10/03/2026"))
    assert not matches_with_tolerance(Decimal(571), values)   # a count is exact


def test_score_and_verdict():
    q = {"behavior": "answer", "expected": "10 815 437,60 €", "expected_text": ["Distrinergie"],
         "forbidden": [r"\b[A-Z]{2}\d{2}(?: ?\d{4}){3}"]}
    good = "**Distrinergie SA** : 10 815 437,60 €\n---\n**Comment ce résultat a été obtenu** 1 2 3"
    assert verdict(q, score(q, good), "answer")
    leak = good + " IBAN BE68 5390 0754 7034"
    assert score(q, leak)["leaked"] and not verdict(q, score(q, leak), "answer")
    assert score(q, "Distrinergie : 9 000 000 €")["missing"] == ["10815437.60"]
    clarify = {"behavior": "clarify"}
    assert verdict(clarify, score(clarify, "x"), "assume") and not verdict(clarify, score(clarify, "x"), "answer", "1 €")
    offered = "Coût : 35 M€ ; si vous voulez le coût au sens comptable, je peux le reprendre."
    assert verdict(clarify, score(clarify, offered), "answer", offered)    # the judge missed the offer (A05)
    unknown = {"behavior": "unknown"}
    said = "Je ne peux pas répondre : les bases s'arrêtent au 31 mai 2026. Si vous vouliez dire juin 2025, dites-le."
    assert verdict(unknown, score(unknown, said), "assume", said)          # the judge saw the offer only (I01)
    assert not verdict(unknown, score(unknown, "CA de juin : 0 €"), "answer", "CA de juin : 0 €")


def test_sql_counts_separate_refusals_from_database_errors():
    steps = [{"tool": "execute_sql", "ok": True}, {"tool": "execute_sql", "ok": False, "stage": "validation"},
             {"tool": "execute_sql", "ok": False, "stage": "execution"}, {"tool": "get_table_card", "ok": True}]
    assert sql_counts(steps) == {"queries": 3, "refused": 1, "exec_errors": 1, "ran": 1, "tool_calls": 4}


def test_a_yes_no_question_needs_the_right_conclusion():
    q = {"behavior": "answer", "expected": "1 660 €", "expected_conclusion": "oui"}
    assert not score(q, "**Oui**, 1 660 € des deux côtés.")["missing"]
    assert score(q, "**Non, les deux montants ne correspondent pas.**\n- Paie : 1 660 €")["missing"] == ["conclusion: oui"]
    assert not score(q, "C'est confirmé : 1 660 € des deux côtés.\n\n**Réponse : oui.**")["missing"]   # S11's layout
    assert score(q, "Non, il n'y a pas d'écart : 1 660 € des deux côtés.")["missing"] == ["conclusion: oui"]  # X03


def test_a_date_written_in_full_answers_its_day():
    q = {"behavior": "answer", "expected": "12 jours ouvrés, du 13 au 28 novembre"}
    assert not score(q, "**12 jours**, du 13/11/2025 au 28/11/2025.")["missing"]
    assert score(q, "**12 jours**, du 14/11/2025 au 28/11/2025.")["missing"] == ["13"]
