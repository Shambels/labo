"""The OpenAI-compatible endpoint (step 13), with a fake agent: format, streaming, history handling."""
import json

from fastapi.testclient import TestClient
from openai import OpenAI

from text2sql_calorvia.api import create_app
from text2sql_calorvia.config import settings

STEP = {"tool": "execute_sql", "args": {"source": "erp", "sql": "SELECT 1"}, "ok": True, "id": "q1", "row_count": 1}


class FakeAgent:
    def __init__(self):
        self.received = None

    async def stream(self, messages, session_id=None):
        self.received = messages
        yield "agent", {}
        yield "tools", {"steps": [STEP]}
        yield "finish", {"answer": "CA : 5 €"}

    async def ask(self, messages, session_id=None):
        self.received = messages
        return {"answer": "CA : 5 €", "steps": [STEP]}


def client(agent=None):
    agent = agent or FakeAgent()
    return TestClient(create_app(agent)), agent


def test_models_lists_the_agent():
    http, _ = client()
    assert http.get("/v1/models").json()["data"][0]["id"] == settings.agent_model_name


def test_a_completion_has_the_openai_format():
    http, _ = client()
    body = http.post("/v1/chat/completions", json={"model": "calorvia-agent",
                                                   "messages": [{"role": "user", "content": "CA ?"}]}).json()
    assert body["object"] == "chat.completion" and body["choices"][0]["message"] == {"role": "assistant",
                                                                                    "content": "CA : 5 €"}


def test_the_openai_sdk_reads_it():
    http, _ = client()
    sdk = OpenAI(base_url="http://testserver/v1", api_key="x", http_client=http)
    answer = sdk.chat.completions.create(model="calorvia-agent", messages=[{"role": "user", "content": "CA ?"}])
    assert answer.choices[0].message.content == "CA : 5 €"
    chunks = sdk.chat.completions.create(model="calorvia-agent", stream=True,
                                         messages=[{"role": "user", "content": "CA ?"}])
    text = "".join(c.choices[0].delta.content or "" for c in chunks)
    assert text.startswith("<details>") and "✓ `erp` requête — q1 : 1 ligne(s)" in text and text.endswith("CA : 5 €")


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
        async def stream(self, messages, session_id=None):
            yield "tools", {"steps": [STEP]}
            raise RuntimeError("LLM down")
    http, _ = client(Broken())
    text = http.post("/v1/chat/completions", json={"messages": [{"role": "user", "content": "CA ?"}],
                                                   "stream": True}).text
    assert "</details>" in text and "RuntimeError: LLM down" in text and text.rstrip().endswith("[DONE]")
