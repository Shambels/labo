from datetime import datetime

import pytest
from openpyxl import Workbook

from rag_calorvia.etl.excel import SMALL_TABLE_ROWS, Table, read_workbook, row_sentence, table_groups, workbook_pieces


@pytest.fixture
def reporting(tmp_path):
    """A small reporting workbook: merged title, subtitle with the unit, a table with a percentage, a note,
    and a comments sheet without any table."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Synthèse"
    ws.append(["Reporting mensuel · mars 2026"])
    ws.merge_cells("A1:C1")
    ws.append(["Montants en k€"])
    ws.append(["Indicateur", "Mois", "Écart au budget"])
    ws.append(["Chiffre d'affaires", 13600.0, -0.00681316572305923])
    ws["C4"].number_format = "0.0%"
    ws.append(["Clôture", datetime(2026, 4, 3), None])
    ws.append(["Source : contrôle de gestion"])
    comments = wb.create_sheet("Commentaires")
    comments.append(["Reprise partielle de provision : Valtek prend en charge 65 % du coût du rappel."])
    path = tmp_path / "Reporting 2026-03.xlsx"
    wb.save(path)
    return path


def test_tables_keep_title_unit_header_and_notes(reporting):
    table, text = read_workbook(reporting)
    assert table.sheet == "Synthèse"
    assert table.title == "Reporting mensuel · mars 2026 · Montants en k€"
    assert table.header == ["Indicateur", "Mois", "Écart au budget"]
    assert table.notes == ["Source : contrôle de gestion"]
    assert table.first_row == 4
    assert text.sheet == "Commentaires" and "Valtek" in text.lines[0]


def test_values_are_displayed_as_in_excel(reporting):
    table = read_workbook(reporting)[0]
    assert table.rows[0] == ["Chiffre d'affaires", "13600", "-0,7 %"]  # integer without .0, percentage formatted
    assert table.rows[1][1] == "03/04/2026"


def test_row_sentence_names_every_value(reporting):
    table = read_workbook(reporting)[0]
    assert row_sentence(table, table.rows[0]) == (
        "onglet « Synthèse » · Reporting mensuel · mars 2026 · Montants en k€ · "
        "Indicateur : Chiffre d'affaires ; Mois : 13600 ; Écart au budget : -0,7 %")


def test_pieces_of_a_small_table(reporting):
    kinds = [p["kind"] for p in workbook_pieces(reporting, fits=lambda text: True)]
    assert kinds == ["table", "row", "row", "text"]


def test_big_tables_get_a_summary_and_groups_with_the_header():
    table = Table("Unités", None, ["Numéro", "Statut"], [[f"AE12-{i}", "Réparée"] for i in range(SMALL_TABLE_ROWS + 10)], 2)
    groups = table_groups(table, fits=lambda text: text.count("\n") <= 12)  # heading + header (2 lines) + 10 rows
    assert len(groups) == 4
    assert all(text.splitlines()[1].startswith("| Numéro | Statut |") for _, _, text in groups)
    assert groups[1][2].splitlines()[0].endswith("lignes 11 à 20")


def test_a_key_value_line_is_text_not_an_empty_table(tmp_path):
    wb = Workbook()
    ws = wb.active
    ws.append(["Formation", "Heures"])
    ws.append(["Caristes", 160])
    ws.append([])
    ws.append(["Heures de formation à la sécurité", None, 620])
    path = tmp_path / "plan.xlsx"
    wb.save(path)
    table, text = read_workbook(path)
    assert table.rows == [["Caristes", "160"]]
    assert text.lines == ["Heures de formation à la sécurité : 620"]


def test_the_summary_counts_the_values_of_categorical_columns():
    from rag_calorvia.etl.excel import summary_text
    rows = [[f"AE12-{i}", "Réparée"] for i in range(40)] + [[f"AE12-{i}", "Introuvable"] for i in range(40, 43)]
    table = Table("Unités", None, ["Numéro", "Statut"], rows, 2)
    summary = summary_text(table)
    assert "tableau de 43 lignes" in summary
    assert "Statut : Réparée (40), Introuvable (3)." in summary
    assert "Numéro :" not in summary  # 43 distinct values: not a category
