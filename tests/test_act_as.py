"""Step 47: an admin acts as a role. The endpoint decides who may (a client can't grant itself a role), the role is the
one the data layers enforce (the signed token, the documents' filter), and the simulated role keeps its own
conversations and memory, so nothing answered with the admin's access reaches it.
"""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from streamlit.testing.v1 import AppTest

from text2sql_calorvia import access, auth, documents, memory
from text2sql_calorvia.api import create_app
from text2sql_calorvia.config import settings
from test_api import BODY, KEYS, FakeAgent, bearer

CHAT = str(Path(__file__).resolve().parents[1] / "app" / "chat.py")
ACT = "X-Calorvia-Act-As"


@pytest.fixture(autouse=True)
def stored(monkeypatch):
    """No PostgreSQL: turns are recorded, every conversation id is new unless a test says otherwise."""
    turns = []
    monkeypatch.setattr(memory, "save_turn", lambda *a: turns.append(a))
    monkeypatch.setattr(memory, "conversation_owner", lambda _: None)
    return turns


def keyed(admins="alice"):
    agent = FakeAgent()
    return TestClient(create_app(agent, api_keys=KEYS, gateways="webui", admins=admins)), agent


def test_only_an_admin_or_local_mode_may_act_as_a_role():
    assert auth.may_act_as(auth.Caller("alice"), "alice", {"alice"})
    assert not auth.may_act_as(auth.Caller("bob"), "bob", {"alice"})
    assert not auth.may_act_as(auth.Caller("webui", True), "webui/bob", {"webui"})   # the gateway is not its users
    assert auth.may_act_as(auth.Caller(None), "default", set())
    assert auth.acting_user("alice", "finance") == "alice#as:finance" and auth.acting_user("alice", None) == "alice"


def test_an_admin_acts_as_the_role_with_its_own_conversations():
    http, agent = keyed()
    assert http.post("/v1/chat/completions", json=BODY, headers={**bearer("key-a"), ACT: "rh"}).status_code == 200
    assert access.read_token(agent.token) == "rh" and agent.who[0] == "alice#as:rh"


@pytest.mark.parametrize("key, role, status", [("key-b", "rh", 403), ("key-w", "direction", 403),
                                               ("key-a", "superuser", 400)])
def test_a_non_admin_or_an_unknown_role_is_refused(key, role, status):
    http, agent = keyed()
    assert http.post("/v1/chat/completions", json=BODY, headers={**bearer(key), ACT: role}).status_code == status
    assert not hasattr(agent, "token")                           # refused before the agent was called


def test_in_local_mode_acting_gives_the_role_a_token_it_would_not_have():
    agent = FakeAgent()
    http = TestClient(create_app(agent, api_keys="", admins=""))
    http.post("/v1/chat/completions", json=BODY)
    assert agent.token is None                                   # local mode: every table, as before
    http.post("/v1/chat/completions", json=BODY, headers={ACT: "commercial"})
    assert access.read_token(agent.token) == "commercial" and agent.who[0] == "default#as:commercial"


def test_acting_never_continues_a_conversation_held_with_full_access(monkeypatch):
    monkeypatch.setattr(memory, "conversation_owner", lambda _: "default")
    agent = FakeAgent()
    http = TestClient(create_app(agent, api_keys="", admins=""))
    http.post("/v1/chat/completions", json=BODY, headers={"X-Conversation-Id": "c1"})
    assert agent.who[1] == "c1"                                  # local mode reads its own conversation
    http.post("/v1/chat/completions", json=BODY, headers={"X-Conversation-Id": "c1", ACT: "rh"})
    assert agent.who[1] != "c1"                                  # the simulated role starts a new one


def test_the_documents_are_searched_with_the_role_acted(monkeypatch):
    roles = []
    monkeypatch.setattr(documents, "retrieve_context", lambda q, role: roles.append(role) or [])
    monkeypatch.setattr(documents, "write_answer", lambda q, c, role, on_text=None: {"answer": "Je ne sais pas.",
                                                                                     "extracts": [], "images": []})
    http, _ = keyed()
    http.post("/v1/chat/completions", json={**BODY, "model": "calorvia-docs"}, headers={**bearer("key-a"), ACT: "it"})
    assert roles == ["it"]


# --- the chat page ------------------------------------------------------------------------------------------------
@pytest.fixture
def page(monkeypatch):
    monkeypatch.setattr(memory, "conversations", lambda user, *a, **k: [])
    monkeypatch.setattr(settings, "user_roles", "alice:finance,bob:rh")

    def opened(key=None):
        app = AppTest.from_file(CHAT, default_timeout=60).run()
        if key:
            app.text_input[0].input(key)
            app.button[0].click().run()
        return app
    return opened


def selector(app):
    return [s for s in app.sidebar.selectbox if s.label == "Agir en tant que"]


def test_an_admin_picks_a_role_and_gets_a_new_conversation(page, monkeypatch):
    monkeypatch.setattr(settings, "api_keys", "alice:key-a,bob:key-b")
    monkeypatch.setattr(settings, "admin_users", "alice")
    app = page("key-a")
    assert not app.exception and selector(app)
    first = app.session_state.conversation_id
    app = selector(app)[0].select("rh").run()
    assert not app.exception and app.session_state.conversation_id != first
    assert any("« rh »" in w.value for w in app.sidebar.warning)


def test_a_user_who_is_not_an_admin_has_no_selector(page, monkeypatch):
    monkeypatch.setattr(settings, "api_keys", "alice:key-a,bob:key-b")
    monkeypatch.setattr(settings, "admin_users", "alice")
    app = page("key-b")
    assert not app.exception and app.chat_input and not selector(app)


def test_local_mode_has_the_selector(page, monkeypatch):
    monkeypatch.setattr(settings, "api_keys", "")
    app = page()
    assert not app.exception and selector(app) and selector(app)[0].value is None   # « — mon accès — » by default
    assert not app.sidebar.warning


# --- the configuration selector -------------------------------------------------------------------------------------
def test_the_default_configuration_is_marked_and_one_click_away(page, monkeypatch):
    from rag_calorvia.config import settings as rag_settings
    monkeypatch.setattr(settings, "api_keys", "")
    app = page()
    box = next(s for s in app.sidebar.selectbox if s.label == "Configuration")
    star = next(b for b in app.sidebar.button if b.label == "★")
    assert box.value == rag_settings.final_config and star.disabled          # the default, marked, nothing to reset
    other = next(p for p in sorted(Path("experiments").glob("*.toml")) if p != rag_settings.final_config)
    app = box.select(other).run()
    star = next(b for b in app.sidebar.button if b.label == "★")
    assert not app.exception and not star.disabled
    app = star.click().run()
    box = next(s for s in app.sidebar.selectbox if s.label == "Configuration")
    assert not app.exception and box.value == rag_settings.final_config
