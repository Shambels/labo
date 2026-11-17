"""The agent as an OpenAI-compatible endpoint: GET /v1/models, POST /v1/chat/completions (streaming or not).

    uv run python -m text2sql_calorvia.api     # http://127.0.0.1:9000/v1, model "calorvia-agent"

Streaming sends the agent's steps as they happen (tool calls, queries, failures) inside a collapsed <details>
block, then the answer. Open WebUI renders <details> as a fold-out; when a client sends the conversation back, those
blocks are removed from earlier answers so the steps do not fill the model's context. The answers keep their
"how this was obtained" section: a follow-up question ("et pour avril ?") can reuse the queries shown there.
"""
import json
import re
import time
import uuid
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from text2sql_calorvia.agent import Agent, default_agent
from text2sql_calorvia.config import settings

DETAILS = re.compile(r"<details>.*?</details>\s*", re.S)


class Message(BaseModel):
    role: str
    content: str | list[dict[str, Any]] | None = None


class ChatRequest(BaseModel):
    model: str = settings.agent_model_name
    messages: list[Message]
    stream: bool = False
    user: str | None = None


def text_of(content) -> str:
    """OpenAI content is a string or a list of parts; keep the text parts."""
    if isinstance(content, list):
        return "".join(p.get("text", "") for p in content if p.get("type") == "text")
    return content or ""


def conversation(messages: list[Message]) -> list[dict]:
    """The client's history, without system messages (the agent has its own) and without earlier step blocks."""
    out = []
    for m in messages:
        if m.role not in ("user", "assistant"):
            continue
        text = text_of(m.content)
        out.append({"role": m.role, "content": DETAILS.sub("", text) if m.role == "assistant" else text})
    if not out or out[-1]["role"] != "user":
        raise HTTPException(400, "The last message must come from the user.")
    return out


def describe_step(step: dict) -> str:
    """One line per tool call, for the progress block."""
    a, tool = step["args"], step["tool"]
    mark = "✓" if step.get("ok") else "✗"
    if tool == "execute_sql":
        extra = f"{step['id']} : {step['row_count']} ligne(s)" if step.get("ok") else "; ".join(map(str, step.get("errors", [])))[:300]
        return f"{mark} `{a.get('source')}` requête — {extra}"
    if tool == "validate_sql":
        return f"{mark} `{a.get('source')}` vérification" + ("" if step.get("ok") else " — " + "; ".join(map(str, step.get("errors", [])))[:300])
    if tool == "get_table_card":
        return f"{mark} `{a.get('source')}` fiche {a.get('table')}"
    if tool == "find_values":
        return f"{mark} `{a.get('source')}` recherche « {a.get('value')} »"
    if tool == "reconcile":
        return f"{mark} rapprochement {a.get('left')} ↔ {a.get('right')} (clé {a.get('key_type')})"
    return f"{mark} {tool} " + json.dumps(a, ensure_ascii=False)[:200]


def create_app(agent: Agent | None = None) -> FastAPI:
    app = FastAPI(title="Calorvia text-to-SQL agent")
    get_agent = (lambda: agent) if agent else default_agent

    @app.get("/v1/models")
    def models():
        return {"object": "list", "data": [{"id": settings.agent_model_name, "object": "model",
                                            "created": 0, "owned_by": "calorvia"}]}

    @app.post("/v1/chat/completions")
    async def chat(request: ChatRequest):
        messages = conversation(request.messages)
        completion_id, created = f"chatcmpl-{uuid.uuid4().hex}", int(time.time())
        session_id = completion_id

        if not request.stream:
            result = await get_agent().ask(messages, session_id)
            return {"id": completion_id, "object": "chat.completion", "created": created,
                    "model": settings.agent_model_name,
                    "choices": [{"index": 0, "finish_reason": "stop",
                                 "message": {"role": "assistant", "content": result["answer"]}}],
                    "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}}

        def chunk(delta: dict, finish: str | None = None) -> str:
            body = {"id": completion_id, "object": "chat.completion.chunk", "created": created,
                    "model": settings.agent_model_name,
                    "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}
            return f"data: {json.dumps(body, ensure_ascii=False)}\n\n"

        async def events():
            yield chunk({"role": "assistant", "content": ""})
            opened, shown = False, 0
            try:
                async for node, change in get_agent().stream(messages, session_id):
                    if node == "tools":
                        if not opened:
                            yield chunk({"content": "<details>\n<summary>Étapes de l'agent</summary>\n\n"})
                            opened = True
                        for step in change["steps"][shown:]:
                            yield chunk({"content": f"- {describe_step(step)}\n"})
                        shown = len(change["steps"])
                    elif node == "finish":
                        if opened:
                            yield chunk({"content": "\n</details>\n\n"})
                            opened = False
                        yield chunk({"content": change["answer"]})
            except Exception as error:   # the client gets a readable end, not a cut stream
                if opened:
                    yield chunk({"content": "\n</details>\n\n"})
                yield chunk({"content": f"L'agent a rencontré une erreur : {type(error).__name__}: {error}"})
            yield chunk({}, "stop")
            yield "data: [DONE]\n\n"

        return StreamingResponse(events(), media_type="text/event-stream")

    return app


app = create_app()


def main():
    uvicorn.run(app, host=settings.agent_host, port=settings.agent_port)


if __name__ == "__main__":
    main()
