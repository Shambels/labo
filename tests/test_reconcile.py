"""Cross-source reconciliation (step 13): keys normalized per type, amounts compared, nothing lost silently."""
import pytest

from text2sql_calorvia.reconcile import key_staff_number, key_text, key_vat, reconcile


def test_keys_are_normalized_the_same_way_on_both_sides():
    assert key_vat("BE 0236.099.757") == key_vat("be0236099757") == "BE0236099757"
    assert key_staff_number("M10405") == key_staff_number(10405) == key_staff_number("m010405") == "10405"
    assert key_text("Distrinergie S.A.") == key_text("DISTRINERGIE SA")


def test_reconcile_matches_on_vat_and_reports_differences_and_orphans():
    erp = {"columns": ["CLI_TVA", "ca_erp"],
           "rows": [["BE0236099757", 100.0], ["BE0236099757", 50.0], ["BE0111222333", 80.0], ["BE0999", 5.0]]}
    compta = {"columns": ["numero_tva", "ca_compta"],
              "rows": [["BE 0236.099.757", 150.0], ["BE 0111.222.333", 70.0], ["BE 0444", 9.0]]}
    r = reconcile(erp, compta, "cli_tva", "NUMERO_TVA", "vat", compare=[["ca_erp", "ca_compta"]])
    assert (r["matched"], r["only_left"], r["only_right"], r["differences"]) == (2, 1, 1, 1)
    assert r["difference_rows"] == [{"key": "BE0111222333", "left_key": "BE0111222333",
                                     "right_key": "BE 0111.222.333", "ca_erp - ca_compta": 10.0}]
    assert r["totals"]["ca_erp / ca_compta"] == {"left": 235.0, "right": 229.0, "difference": 6.0,
                                                  "left_matched": 230.0, "right_matched": 220.0}
    assert r["only_left_rows"][0]["ca_erp"] == 5.0 and r["only_right_rows"][0]["ca_compta"] == 9.0


def test_reconcile_refuses_unknown_columns_and_key_types():
    result = {"columns": ["a"], "rows": [[1]]}
    with pytest.raises(ValueError, match="Colonne b absente"):
        reconcile(result, result, "a", "b")
    with pytest.raises(ValueError, match="key_type inconnu"):
        reconcile(result, result, "a", "a", "iban")
