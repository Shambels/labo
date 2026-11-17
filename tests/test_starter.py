"""Unit tests of the starter-question check (no database, no course material: synthetic answers only)."""
from datetime import date, datetime
from decimal import Decimal

from text2sql_calorvia.starter import expected_tokens, matches, result_values, starter_queries


def test_french_numbers_and_dates():
    assert expected_tokens("1 234 567,89 €, soit 9,4 %") == [Decimal("1234567.89"), Decimal("9.4")]
    assert expected_tokens("12 reçues le 05/01/2026") == [Decimal(12), date(2026, 1, 5)]
    # no-break and narrow no-break spaces as thousands separators
    assert expected_tokens("1 230 et 2 000") == [Decimal(1230), Decimal(2000)]


def test_a_comma_followed_by_a_space_separates_two_numbers():
    assert expected_tokens("Gand 190, Herstal 6") == [Decimal(190), Decimal(6)]


def test_numbers_match_at_the_written_precision():
    values = result_values([(Decimal("9.43"), Decimal("1278366.78"))])
    assert matches(Decimal("9.4"), values)
    assert matches(Decimal("1278366.78"), values)
    assert not matches(Decimal("9.5"), values)


def test_negative_quantities_and_dates():
    values = result_values([(Decimal("-386.000"), datetime(2025, 12, 3, 14, 0))])
    assert matches(Decimal(386), values)          # a return is a negative stock movement
    assert matches(date(2025, 12, 3), values)
    assert matches(Decimal(3), values)            # "le 3"
    assert matches(Decimal(2025), values)         # "décembre 2025"
    assert not matches(date(2025, 12, 4), values)


def test_every_question_has_a_query_on_a_known_source():
    queries = starter_queries()
    assert sorted(queries) == list(range(1, 13))
    assert {source for qs in queries.values() for source, _, _ in qs} == {"erp", "compta", "paie"}
    assert len(queries[11]) == 2 and len(queries[12]) == 2   # the two cross-source questions
