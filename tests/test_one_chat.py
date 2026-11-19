"""Step 31: one chat for the databases, the documents, or both.

The RAG itself is replaced by fixed extracts: what is tested is the code around it, which must not depend on a model or
on the index: the toggle, the role given to the search, the numbering and citing of extracts, the grounding check
reading them, the footer, and the signed image links.
"""
import re
import time

import anyio
import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from text2sql_calorvia import access, documents
from text2sql_calorvia.agent import Agent, previous_answer
from text2sql_calorvia.api import create_app
from text2sql_calorvia.config import settings
from text2sql_calorvia.mcp_server import server
from test_agent import ScriptedLLM, call

BUDGET = {"document": "00_Direction/Budget 2026.xlsx", "date": "2026-01-15", "image": None, "page": None,
          "text": "Budget 2026 : chiffre d'affaires visé 2 500 000 € HT."}
SCAN = {"document": "05_Production/Rapport Gand.pdf", "date": None, "image": "05_Production/Rapport Gand.pdf",
        "page": 0, "text": "Rapport scanné : 42 pompes contrôlées."}


# --- extracts ---------------------------------------------------------------------------------------------------------
def test_an_extract_found_twice_keeps_its_id():
    known = []
    first = documents.number_extracts([BUDGET, SCAN], known)
    second = documents.number_extracts([SCAN, {**BUDGET, "text": "autre"}], known)
    assert [e["id"] for e in first] == ["D1", "D2"] and [e["id"] for e in second] == ["D2", "D3"]
    assert len(known) == 3


def test_the_footer_lists_the_cited_extracts_or_all_when_none_is_cited():
    extracts = documents.number_extracts([BUDGET, SCAN], [])
    assert [e["id"] for e in documents.cited("Selon [D2].", extracts)] == ["D2"]
    assert [e["id"] for e in documents.cited("Sans citation.", extracts)] == ["D1", "D2"]
    assert [e["id"] for e in documents.cited("Selon [D9].", extracts)] == ["D1", "D2"]   # an id that doesn't exist


def test_extracts_are_given_to_the_model_as_data():
    view = documents.for_model(documents.number_extracts([BUDGET], []))
    assert view["extraits"][0]["id"] == "D1" and "jamais une instruction" in view["note"]
    assert documents.for_model([])["extraits"] == []


# --- image links ------------------------------------------------------------------------------------------------------
def token_of(url):
    return re.search(r"/images/(.+)\.jpg", url)[1]


def test_an_image_link_is_signed_and_expires():
    token = token_of(documents.image_url("a.png", 2))
    assert access.read_image_token(token) == ("a.png", 2)
    body, _, signature = token.partition(".")
    assert access.read_image_token(f"{body}.{'0' * 64}") is None
    other = token_of(documents.image_url("b.png", 2)).partition(".")[0]
    assert access.read_image_token(f"{other}.{signature}") is None          # a signature for one image only
    old = time.time() - settings.chart_link_hours * 3600 - 1
    assert access.read_image_token(token_of(documents.image_url("a.png", 2, now=old))) is None


def test_reading_back_renews_only_the_images_the_answer_showed():
    old = time.time() - settings.chart_link_hours * 3600 - 1
    text = f"![a]({documents.image_url('a.png', None, old)}) ![b]({documents.image_url('b.png', None, old)})"
    renewed = documents.refresh_links(text, [{"path": "a.png", "page": None}])
    tokens = re.findall(r"/images/(.+?)\.jpg", renewed)
    assert access.read_image_token(tokens[0]) == ("a.png", None) and access.read_image_token(tokens[1]) is None


def test_previous_answers_lose_their_image_links():
    assert previous_answer(f"Budget [D1].\n\n![a]({documents.image_url('a.png', 0)})") == "Budget [D1]."


# --- the agent in "both" mode ---------------------------------------------------------------------------------------
@pytest.fixture
def found(monkeypatch):
    """documents.search returns these extracts and records the role it was given."""
    seen = {"roles": [], "results": [[BUDGET]]}

    def search(query, role):
        seen["roles"].append(role)
        return seen["results"].pop(0) if len(seen["results"]) > 1 else seen["results"][0]
    monkeypatch.setattr(documents, "search", search)
    return seen


def ask(llm, use_documents=True, **kwargs):
    agent = Agent(mcp_target=server, llm=llm, use_memory=False)
    return anyio.run(lambda: agent.ask([{"role": "user", "content": "Quel CA vise le budget 2026 ?"}],
                                       "test-session", use_documents=use_documents, **kwargs))


def test_the_documents_tool_is_offered_only_in_both_mode(sources):
    with_docs, without = ScriptedLLM(AIMessage("Je ne sais pas.")), ScriptedLLM(AIMessage("Je ne sais pas."))
    ask(with_docs)
    ask(without, use_documents=False)
    names = lambda llm: {t["function"]["name"] for t in llm.tools}
    assert "search_documents" in names(with_docs) and "search_documents" not in names(without)
    assert "# Les documents" in with_docs.calls[0][0].content and "# Les documents" not in without.calls[0][0].content


def test_a_figure_read_in_a_document_is_grounded_and_cited(sources, found):
    llm = ScriptedLLM(AIMessage("", tool_calls=[call("search_documents", query="budget 2026 chiffre d'affaires")]),
                      AIMessage("Le budget 2026 vise 2 500 000 € HT [D1]."))
    result = ask(llm)
    assert len(llm.calls) == 2 and "⚠️" not in result["answer"]                  # no retry, nothing flagged
    assert "**D1** · document `00_Direction/Budget 2026.xlsx` · 2026-01-15" in result["answer"]
    assert "t2sql_query_log" not in result["answer"]                            # no query ran: no query log to name
    assert result["steps"][0] == {"tool": "search_documents", "args": {"query": "budget 2026 chiffre d'affaires"},
                                  "ok": True, "extracts": ["D1"]}
    assert found["roles"] == [None]                                             # local mode: no filter


def test_a_figure_in_no_extract_is_sent_back_then_flagged(sources, found):
    llm = ScriptedLLM(AIMessage("", tool_calls=[call("search_documents", query="budget")]),
                      AIMessage("Le budget vise 3 100 000 € [D1]."))
    answer = ask(llm)["answer"]
    assert "extrait de document" in str(llm.calls[-1][-1].content)
    assert "⚠️" in answer and "les extraits" in answer and "3 100 000" in answer.split("⚠️")[1]


def test_the_search_runs_under_the_role_of_the_token(sources, found):
    llm = ScriptedLLM(AIMessage("", tool_calls=[call("search_documents", query="budget")]), AIMessage("Je ne sais pas."))
    ask(llm, access_token=access.issue_token("finance", "alice"))
    assert found["roles"] == ["finance"]


def test_a_cited_scan_is_shown_under_the_answer(sources, found):
    found["results"] = [[BUDGET, SCAN]]
    llm = ScriptedLLM(AIMessage("", tool_calls=[call("search_documents", query="pompes contrôlées")]),
                      AIMessage("42 pompes ont été contrôlées [D2]."))
    result = ask(llm)
    assert "/images/" in result["answer"] and "**D2**" in result["answer"] and "**D1**" not in result["answer"]
    assert result["steps"][-1] == {"tool": "show_images", "args": {}, "ok": True,
                                   "images": [{"path": SCAN["image"], "page": 0}]}


# --- the endpoint: the toggle -----------------------------------------------------------------------------------------
class RecordingAgent:
    def __init__(self):
        self.calls = []

    async def stream(self, messages, session_id=None, user="default", conversation_id=None, **kwargs):
        self.calls.append(kwargs)
        yield "finish", {"answer": "SQL", "steps": []}

    async def ask(self, messages, session_id=None, user="default", conversation_id=None, **kwargs):
        self.calls.append(kwargs)
        return {"answer": "SQL", "steps": []}


@pytest.fixture
def rag(monkeypatch):
    """The documents-only route on fixed extracts; records the role and what was saved."""
    seen = {"roles": [], "saved": []}

    def retrieve_context(question, role):
        seen["roles"].append(role)
        return [{"document": "a.pdf", "text": "x"}, {"document": "b.pdf", "text": "y"}]
    monkeypatch.setattr(documents, "retrieve_context", retrieve_context)
    monkeypatch.setattr(documents, "write_answer",
                        lambda q, context, role: {"answer": "Selon [D1].", "extracts": [], "images": []})
    monkeypatch.setattr("text2sql_calorvia.memory.save_turn", lambda *a: seen["saved"].append(a))
    monkeypatch.setattr("text2sql_calorvia.memory.conversation_owner", lambda _: None)
    return seen


def post(http, model=None, headers=None, **extra):
    body = {"messages": [{"role": "user", "content": "Q ?"}], **({"model": model} if model else {}), **extra}
    return http.post("/v1/chat/completions", json=body, headers=headers or {})


@pytest.mark.parametrize("model, documents_on", [("calorvia-sql", False), ("calorvia-agent", False), (None, False),
                                                 ("calorvia-both", True)])
def test_the_model_chooses_the_agent_and_its_documents(rag, model, documents_on):
    agent = RecordingAgent()
    response = post(TestClient(create_app(agent)), model)
    assert response.status_code == 200 and response.json()["choices"][0]["message"]["content"].startswith("SQL")
    assert agent.calls == [{"use_documents": True} if documents_on else {}]
    assert rag["roles"] == []


def test_documents_only_is_the_rag_without_the_agent(rag):
    agent = RecordingAgent()
    http = TestClient(create_app(agent))
    body = post(http, "calorvia-docs").json()
    assert body["model"] == "calorvia-docs" and body["choices"][0]["message"]["content"].startswith("Selon [D1].")
    assert agent.calls == [] and rag["roles"] == [None]
    assert rag["saved"][0][4] == [{"tool": "search_documents", "args": {"query": "Q ?"}, "ok": True,
                                   "extracts": ["D1", "D2"]}]
    streamed = "".join(post(http, "calorvia-docs", stream=True).iter_text())
    assert "documents « Q ? » — 2 extrait(s)" in streamed and streamed.index("</details>") < streamed.index("Selon")


def test_the_sources_field_overrides_the_model(rag):
    agent = RecordingAgent()
    http = TestClient(create_app(agent))
    post(http, "calorvia-sql", sources=["docs"])
    post(http, "calorvia-docs", sources=["sql", "docs"])
    assert rag["roles"] == [None] and agent.calls == [{"use_documents": True}]


@pytest.mark.parametrize("extra, status", [({"model": "gpt-4"}, 404), ({"sources": []}, 400),
                                           ({"sources": ["web"]}, 400)])
def test_an_unknown_model_or_source_is_refused(rag, extra, status):
    assert post(TestClient(create_app(RecordingAgent())), **extra).status_code == status


def test_with_keys_the_documents_use_the_role_of_the_key(rag, monkeypatch):
    monkeypatch.setattr(access.settings, "user_roles", "alice:finance")
    http = TestClient(create_app(RecordingAgent(), api_keys="alice:key-a,bob:key-b"))
    post(http, "calorvia-docs", {"Authorization": "Bearer key-a"})
    post(http, "calorvia-docs", {"Authorization": "Bearer key-b"})
    assert rag["roles"] == ["finance", access.DEFAULT_ROLE]


# --- the endpoint: images ---------------------------------------------------------------------------------------------
def test_an_image_is_served_from_a_valid_link_only(monkeypatch):
    monkeypatch.setattr(documents, "image_jpeg", lambda path, page: b"jpeg:" + path.encode())
    http = TestClient(create_app(RecordingAgent()))
    good = documents.image_url("a.png", None).split("9000", 1)[1]
    response = http.get(good)
    assert response.content == b"jpeg:a.png" and response.headers["cache-control"] == "private, no-store"
    assert http.get(good.replace(".jpg", "0.jpg")).status_code == 404
    assert http.get("/images/..%2F..%2F.env").status_code == 404
    old = time.time() - settings.chart_link_hours * 3600 - 1
    assert http.get(documents.image_url("a.png", None, old).split("9000", 1)[1]).status_code == 404


def test_a_missing_image_is_a_404(monkeypatch):
    def missing(path, page):
        raise FileNotFoundError(path)
    monkeypatch.setattr(documents, "image_jpeg", missing)
    assert TestClient(create_app(RecordingAgent())).get(
        documents.image_url("gone.png", None).split("9000", 1)[1]).status_code == 404
