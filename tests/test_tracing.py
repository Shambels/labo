"""Monitoring (step 32): what a trace holds, with the spans kept in memory instead of sent to Langfuse."""
import json
import uuid

import anyio
import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from test_agent import ScriptedLLM, call
from test_api import FakeAgent

from text2sql_calorvia import tracing
from text2sql_calorvia.agent import Agent
from text2sql_calorvia.api import create_app
from text2sql_calorvia.mcp_server import server


class TracedLLM(ScriptedLLM):
    """ChatOpenAI takes a config (Langfuse's handler, inside a trace); records it."""

    async def ainvoke(self, messages, config=None):
        self.config = config
        return await super().ainvoke(messages)


INPUT, OUTPUT, LEVEL = "langfuse.observation.input", "langfuse.observation.output", "langfuse.observation.level"


@pytest.fixture
def spans(monkeypatch):
    """A Langfuse client whose spans stay in memory; returns a function listing the finished spans."""
    from langfuse import Langfuse
    exporter = InMemorySpanExporter()
    # A new key each time: the SDK keeps one exporter per public key, and the last test's was shut down
    lf = Langfuse(public_key=f"pk-lf-test-{uuid.uuid4().hex}", secret_key="sk-lf-test", base_url="http://127.0.0.1:9",
                  span_exporter=exporter, environment="test")
    monkeypatch.setattr(tracing, "client", lambda: lf)
    monkeypatch.setattr("text2sql_calorvia.memory.save_turn", lambda *a: None)
    yield lambda: (lf.flush(), list(exporter.get_finished_spans()))[1]
    lf.shutdown()


def test_off_without_keys_every_call_is_a_no_op():
    with tracing.trace("calorvia-sql", question="Q?", user="u", session_id="c") as t:
        assert t.trace_id is None and not tracing.active()
        with tracing.observe("execute_sql", as_type="tool") as o:
            o.update(output="x")
            o.score("s", 1)
        assert tracing.llm_kwargs("agent") == {}


def test_nothing_is_traced_outside_a_trace(spans):
    """An evaluation script calls the agent directly: no orphan spans, no handler on the LLM calls."""
    with tracing.observe("execute_sql", as_type="tool"):
        assert tracing.llm_kwargs("agent") == {}
    assert spans() == []


def test_a_child_span_belongs_to_the_trace_and_carries_its_user_and_session(spans):
    with tracing.trace("calorvia-sql", question="Q?", user="alice", session_id="conv-1", tags=["calorvia-sql"]) as t:
        assert tracing.active() and "config" in tracing.llm_kwargs("agent")
        with tracing.observe("execute_sql", as_type="tool", input={"sql": "SELECT 1"}) as o:
            o.update(output={"rows": [[1]]})
    child, root = spans()
    assert child.parent.span_id == root.context.span_id and child.context.trace_id == root.context.trace_id
    assert format(root.context.trace_id, "032x") == t.trace_id
    for span in (child, root):
        assert span.attributes["user.id"] == "alice" and span.attributes["session.id"] == "conv-1"
    assert json.loads(child.attributes[INPUT]) == {"sql": "SELECT 1"}


def test_the_endpoint_traces_a_question_under_its_conversation(spans):
    http = TestClient(create_app(FakeAgent()))
    http.post("/v1/chat/completions", json={"messages": [{"role": "user", "content": "CA ?"}], "stream": True,
                                            "user": "bob"}, headers={"X-Conversation-Id": "conv-9"})
    (root,) = [s for s in spans() if s.parent is None]
    assert root.name == "calorvia-sql"
    assert root.attributes["user.id"] == "bob" and root.attributes["session.id"] == "conv-9"
    assert root.attributes[INPUT] == "CA ?" and root.attributes[OUTPUT] == "CA : 5 €"
    assert set(root.attributes["langfuse.trace.tags"]) == {"calorvia-agent", "stream", "api"}


def test_a_tool_span_holds_the_models_arguments_and_what_it_got_back(spans):
    """Never the fields the agent adds (question, session, row budget, role token): the model's call only."""
    llm = TracedLLM(AIMessage("", tool_calls=[call("reconcile", left="q1", right="q2", left_key="a",
                                                     right_key="b", key_type="exact")]), AIMessage("Rien."))
    with tracing.trace("calorvia-sql", question="Q?", user="u", session_id="c"):
        anyio.run(lambda: Agent(mcp_target=server, llm=llm, use_memory=False).ask(
            [{"role": "user", "content": "Q?"}], "s"))
    tool = next(s for s in spans() if s.name == "reconcile")
    assert json.loads(tool.attributes[INPUT]) == {"left": "q1", "right": "q2", "left_key": "a", "right_key": "b",
                                                 "key_type": "exact"}
    assert "Résultat inconnu" in json.loads(tool.attributes[OUTPUT])["error"] and tool.attributes[LEVEL] == "WARNING"
    check = next(s for s in spans() if s.name == "grounding_check")
    assert type(llm.config["callbacks"][0]).__name__ == "LangchainCallbackHandler" and llm.config["run_name"] == "agent"
    assert json.loads(check.attributes[OUTPUT]) == {"unverified": [], "retry": False}


def test_each_answer_is_scored(monkeypatch):
    scores = {}
    monkeypatch.setattr(tracing, "score", lambda name, value, comment=None: scores.update({name: value}))
    llm = ScriptedLLM(AIMessage("Le CA est de 999 999 €."))
    anyio.run(lambda: Agent(mcp_target=server, llm=llm, use_memory=False).ask([{"role": "user", "content": "Q?"}], "s"))
    assert scores == {"tool_calls": 0, "sql_errors": 0, "unverified_numbers": 1, "grounding_retry": 1,
                      "budget_spent": 0, "queries_run": 0}
