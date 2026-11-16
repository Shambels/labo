from datetime import date

import pytest

from rag_calorvia.etl.metadata import (
    content_date,
    department,
    doc_type,
    document_date,
    markers,
    source_type,
    status,
    version,
)


@pytest.mark.parametrize("path, start, end, precision, source", [
    ("00_Direction/CODIR/2025/PV_CODIR_2025-10-13.docx", date(2025, 10, 13), date(2025, 10, 13), "day", "filename"),
    ("00_Direction/CODIR/2025/PV_CODIR_2025-11-17_v2.docx", date(2025, 11, 17), date(2025, 11, 17), "day", "filename"),
    ("00_Direction/CODIR/2026/2026-01-14 CODIR extraordinaire PV.docx", date(2026, 1, 14), date(2026, 1, 14), "day", "filename"),
    ("00_Direction/Conseil_administration/PV_signes/PV CA 2025-11-18 signé.pdf", date(2025, 11, 18), date(2025, 11, 18), "day", "filename"),
    ("07_IT/Projet_Atlas_ERP/COPIL/COPIL_Atlas_05_20260219.docx", date(2026, 2, 19), date(2026, 2, 19), "day", "filename"),
    ("01_Finance/Budget_2026/Budget 2026 - version approuvee CA 16-12-2025.xlsx", date(2025, 12, 16), date(2025, 12, 16), "day", "filename"),
    ("01_Finance/Reporting_mensuel/Reporting 2026-03.xlsx", date(2026, 3, 1), date(2026, 3, 31), "month", "filename"),
    ("03_Production/Gent/Maandrapporten/Productierapport Gent 2026-02.xlsx", date(2026, 2, 1), date(2026, 2, 28), "month", "filename"),
    ("04_Qualite/Indicateurs/Rebut par ligne decembre 2025.png", date(2025, 12, 1), date(2025, 12, 31), "month", "filename"),
    ("01_Finance/Reporting_mensuel/Commentaires de gestion T4 2025.pdf", date(2025, 10, 1), date(2025, 12, 31), "quarter", "filename"),
    ("02_RH/Effectifs/Effectifs mensuels 2025-2026.xlsx", date(2025, 1, 1), date(2026, 12, 31), "range", "filename"),
    ("03_Production/Seneffe/Photos_equipements/IMG_20260311_Presse_plieuse.jpg", date(2026, 3, 11), date(2026, 3, 11), "day", "photo"),
    ("02_RH/Notes_de_service/2026-01-05 NS-2026-01 Gel des recrutements des fonctions support.docx", date(2026, 1, 5), date(2026, 1, 5), "day", "filename"),
    ("01_Finance/Comptabilite/Factures_fournisseurs/2026-01-08 Tolerie Mosane TM-2026-0042.jpg", date(2026, 1, 8), date(2026, 1, 8), "day", "filename"),
])
def test_dates_from_file_names(path, start, end, precision, source):
    found = document_date(path, "")
    assert (found.start, found.end, found.precision, found.source) == (start, end, precision, source)


def test_codes_in_file_names_are_not_months():
    # 'TM-2025-0391' or 'NC-2025-047' look like '2025-03' / '2025-04' to a careless pattern
    assert document_date("x/NC-2025-047.docx", "").precision == "year"
    assert document_date("x/Facture TM-2025-0391.jpg", "").precision == "year"


def test_content_date_when_the_name_has_none():
    text = "Fiche de non-conformité NC-2025-047\n| Date d'ouverture | 02/12/2025 |"
    found = document_date("04_Qualite/Non_conformites/NC-2025-047.docx", text)
    assert (found.start, found.source) == (date(2025, 12, 2), "content")


@pytest.mark.parametrize("text, expected", [
    ("Séance du lundi 13 octobre 2025, Namur", date(2025, 10, 13)),
    ("Mise en production le 1er avril 2026", date(2026, 4, 1)),
    ("Actieplan veiligheid (stand van zaken 26 januari 2026)", date(2026, 1, 26)),
    ("Term: three years from 1 February 2025.", date(2025, 2, 1)),
    ("Publiée le 04/05/2026. Prise de fonction le 1er juin 2026.", date(2026, 5, 4)),  # the first one wins
])
def test_content_dates_in_three_languages(text, expected):
    assert content_date(text).start == expected


def test_invalid_dates_are_ignored():
    assert content_date("Référence 31/02/2026") is None


def test_workbook_only_reads_its_title_line():
    text = "Liste des unités concernées\n| AE12-25-4501 | 03/11/2025 | Distrinergie |"
    assert content_date(text, first_line_only=True) is None
    assert content_date("Tarif 2026 · en vigueur au 01/01/2026\n| Aéris 6 | 7 130 |", first_line_only=True).start == date(2026, 1, 1)


@pytest.mark.parametrize("path, expected", [
    ("00_Direction/CODIR/2025/PV_CODIR_2025-10-13.docx", "codir_minutes"),
    ("99_Archives/2024/PV_CODIR_2024-12-16.docx", "codir_minutes"),
    ("00_Direction/CODIR/Annexes/2025-12-08 Annexe - Rapport 8D Aeris 12.pdf", "codir_annex"),
    ("00_Direction/Conseil_administration/Projets_PV/Projet PV CA 2025-11-18.docx", "board_minutes"),
    ("03_Production/Gent/Veiligheid/Comite PBW/Verslag Comite PBW Gent 2026-01-22.docx", "safety_committee"),
    ("00_Direction/Strategie/Photo tableau SWOT seminaire 2025-08-26.jpg", "photo"),
    ("05_Commercial/Comptes_cles/Avenant tarifaire Distrinergie 2026 signe.pdf", "contract"),
    ("05_Commercial/Tarifs/Tarif 2026 - projet v1.xlsx", "price_list"),
    ("01_Finance/Investissements/Suivi capex 2026.xlsx", "workbook"),
    ("07_IT/Support/README.md", "other"),
])
def test_doc_types(path, expected):
    assert doc_type(path)[0] == expected


@pytest.mark.parametrize("path, expected_version, expected_status", [
    ("00_Direction/CODIR/2025/PV_CODIR_2025-11-17_v2.docx", "v2", None),
    ("03_Production/Procedures/MO-SEN-07 Brasage des vannes 4 voies rev C.pdf", "rev C", None),
    ("00_Direction/Conseil_administration/Projets_PV/Projet PV CA 2026-02-17 v1.docx", "v1", "draft"),
    ("00_Direction/Conseil_administration/PV_signes/PV CA 2026-02-17.pdf", None, "signed"),
    ("99_Archives/Doublons/Budget 2026 v2 FINAL.xlsx", "v2", "copy"),
    ("99_Archives/Doublons/Politique teletravail v3 (2026) (1).docx", "v3", "copy"),
    ("99_Archives/2024/Tarif 2024.xlsx", None, "archive"),
    ("00_Direction/Modeles/Modele PV CODIR.docx", None, "template"),
    ("09_Communication/Intranet/Le projet Atlas en 10 questions.html", None, None),  # a project, not a draft
    ("03_Production/Procedures/Consignes EPI usine Seneffe.pdf", None, None),          # 'Consignes' is not 'signé'
])
def test_versions_and_status(path, expected_version, expected_status):
    assert version(path) == expected_version
    assert status(markers(path)) == expected_status


def test_final_in_name_is_recorded_but_is_not_a_status():
    found = markers("99_Archives/Doublons/Budget 2026 v2 FINAL.xlsx")
    assert "final_in_name" in found and status(found) == "copy"


def test_department_and_source_type():
    assert department("03_Production/Gent/x.docx") == "Production"
    assert source_type("pdf", False) == "scan"
    assert source_type("pdf", True) == "text"
    assert source_type("xlsx", None) == "table"
    assert source_type("png", None) == "image"
