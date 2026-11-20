"""Managing conversations (step 33): search, rename, archive, compaction, export; the routes and the chat page.

The storage tests use the course PostgreSQL (skipped when it is down) under user names of their own, removed after.
"""
import uuid
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient
from streamlit.testing.v1 import AppTest
from test_api import FakeAgent

from text2sql_calorvia import conversations, memory
from text2sql_calorvia.api import create_app
from text2sql_calorvia.config import settings

PREFIX = "test-conv-"
CHAT = str(Path(__file__).resolve().parents[1] / "app" / "chat.py")


@pytest.fixture
def db():
    """A user name of the test's own; every conversation of test users is deleted afterwards."""
    try:
        memory.ensure_schema()
    except psycopg.Error:
        pytest.skip("the course PostgreSQL (5432) is not running")
    yield f"{PREFIX}{uuid.uuid4().hex[:8]}"
    with memory.connect() as c:
        c.execute("DELETE FROM t2sql_conversations WHERE user_name LIKE %s", (PREFIX + "%",))


def conversation(user, turns, conversation_id=None):
    """A stored conversation of `turns` (question, answer) pairs; returns its id."""
    conversation_id = conversation_id or f"conv-{uuid.uuid4().hex}"
    for q, a in turns:
        memory.save_turn(conversation_id, user, q, a, [])
    return conversation_id


TURNS = [("Quel est le CA de mars 2026 ?", "**13 599 646,63 € HT** pour mars."),
         ("Et pour avril ?", "**12 099 823,09 € HT** pour avril."),
         ("Et pour mai ?", "**14 001 002,50 € HT** pour mai."),
         ("Combien de factures en mai ?", "**3 860 factures** en mai.")]


# --- without a database ---------------------------------------------------------------------------------------------
def test_a_search_text_is_matched_literally():
    assert memory.like_pattern("100%_a") == "%100\\%\\_a%"


def history(n_turns, last="Et la marge ?"):
    out = [m for q, a in TURNS[:n_turns] for m in ({"role": "user", "content": q}, {"role": "assistant", "content": a})]
    return out + [{"role": "user", "content": last}]


def test_the_summary_replaces_the_turns_it_covers():
    stored = history(4)[:-1]
    info = {"summary": "- mars : 13 599 646,63 €", "summary_messages": 4}
    out = conversations.with_summary(history(4), info, stored)
    assert out[0]["content"] == conversations.SUMMARY_QUESTION
    assert out[1]["content"].endswith("- mars : 13 599 646,63 €")
    assert out[2:] == history(4)[4:]          # the last two turns and the question, word for word


def test_a_history_that_is_not_the_stored_one_is_left_as_it_is():
    stored = history(4)[:-1]
    info = {"summary": "résumé", "summary_messages": 4}
    edited = history(4)
    edited[2]["content"] = "Et pour juin ?"   # the client edited a question the summary covers
    assert conversations.with_summary(edited, info, stored) == edited
    assert conversations.with_summary(history(1), info, stored) == history(1)   # shorter than the summary
    assert conversations.with_summary(history(4), {"summary": None, "summary_messages": 0}, stored) == history(4)


def test_a_message_is_cleaned_of_what_only_a_live_client_uses():
    text = ("<details>\n<summary>Étapes</summary>\n- ✓ requête\n</details>\n\nCA : 5 €"
            "\n\n![CA](http://localhost:9000/charts/0123456789abcdef.png?exp=1&sig=x)"
            "\n\n<!-- calorvia:conversation=chatcmpl-1 -->")
    assert conversations.clean(text) == "CA : 5 €"


# --- storage --------------------------------------------------------------------------------------------------------
def test_rename_archive_restore_and_only_by_the_owner(db):
    cid = conversation(db, TURNS[:1])
    assert not memory.rename(cid, db + "-other", "Volé")
    assert memory.rename(cid, db, "  CA   mensuel ")
    assert memory.conversation_info(cid)["title"] == "CA mensuel"
    with pytest.raises(ValueError):
        memory.rename(cid, db, "   ")
    assert memory.archive(cid, db)
    assert [c["id"] for c in memory.conversations(db)] == []
    assert [c["id"] for c in memory.conversations(db, archived=True)] == [cid]
    assert memory.archive(cid, db, False) and [c["id"] for c in memory.conversations(db)] == [cid]
    assert len(memory.conversation(cid)) == 2   # archiving keeps every message


def test_a_new_turn_brings_an_archived_conversation_back(db):
    cid = conversation(db, TURNS[:1])
    memory.archive(cid, db)
    memory.save_turn(cid, db, "Et pour avril ?", "12 099 823,09 €", [])
    assert not memory.conversation_info(cid)["archived"]


def test_search_reads_titles_and_messages(db):
    march = conversation(db, TURNS[:1])
    invoices = conversation(db, [("Combien de factures ?", "3 860 factures, dont 2 % d'avoirs.")])
    assert [c["id"] for c in memory.conversations(db, search="FACTURES")] == [invoices]
    assert [c["id"] for c in memory.conversations(db, search="13 599")] == [march]       # in an answer
    assert [c["id"] for c in memory.conversations(db, search="2 %")] == [invoices]       # % is a character
    assert memory.conversations(db, search="_") == []


def test_compaction_covers_all_but_the_last_turns_and_folds_the_previous_summary(db):
    cid = conversation(db, TURNS)
    seen = []

    def summarize(text, note=None):
        seen.append(text)
        return "- mars : 13 599 646,63 € HT ; avril : 12 099 823,09 € HT"

    done = conversations.compact(cid, db, keep_turns=2, summarize=summarize)
    assert done == {"summary": summarize(""), "summary_messages": 4, "kept_messages": 4}
    assert "Et pour avril ?" in seen[0] and "Et pour mai ?" not in seen[0]
    with pytest.raises(ValueError, match="Rien à compacter"):
        conversations.compact(cid, db, keep_turns=2, summarize=summarize)
    memory.save_turn(cid, db, "Et pour juin ?", "**9 876 543,21 € HT**", [])
    conversations.compact(cid, db, keep_turns=2, summarize=summarize)
    assert seen[-1].startswith("Résumé précédent :\n- mars") and "Et pour mai ?" in seen[-1]
    assert memory.conversation_info(cid)["summary_messages"] == 6


def test_a_summary_with_a_figure_the_turns_dont_have_is_retried_then_refused(db):
    cid = conversation(db, TURNS)
    notes = []

    def invents(text, note=None):
        notes.append(note)
        return "- mars : 13 599 646,63 € ; juin : 11 500 000 €"   # a month nobody asked about
    # (a sum or difference of two figures of the turns would pass: the check allows them, as for answers)

    with pytest.raises(ValueError, match="11 500 000"):
        conversations.compact(cid, db, summarize=invents)
    assert notes[0] is None and "11 500 000" in notes[1]
    assert memory.conversation_info(cid)["summary"] is None   # nothing stored


def test_the_export_holds_every_message_and_names_the_charts(db):
    cid = conversation(db, TURNS[:1])
    memory.save_turn(cid, db, "Fais-en un graphique", "Voici.\n\n![CA](http://localhost:9000/charts/0123456789abcdef.png"
                     "?exp=1&sig=x)", [{"tool": "make_chart", "ok": True, "args": {"title": "CA mensuel 2026"}}])
    text = conversations.export_markdown(cid, db)
    assert text.startswith("# Quel est le CA de mars 2026 ?")
    assert "13 599 646,63" in text and "*Graphique : CA mensuel 2026*" in text and "/charts/" not in text
    with pytest.raises(conversations.NotFound):
        conversations.export_markdown(cid, db + "-other")


# --- routes ---------------------------------------------------------------------------------------------------------
def test_routes_rename_archive_export_and_compact(db, monkeypatch):
    cid = conversation(db, TURNS)
    http = TestClient(create_app(FakeAgent()))
    r = http.patch(f"/v1/conversations/{cid}?user={db}", json={"title": "CA 2026", "archived": True})
    assert r.json() == {"id": cid, "title": "CA 2026", "archived": True}
    assert http.get(f"/v1/conversations?user={db}").json()["data"] == []
    assert [c["title"] for c in http.get(f"/v1/conversations?user={db}&archived=true").json()["data"]] == ["CA 2026"]
    assert http.get(f"/v1/conversations?user={db}&archived=true&q=avril").json()["data"][0]["id"] == cid
    assert http.patch(f"/v1/conversations/{cid}?user=someone-else", json={"title": "x"}).status_code == 404
    export = http.get(f"/v1/conversations/{cid}/export?user={db}")
    assert export.headers["content-type"].startswith("text/markdown") and "# CA 2026" in export.text
    monkeypatch.setattr(conversations, "llm_summary", lambda text, note=None: "- mars : 13 599 646,63 €")
    r = http.post(f"/v1/conversations/{cid}/compact?user={db}", json={"keep_turns": 1})
    assert r.json()["summary_messages"] == 6
    assert http.post(f"/v1/conversations/{cid}/compact?user={db}", json={"keep_turns": 1}).status_code == 409
    assert http.get(f"/v1/conversations/{cid}").json()["summary"] == "- mars : 13 599 646,63 €"


def test_with_keys_a_user_manages_only_their_own_conversations(db):
    cid = conversation(db, TURNS[:1])
    http = TestClient(create_app(FakeAgent(), api_keys=f"{db}:k1,{db}-other:k2"))
    other = {"Authorization": "Bearer k2"}
    assert http.patch(f"/v1/conversations/{cid}?user={db}", json={"archived": True}, headers=other).status_code == 404
    assert http.get(f"/v1/conversations/{cid}/export?user={db}", headers=other).status_code == 404
    r = http.patch(f"/v1/conversations/{cid}", json={"archived": True}, headers={"Authorization": "Bearer k1"})
    assert r.json()["archived"] is True


def test_the_agent_reads_the_summary_in_place_of_the_turns_it_covers(db, monkeypatch):
    cid = conversation(db, TURNS)
    memory.set_summary(cid, db, "- mars : 13 599 646,63 €", 4)
    monkeypatch.setattr("text2sql_calorvia.memory.save_turn", lambda *a: None)   # the new turn isn't stored
    agent = FakeAgent()
    TestClient(create_app(agent)).post("/v1/chat/completions", headers={"X-Conversation-Id": cid}, json={
        "user": db, "messages": history(4, "Et pour juin ?")})
    assert [m["content"] for m in agent.received][:2] == [conversations.SUMMARY_QUESTION,
                                                          conversations.SUMMARY_HEAD + "- mars : 13 599 646,63 €"]
    assert [m["content"] for m in agent.received][2:] == [m["content"] for m in history(4, "Et pour juin ?")[4:]]


# --- the chat page --------------------------------------------------------------------------------------------------
def test_the_chat_lists_conversations_and_reopens_one(monkeypatch):
    listed = [{"id": "c1", "title": "CA de mars", "updated_at": "2026-11-20T10:00:00", "messages": 2,
               "archived": False, "compacted": False}]
    stored = [{"role": "user", "content": "CA de mars ?", "steps": None, "created_at": "2026-11-20T10:00:00"},
              {"role": "assistant", "content": "**13 599 646,63 €**", "steps": [], "created_at": "2026-11-20T10:00:01"}]
    info = {"id": "c1", "user": "default", "title": "CA de mars", "archived": False, "summary": None,
            "summary_messages": 0, "compacted_at": None, "created_at": "2026-11-20T10:00:00",
            "updated_at": "2026-11-20T10:00:01"}
    monkeypatch.setattr(memory, "conversations", lambda *a, **k: listed)
    monkeypatch.setattr(memory, "conversation", lambda cid: stored if cid == "c1" else [])
    monkeypatch.setattr(memory, "conversation_info", lambda cid: info if cid == "c1" else None)
    monkeypatch.setattr(settings, "api_keys", "")
    page = AppTest.from_file(CHAT, default_timeout=60).run()
    assert not page.exception
    button = next(b for b in page.sidebar.button if b.label == "CA de mars")
    page = button.click().run()
    assert not page.exception
    assert [m.markdown[0].value for m in page.chat_message if m.name == "assistant"][-1] == "**13 599 646,63 €**"
    assert page.session_state.conversation_id == "c1"
    assert any(e.label.startswith("⚙️ CA de mars") for e in page.expander)
