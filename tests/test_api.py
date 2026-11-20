"""The OpenAI-compatible endpoint (step 13), with a fake agent: format, streaming, history handling."""
import json
import re
import time

import pytest
from fastapi.testclient import TestClient
from openai import OpenAI

from text2sql_calorvia import access, charts
from text2sql_calorvia.api import create_app
from text2sql_calorvia.config import settings

STEP = {"tool": "execute_sql", "args": {"source": "erp", "sql": "SELECT 1"}, "ok": True, "id": "q1", "row_count": 1}


class FakeAgent:
    def __init__(self):
        self.received, self.who = None, None

    async def stream(self, messages, session_id=None, user="default", conversation_id=None, access_token=None):
        self.received, self.who, self.token = messages, (user, conversation_id), access_token
        yield "agent", {}
        yield "tools", {"steps": [STEP]}
        yield "finish", {"answer": "CA : 5 €"}

    async def ask(self, messages, session_id=None, user="default", conversation_id=None, access_token=None):
        self.received, self.who, self.token = messages, (user, conversation_id), access_token
        return {"answer": "CA : 5 €", "steps": [STEP]}


@pytest.fixture(autouse=True)
def saved(monkeypatch):
    """Turns are recorded here instead of the course PostgreSQL."""
    turns = []
    monkeypatch.setattr("text2sql_calorvia.memory.save_turn", lambda *a: turns.append(a))
    return turns


def client(agent=None):
    agent = agent or FakeAgent()
    return TestClient(create_app(agent)), agent


def test_models_lists_the_three_modes():
    http, _ = client()
    assert [m["id"] for m in http.get("/v1/models").json()["data"]] == ["calorvia-sql", "calorvia-docs", "calorvia-both"]


def test_a_completion_has_the_openai_format():
    http, _ = client()
    body = http.post("/v1/chat/completions", json={"model": "calorvia-agent",
                                                   "messages": [{"role": "user", "content": "CA ?"}]}).json()
    message = body["choices"][0]["message"]
    assert body["object"] == "chat.completion" and message["role"] == "assistant"
    assert message["content"].startswith("CA : 5 €\n\n<!-- calorvia:conversation=chatcmpl-")


def test_the_openai_sdk_reads_it():
    http, _ = client()
    sdk = OpenAI(base_url="http://testserver/v1", api_key="x", http_client=http)
    answer = sdk.chat.completions.create(model="calorvia-agent", messages=[{"role": "user", "content": "CA ?"}])
    assert answer.choices[0].message.content.startswith("CA : 5 €")
    chunks = sdk.chat.completions.create(model="calorvia-agent", stream=True,
                                         messages=[{"role": "user", "content": "CA ?"}])
    text = "".join(c.choices[0].delta.content or "" for c in chunks)
    assert text.startswith("<details>") and "✓ `erp` requête — q1 : 1 ligne(s)" in text and "CA : 5 €\n\n<!--" in text


def test_streaming_sends_steps_then_the_answer_then_done():
    http, _ = client()
    lines = [line for line in http.post("/v1/chat/completions", json={
        "messages": [{"role": "user", "content": "CA ?"}], "stream": True}).text.splitlines() if line]
    assert lines[-1] == "data: [DONE]"
    chunks = [json.loads(line[6:]) for line in lines[:-1]]
    assert chunks[0]["choices"][0]["delta"]["role"] == "assistant"
    assert chunks[-1]["choices"][0]["finish_reason"] == "stop"
    text = "".join(c["choices"][0]["delta"].get("content", "") for c in chunks)
    assert text.index("</details>") < text.index("CA : 5 €")


def test_history_loses_step_blocks_and_system_messages():
    http, agent = client()
    http.post("/v1/chat/completions", json={"messages": [
        {"role": "system", "content": "You are a pirate."},
        {"role": "user", "content": "CA de mars ?"},
        {"role": "assistant", "content": "<details>\n<summary>Étapes</summary>\n- ✓ q1\n</details>\n\nCA : 5 €"},
        {"role": "user", "content": [{"type": "text", "text": "et avril ?"}]}]})
    assert agent.received == [{"role": "user", "content": "CA de mars ?"},
                              {"role": "assistant", "content": "CA : 5 €"},
                              {"role": "user", "content": "et avril ?"}]


def test_the_last_message_must_be_a_question():
    http, _ = client()
    response = http.post("/v1/chat/completions", json={"messages": [{"role": "assistant", "content": "x"}]})
    assert response.status_code == 400


def test_an_agent_failure_ends_the_stream_cleanly():
    class Broken(FakeAgent):
        async def stream(self, messages, session_id=None, user="default", conversation_id=None):
            yield "tools", {"steps": [STEP]}
            raise RuntimeError("LLM down")
    http, _ = client(Broken())
    text = http.post("/v1/chat/completions", json={"messages": [{"role": "user", "content": "CA ?"}],
                                                   "stream": True}).text
    assert "</details>" in text and "RuntimeError: LLM down" in text and text.rstrip().endswith("[DONE]")


def test_a_conversation_is_found_again_from_the_marker_of_an_earlier_answer(saved):
    http, agent = client()
    first = http.post("/v1/chat/completions", json={"messages": [{"role": "user", "content": "CA de mars ?"}]}).json()
    content = first["choices"][0]["message"]["content"]
    conversation_id = first["id"]
    assert agent.who == ("default", conversation_id) and saved[0][:3] == (conversation_id, "default", "CA de mars ?")
    http.post("/v1/chat/completions", json={"user": "cfo", "messages": [
        {"role": "user", "content": "CA de mars ?"}, {"role": "assistant", "content": content},
        {"role": "user", "content": "et avril ?"}]})
    assert agent.who == ("cfo", conversation_id)                     # same conversation, the request's user
    assert agent.received[1]["content"] == "CA : 5 €"                # the marker is not shown to the model
    assert saved[1][:3] == (conversation_id, "cfo", "et avril ?")


def test_a_client_can_name_the_conversation_and_the_user_by_header(saved):
    http, agent = client()
    http.post("/v1/chat/completions", headers={"X-Conversation-Id": "conv-42", "X-OpenWebUI-User-Id": "u7"},
              json={"messages": [{"role": "user", "content": "CA ?"}], "stream": True})
    assert agent.who == ("u7", "conv-42") and saved[0][:2] == ("conv-42", "u7")


def test_a_failed_save_does_not_cost_the_answer(monkeypatch):
    def broken(*a):
        raise RuntimeError("database down")
    monkeypatch.setattr("text2sql_calorvia.memory.save_turn", broken)
    http, _ = client()
    body = http.post("/v1/chat/completions", json={"messages": [{"role": "user", "content": "CA ?"}]}).json()
    assert body["choices"][0]["message"]["content"].startswith("CA : 5 €")


CHART = "0123456789abcdef"


def link(chart_id=CHART, now=None):
    return charts.chart_url(chart_id, now).removeprefix(settings.agent_public_url)


@pytest.fixture
def chart_file(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "charts_dir", tmp_path)
    (tmp_path / f"{CHART}.png").write_bytes(b"\x89PNG")
    return tmp_path


def test_a_signed_chart_link_is_served_and_not_cached(chart_file):
    response = client()[0].get(link())
    assert response.status_code == 200 and response.headers["cache-control"] == "private, no-store"


def test_charts_are_served_by_id_only(chart_file):
    http, _ = client()
    assert http.get("/charts/..%2F..%2F.env").status_code == 404
    assert http.get(link("0123456789abcdeg")).status_code == 404


def test_a_chart_link_needs_its_signature(chart_file):
    http, _ = client()
    good = link()
    path, query = good.split("?")
    expires, signature = (part.split("=")[1] for part in query.split("&"))
    assert http.get(path).status_code == 404
    assert http.get(f"{path}?exp={expires}&sig={'0' * 64}").status_code == 404
    assert http.get(f"{path}?exp={int(expires) + 3600}&sig={signature}").status_code == 404   # a longer life
    assert http.get(f"{path}?exp={expires}&sig=é").status_code == 404
    assert http.get(f"{path}?exp=soon&sig={signature}").status_code == 404


def test_a_signature_is_valid_for_one_chart_only(chart_file):
    (chart_file / "fedcba9876543210.png").write_bytes(b"\x89PNG")
    query = link().split("?")[1]
    assert client()[0].get(f"/charts/fedcba9876543210.png?{query}").status_code == 404


def test_a_chart_link_expires(chart_file):
    old = time.time() - settings.chart_link_hours * 3600 - 1
    assert client()[0].get(link(now=old)).status_code == 404


def test_reading_a_conversation_renews_only_the_charts_it_drew(chart_file, monkeypatch):
    other = "fedcba9876543210"
    text = f"![a](http://x/charts/{CHART}.png?exp=1&sig=old) ![b](http://x/charts/{other}.png?exp=1&sig=old)"
    stored = [{"role": "user", "content": "q", "steps": None, "created_at": "t"},
              {"role": "assistant", "content": text, "created_at": "t",
               "steps": [{"tool": "make_chart", "ok": True, "result": {"chart": CHART}}]}]
    monkeypatch.setattr("text2sql_calorvia.memory.conversation", lambda _: stored)
    monkeypatch.setattr("text2sql_calorvia.memory.conversation_owner", lambda _: "default")
    content = client()[0].get("/v1/conversations/c1").json()["messages"][1]["content"]
    renewed = re.search(rf"/charts/{CHART}\.png\?exp=(\d+)&sig=(\w+)", content)
    assert access.chart_link_valid(CHART, renewed[1], renewed[2])
    assert f"/charts/{other}.png?exp=1&sig=old" in content


# Step 24 (D72): keys, and the user they prove
KEYS = "alice:key-a,bob:key-b,webui:key-w"
BODY = {"model": settings.agent_model_name, "messages": [{"role": "user", "content": "CA ?"}]}


def keyed(agent=None):
    agent = agent or FakeAgent()
    return TestClient(create_app(agent, api_keys=KEYS, gateways="webui")), agent


def bearer(key):
    return {"Authorization": f"Bearer {key}"}


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer nope"}, {"Authorization": "key-a"}])
def test_a_key_is_required_once_keys_are_set(headers):
    http, _ = keyed()
    assert http.get("/v1/models", headers=headers).status_code == 401
    assert http.post("/v1/chat/completions", json=BODY, headers=headers).status_code == 401
    assert http.get("/v1/conversations", headers=headers).status_code == 401


def test_the_user_is_the_key_not_what_the_request_says(monkeypatch):
    monkeypatch.setattr("text2sql_calorvia.memory.conversation_owner", lambda _: None)
    http, agent = keyed()
    assert http.post("/v1/chat/completions", json={**BODY, "user": "bob"}, headers={
        **bearer("key-a"), "X-OpenWebUI-User-Id": "bob"}).status_code == 200
    assert agent.who[0] == "alice"


def test_a_gateway_names_its_end_user_under_its_own_name(monkeypatch):
    monkeypatch.setattr("text2sql_calorvia.memory.conversation_owner", lambda _: None)
    http, agent = keyed()
    http.post("/v1/chat/completions", json=BODY, headers={**bearer("key-w"), "X-OpenWebUI-User-Id": "alice"})
    assert agent.who[0] == "webui/alice"


def test_someone_elses_conversation_is_neither_read_nor_continued(monkeypatch):
    monkeypatch.setattr("text2sql_calorvia.memory.conversation_owner", lambda _: "bob")
    monkeypatch.setattr("text2sql_calorvia.memory.conversation", lambda _: [{"role": "user", "content": "secret"}])
    http, agent = keyed()
    assert http.get("/v1/conversations/c1", headers=bearer("key-a")).status_code == 404
    assert http.get("/v1/conversations/c1", headers=bearer("key-b")).status_code == 200
    http.post("/v1/chat/completions", json=BODY, headers={**bearer("key-a"), "X-Conversation-Id": "c1"})
    assert agent.who[1] != "c1"


def test_the_list_of_conversations_is_the_callers(monkeypatch):
    seen = []
    monkeypatch.setattr("text2sql_calorvia.memory.conversations",
                        lambda user, limit, archived=False, search=None: seen.append(user) or [])
    http, _ = keyed()
    http.get("/v1/conversations?user=bob", headers=bearer("key-a"))
    assert seen == ["alice"]


def test_the_server_refuses_to_listen_openly_without_keys(monkeypatch):
    from text2sql_calorvia import api
    monkeypatch.setattr(api.settings, "api_keys", "")
    monkeypatch.setattr(api.settings, "agent_host", "0.0.0.0")
    with pytest.raises(SystemExit, match="API_KEYS"):
        api.main()


def test_a_malformed_key_list_is_refused():
    with pytest.raises(ValueError, match="name:key"):
        create_app(FakeAgent(), api_keys="just-a-key")


def test_the_agent_gets_the_role_of_the_key_and_none_in_local_mode(monkeypatch):
    from text2sql_calorvia import access
    monkeypatch.setattr("text2sql_calorvia.memory.conversation_owner", lambda _: None)
    monkeypatch.setattr(access.settings, "user_roles", "alice:finance")
    http, agent = keyed()
    http.post("/v1/chat/completions", json=BODY, headers=bearer("key-a"))
    assert access.read_token(agent.token) == "finance"
    http.post("/v1/chat/completions", json=BODY, headers=bearer("key-b"))
    assert access.read_token(agent.token) == access.DEFAULT_ROLE       # nobody gets data by default
    local, agent = client()
    local.post("/v1/chat/completions", json=BODY)
    assert agent.token is None
