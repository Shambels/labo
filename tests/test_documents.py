"""Phase D, step 28: which documents each role may read. The Qdrant tests are skipped until
scripts/apply_document_roles.py has run; they use BM25, so they need no embedder."""
import tomllib
from pathlib import Path

import pytest
from qdrant_client import models
from qdrant_client.http.exceptions import ResponseHandlingException, UnexpectedResponse
from streamlit.testing.v1 import AppTest

from rag_calorvia.etl.chunk import ACCESS_FIELD
from rag_calorvia.etl.index import collection_name, get_qdrant
from rag_calorvia.rag import images, permissions, tables
from rag_calorvia.rag.pipeline import question_filter
from rag_calorvia.rag.search import search
from text2sql_calorvia import policy

CONFIG = tomllib.loads(Path("experiments/status_filter.toml").read_text())
SPARSE = {**CONFIG, "search": {**CONFIG["search"], "method": "sparse"}}
QUESTIONS = ["budget 2026", "décision du CODIR", "grille salariale", "contrat d'assurance", "politique de télétravail",
             "maintenance Gent", "rappel Aeris 12", "tarif", "sécurité informatique", "communiqué de presse"]


@pytest.mark.parametrize("role, path, allowed", [
    ("direction", "08_Juridique/Contrats/x.pdf", True),
    ("direction", "99_Archives/2024/x.pdf", True),
    ("finance", "01_Finance/Budget_2026/x.xlsx", True),
    ("finance", "00_Direction/CODIR/2025/x.docx", True),
    ("finance", "00_Direction/Strategie/x.docx", False),
    ("finance", "02_RH/Confidentiel/Grille salariale 2026.xlsx", False),
    ("rh", "02_RH/Confidentiel/Grille salariale 2026.xlsx", True),
    ("commercial", "04_Qualite/Reclamations/x.pdf", True),
    ("commercial", "04_Qualite/Audits/x.pdf", False),
    ("operations", "04_Qualite/Audits/x.pdf", False),
    ("qualite", "04_Qualite/Audits/x.pdf", True),
    ("responsable_site_gent", "03_Production/Gent/x.pdf", True),
    ("responsable_site_gent", "03_Production/Seneffe/x.pdf", False),
    ("responsable_site_namur", "03_Production/Procedures/x.pdf", True),
    ("it", "07_IT/Securite/x.pdf", True),
    ("employe", "09_Communication/Newsletter/x.pdf", True),
    ("employe", "02_RH/Politiques/x.pdf", True),
    ("employe", "02_RH/Recrutement/x.pdf", False),
    ("employe", "01_Finance/x.pdf", False),
])
def test_the_policy_gives_each_role_its_documents(role, path, allowed):
    assert policy.may_read(role, path) is allowed


def test_a_folder_rule_does_not_match_a_similar_name():
    assert policy.matches("02_RH", "02_RH/a.pdf") and not policy.matches("02_RH", "02_RH_old/a.pdf")


def test_a_role_entitled_to_any_copy_reads_the_document():
    roles = permissions.roles_for(["06_Achats/Grille.xlsx", "00_Direction/CODIR/Annexes/Grille.xlsx"])
    assert {"achats", "finance", "direction"} <= set(roles) and "commercial" not in roles


def test_a_document_nobody_is_given_is_left_to_the_role_reading_everything():
    assert permissions.roles_for(["99_Archives/Divers/x.pdf"]) == ["direction"]


def test_the_role_is_a_required_condition_of_the_filter():
    built = question_filter({"search": {"exclude_status": ["draft"]}}, None, "finance")
    assert built.must[0].key == ACCESS_FIELD and built.must[0].match.value == "finance" and built.must_not
    assert question_filter({"search": {}}, None) is None


@pytest.fixture
def indexed():
    try:
        name = collection_name(CONFIG)
        info = get_qdrant().get_collection(name)
    except (ResponseHandlingException, UnexpectedResponse, OSError):
        pytest.skip("Qdrant is not running")
    if ACCESS_FIELD not in (info.payload_schema or {}):
        pytest.skip("run scripts/apply_document_roles.py first")
    return name


@pytest.mark.parametrize("role", list(policy.roles()))
def test_a_search_returns_only_what_the_role_may_read(indexed, role):
    for question in QUESTIONS:
        for chunk in search(question, SPARSE, question_filter(SPARSE, None, role)):
            assert permissions.can_read(role, chunk["document"]), chunk["document"]
            assert role in chunk[ACCESS_FIELD]


def test_every_chunk_has_its_roles(indexed):
    empty = models.Filter(must=[models.IsEmptyCondition(is_empty=models.PayloadField(key=ACCESS_FIELD))])
    assert get_qdrant().count(indexed, count_filter=empty, exact=True).count == 0


def test_a_role_finds_its_documents_and_another_does_not(indexed):
    found = lambda role: {c["document"] for c in search("grille salariale", SPARSE, question_filter(SPARSE, None, role))}  # noqa: E731
    target = "02_RH/Confidentiel/Grille salariale 2026.xlsx"
    assert target in found("rh") and target not in found("commercial")


def test_the_workbook_tools_hold_only_the_role_s_workbooks(indexed):
    documents = {row[0] for row in tables.get_store("commercial").execute("SELECT DISTINCT document FROM catalog")}
    assert documents and all(permissions.can_read("commercial", d) for d in documents)
    assert not any(d.startswith(("01_Finance", "02_RH/Confidentiel")) for d in documents)


def test_an_image_needs_the_right_to_read_it(indexed):
    with pytest.raises(PermissionError):
        images.image_bytes("03_Production/Gent/x.jpg", role="commercial")


@pytest.fixture
def keys(monkeypatch):
    from text2sql_calorvia.config import settings
    monkeypatch.setattr(settings, "api_keys", "alice:good-key")
    monkeypatch.setattr(settings, "user_roles", "alice:finance")


def test_a_key_gives_the_user_and_the_role(keys):
    assert permissions.identify("good-key") == ("alice", "finance")
    assert permissions.identify("bad-key") is None


def test_without_keys_the_chat_is_in_local_mode():
    assert permissions.identify("") == (None, None)


def test_the_chat_asks_for_a_key_and_refuses_a_wrong_one(keys):
    app = AppTest.from_file(str(Path(__file__).parents[1] / "app" / "chat.py"), default_timeout=20).run()
    assert not app.chat_input and app.text_input[0].label == "Clé d'accès"
    app.text_input[0].input("bad-key")
    app.button[0].click().run()
    assert app.error[0].value == "Clé invalide." and not app.chat_input
    app.text_input[0].input("good-key")
    app.button[0].click().run()
    assert app.chat_input and any("finance" in str(m.value) for m in app.sidebar.markdown)
