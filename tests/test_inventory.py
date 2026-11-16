from rag_calorvia.etl.inventory import Document, apply_exclusions, is_empty, normalize_text, rule_reason

RULES = [
    {"path": "00_Direction/Modeles/", "reason": "template"},
    {"path": "02_RH/Confidentiel/Entretiens.xlsx", "reason": "personal_data"},
]


def doc(path, content_hash="h", fmt=None, text_chars=10, has_text_layer=None):
    fmt = fmt or path.rsplit(".", 1)[-1]
    return Document(path=path, format=fmt, size_bytes=1, sha256="s-" + path, content_hash=content_hash,
                    text_chars=text_chars, has_text_layer=has_text_layer)


def test_normalize_text_ignores_layout_case_and_punctuation():
    assert normalize_text("Politique  de\ntélétravail — V3.") == normalize_text("POLITIQUE DE TÉLÉTRAVAIL V3")


def test_normalize_text_keeps_digits():
    assert normalize_text("Vitesse : 6 km/h") != normalize_text("Vitesse : 8 km/h")


def test_rule_matches_folder_prefix_and_exact_file_only():
    assert rule_reason("00_Direction/Modeles/Modele PV CODIR.docx", RULES) == "template"
    assert rule_reason("02_RH/Confidentiel/Entretiens.xlsx", RULES) == "personal_data"
    assert rule_reason("02_RH/Confidentiel/Grille salariale 2026.xlsx", RULES) is None
    assert rule_reason("00_Direction/ModelesX/a.docx", RULES) is None


def test_scan_is_not_empty_but_empty_docx_is():
    assert not is_empty(doc("scan.pdf", text_chars=0, has_text_layer=False))
    assert is_empty(doc("blank.docx", text_chars=0))
    assert not is_empty(doc("photo.jpg", fmt="jpg", text_chars=0))  # images are left to the VLM


def test_archive_copy_is_the_duplicate():
    docs = apply_exclusions([doc("99_Archives/Doublons/a.docx"), doc("01_Finance/a.docx")], [])
    archived, home = docs
    assert archived.excluded_reason == "duplicate" and archived.duplicate_of == "01_Finance/a.docx"
    assert home.excluded_reason is None


def test_docx_is_kept_over_its_pdf_export():
    docs = apply_exclusions([doc("02_RH/p.pdf"), doc("02_RH/p.docx")], [])
    assert {d.path: d.excluded_reason for d in docs} == {"02_RH/p.pdf": "duplicate", "02_RH/p.docx": None}


def test_excluded_file_never_becomes_the_kept_copy():
    docs = apply_exclusions([doc("00_Direction/Modeles/m.docx"), doc("99_Archives/m.docx")], RULES)
    template, archived = docs
    assert template.excluded_reason == "template"
    assert archived.excluded_reason is None  # the only copy left: kept, even in the archives


def test_different_content_is_not_a_duplicate():
    docs = apply_exclusions([doc("a.docx", "h1"), doc("b.docx", "h2")], [])
    assert all(d.excluded_reason is None for d in docs)
