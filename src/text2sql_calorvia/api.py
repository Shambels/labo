"""The agent as an OpenAI-compatible endpoint: GET /v1/models, POST /v1/chat/completions (streaming or not).

    uv run python -m text2sql_calorvia.api     # http://127.0.0.1:9000/v1, model "calorvia-agent"

Step 15: every turn is saved (memory.py), under a conversation id: the X-Conversation-Id header if the client sends
one, else the id hidden in an earlier answer of the history (<!-- calorvia:conversation=… -->), else a new one. Charts
are served from /charts/<id>.png; GET /v1/conversations and /v1/conversations/<id> read conversations back.

Step 24 (auth.py): with API_KEYS set, /v1 needs a key and the user is the key's name. Without keys (local mode) the user
is the request's `user` field, or Open WebUI's X-OpenWebUI-User-Id header, else "default", and the server only listens
on loopback. Step 29: an image tag can't send a key, so a chart link is signed and expires; reading a conversation back
renews the links of the charts drawn in it.

Step 31: one endpoint for the databases, the documents, or both. The model chosen is the toggle: `calorvia-sql` (the
agent, also under its old name `calorvia-agent`), `calorvia-docs` (the RAG of phase A, unchanged), `calorvia-both` (the
agent with `search_documents`). A client may instead send `"sources": ["sql", "docs"]`. Images of the documents are
served from signed /images/ links, like charts.

Streaming sends the agent's steps as they happen (tool calls, queries, failures) inside a collapsed <details>
block, then the answer. Open WebUI renders <details> as a fold-out; when a client sends the conversation back, those
blocks are removed from earlier answers so the steps do not fill the model's context. The answers keep their
"how this was obtained" section: a follow-up question ("et pour avril ?") can reuse the queries shown there.
"""
import asyncio
import json
import re
import time
import uuid
from typing import Any

import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel

from text2sql_calorvia import access, auth, charts, documents, memory, tracing
from text2sql_calorvia.agent import Agent, default_agent
from text2sql_calorvia.config import settings

DETAILS = re.compile(r"<details>.*?</details>\s*", re.S)
MARKER = re.compile(r"\s*<!-- calorvia:conversation=([\w-]+) -->")
CHART_ID = re.compile(r"[0-9a-f]{16}")
SOURCES = {"sql", "docs"}
MODELS = {"calorvia-sql": {"sql"}, "calorvia-docs": {"docs"}, "calorvia-both": {"sql", "docs"}}
TRACE_NAME = {frozenset(v): k for k, v in MODELS.items()}   # step 32: a trace is named after what was searched
ALIASES = {settings.agent_model_name: "calorvia-sql"}   # the name of steps 13–29: clients configured with it still work


class Message(BaseModel):
    role: str
    content: str | list[dict[str, Any]] | None = None


class ChatRequest(BaseModel):
    model: str = settings.agent_model_name
    messages: list[Message]
    stream: bool = False
    user: str | None = None
    sources: list[str] | None = None   # step 31: overrides the model's sources


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
        out.append({"role": m.role, "content": MARKER.sub("", DETAILS.sub("", text)) if m.role == "assistant" else text})
    if not out or out[-1]["role"] != "user":
        raise HTTPException(400, "The last message must come from the user.")
    return out


def conversation_id_of(messages: list[Message], header: str | None) -> str | None:
    """The conversation this request continues: the header, or the marker hidden in an earlier answer."""
    if header:
        return header
    for m in messages:
        if m.role == "assistant" and (found := MARKER.search(text_of(m.content))):
            return found.group(1)
    return None


def sources_of(request: ChatRequest) -> set[str]:
    """What this request searches: its `sources` field, else its model."""
    if request.sources is not None:
        wanted = set(request.sources)
        if not wanted or not wanted <= SOURCES:
            raise HTTPException(400, f"sources: a non-empty list among {sorted(SOURCES)}.")
        return wanted
    model = ALIASES.get(request.model, request.model)
    if model not in MODELS:
        raise HTTPException(404, f"Unknown model {request.model!r}: {', '.join(MODELS)}.")
    return MODELS[model]


async def documents_only(question: str, role: str | None):
    """The RAG of phase A, as the same (node, change) events as the agent: the search, then the answer."""
    with tracing.observe("search_documents", as_type="retriever", input={"query": question}) as observed:
        context = await asyncio.to_thread(documents.retrieve_context, question, role)
        observed.update(output=[{"document": c["document"], "date": c.get("doc_date"), "text": c["text"]} for c in context])
    step = {"tool": "search_documents", "args": {"query": question}, "ok": True,
            "extracts": [f"D{n}" for n in range(1, len(context) + 1)]}
    yield "tools", {"steps": [step]}
    with tracing.observe("write_answer", as_type="generation", input=question,
                         model=documents.rag_config().get("generation", {}).get("model")) as observed:
        result = await asyncio.to_thread(documents.write_answer, question, context, role)
        observed.update(output=result["answer"])
    shown = [{"tool": "show_images", "args": {}, "ok": True, "images": result["images"]}] if result["images"] else []
    yield "finish", {"answer": result["answer"], "steps": [step, *shown]}


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
    if tool == "search_documents":
        return f"{mark} documents « {a.get('query')} » — {len(step.get('extracts', []))} extrait(s)"
    if tool == "make_chart":
        return f"{mark} graphique « {a.get('title')} » ({a.get('result')})"
    if tool in ("remember", "forget"):
        return f"{mark} {'retenu' if tool == 'remember' else 'oublié'} : {a.get('content') or a.get('id')}"
    if tool == "reconcile":
        return f"{mark} rapprochement {a.get('left')} ↔ {a.get('right')} (clé {a.get('key_type')})"
    return f"{mark} {tool} " + json.dumps(a, ensure_ascii=False)[:200]


def with_fresh_links(message: dict) -> dict:
    """A stored answer, its links valid again: only for the charts its own steps drew and the images they showed."""
    steps = message.get("steps") or []
    drawn = {s["result"]["chart"] for s in steps if s.get("tool") == "make_chart" and s.get("ok")}
    shown = [i for s in steps if s.get("tool") == "show_images" for i in s.get("images", [])]
    content = message["content"]
    if drawn:
        content = charts.refresh_links(content, drawn)
    if shown:
        content = documents.refresh_links(content, shown)
    return {**message, "content": content}


def create_app(agent: Agent | None = None, api_keys: str | None = None, gateways: str | None = None) -> FastAPI:
    app = FastAPI(title="Calorvia text-to-SQL agent")
    get_agent = (lambda: agent) if agent else default_agent
    keys = auth.parse_keys(settings.api_keys if api_keys is None else api_keys)
    trusted = auth.names(settings.trusted_gateways if gateways is None else gateways)

    def caller(authorization: str | None = Header(default=None)) -> auth.Caller:
        found = auth.authenticate(authorization, keys, trusted)
        if found is None:
            raise HTTPException(401, "Missing or invalid API key.", {"WWW-Authenticate": "Bearer"})
        return found

    def may_read(who: auth.Caller, user: str, conversation_id: str) -> bool:
        return who.name is None or memory.conversation_owner(conversation_id) in (None, user)

    @app.get("/v1/models", dependencies=[Depends(caller)])
    def models():
        return {"object": "list", "data": [{"id": name, "object": "model", "created": 0, "owned_by": "calorvia"}
                                           for name in MODELS]}

    @app.get("/charts/{name}")
    def chart(name: str, exp: str = "", sig: str = ""):
        chart_id = name.removesuffix(".png")
        path = settings.charts_dir / f"{chart_id}.png"
        # An id, never a path from the client; the same answer for a bad link and a missing chart
        if not CHART_ID.fullmatch(chart_id) or not access.chart_link_valid(chart_id, exp, sig) or not path.exists():
            raise HTTPException(404, "Unknown chart.")
        return FileResponse(path, media_type="image/png", headers={"Cache-Control": "private, no-store"})

    @app.get("/images/{name}")
    def image(name: str):
        """An image or scanned page of a document the answer cited (step 31); the same 404 for any bad link."""
        found = access.read_image_token(name.removesuffix(".jpg"))
        if found is None:
            raise HTTPException(404, "Unknown image.")
        try:
            data = documents.image_jpeg(*found)
        except (OSError, ValueError, PermissionError):
            raise HTTPException(404, "Unknown image.")
        return Response(data, media_type="image/jpeg", headers={"Cache-Control": "private, no-store"})

    @app.get("/v1/conversations")
    def list_conversations(user: str = "default", limit: int = 50, who: auth.Caller = Depends(caller),
                           x_openwebui_user_id: str | None = Header(default=None)):
        owner = auth.user_of(who, user, x_openwebui_user_id)
        return {"object": "list", "data": memory.conversations(owner, min(max(limit, 1), 500))}

    @app.get("/v1/conversations/{conversation_id}")
    def read_conversation(conversation_id: str, who: auth.Caller = Depends(caller),
                          x_openwebui_user_id: str | None = Header(default=None)):
        user = auth.user_of(who, None, x_openwebui_user_id)
        messages = memory.conversation(conversation_id) if may_read(who, user, conversation_id) else []
        if not messages:
            raise HTTPException(404, "Unknown conversation.")
        return {"id": conversation_id, "messages": [with_fresh_links(m) for m in messages]}

    @app.post("/v1/chat/completions")
    async def chat(request: ChatRequest, x_conversation_id: str | None = Header(default=None),
                   x_openwebui_user_id: str | None = Header(default=None), who: auth.Caller = Depends(caller)):
        messages = conversation(request.messages)
        wanted = sources_of(request)
        completion_id, created = f"chatcmpl-{uuid.uuid4().hex}", int(time.time())
        session_id = completion_id
        user = auth.user_of(who, request.user, x_openwebui_user_id)
        conversation_id = conversation_id_of(request.messages, x_conversation_id) or completion_id
        if not may_read(who, user, conversation_id):   # someone else's id: this becomes a new conversation
            conversation_id = completion_id
        marker = f"\n\n<!-- calorvia:conversation={conversation_id} -->"
        # With keys, the agent works under the user's role (Phase D); in local mode, as agent_ro
        extra = {"access_token": access.issue_token(access.role_of(user), user)} if who.name else {}
        role = access.role_of(user) if who.name else None   # the documents' filter: the same role as the databases
        if wanted == {"sql", "docs"}:
            extra["use_documents"] = True

        def run():
            """The (node, change) events of this request: the RAG alone, or the agent."""
            if wanted == {"docs"}:
                return documents_only(messages[-1]["content"], role)
            return get_agent().stream(messages, session_id, user, conversation_id, **extra)

        def traced():
            """The trace of this request (step 32): per user, per conversation, named after what was searched."""
            return tracing.trace(TRACE_NAME[frozenset(wanted)], question=messages[-1]["content"], user=user,
                                 session_id=conversation_id,
                                 tags=[request.model, "stream" if request.stream else "single",
                                       "openwebui" if x_openwebui_user_id else "api"],
                                 metadata={"completion_id": completion_id, "role": role, "turn": str(len(messages) // 2 + 1)})

        def save(answer: str, steps: list[dict]):
            try:
                memory.save_turn(conversation_id, user, messages[-1]["content"], answer, steps)
            except Exception as error:   # keeping the history must never cost the user the answer
                print(f"conversation not saved: {type(error).__name__}: {error}", flush=True)

        if not request.stream:
            with traced() as trace:
                if wanted == {"docs"}:
                    result = {"answer": "", "steps": []}
                    async for node, change in run():
                        if node == "finish":
                            result = change
                else:
                    result = await get_agent().ask(messages, session_id, user, conversation_id, **extra)
                trace.update(output=result["answer"])
            save(result["answer"], result["steps"])
            return {"id": completion_id, "object": "chat.completion", "created": created,
                    "model": request.model,
                    "choices": [{"index": 0, "finish_reason": "stop",
                                 "message": {"role": "assistant", "content": result["answer"] + marker}}],
                    "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}}

        def chunk(delta: dict, finish: str | None = None) -> str:
            body = {"id": completion_id, "object": "chat.completion.chunk", "created": created,
                    "model": request.model,
                    "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}
            return f"data: {json.dumps(body, ensure_ascii=False)}\n\n"

        async def events():
            yield chunk({"role": "assistant", "content": ""})
            opened, shown, steps = False, 0, []
            with traced() as trace:
                try:
                    async for node, change in run():
                        if node == "tools":
                            steps = change["steps"]
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
                            yield chunk({"content": change["answer"] + marker})
                            trace.update(output=change["answer"])
                            save(change["answer"], change.get("steps", steps))
                except Exception as error:   # the client gets a readable end, not a cut stream
                    trace.update(level="ERROR", status_message=f"{type(error).__name__}: {error}")
                    if opened:
                        yield chunk({"content": "\n</details>\n\n"})
                    yield chunk({"content": f"L'agent a rencontré une erreur : {type(error).__name__}: {error}"})
            yield chunk({}, "stop")
            yield "data: [DONE]\n\n"

        return StreamingResponse(events(), media_type="text/event-stream")

    return app


app = create_app()


def main():
    if not settings.api_keys and not auth.is_loopback(settings.agent_host):
        raise SystemExit("API_KEYS is required to listen beyond loopback (AGENT_HOST).")
    uvicorn.run(app, host=settings.agent_host, port=settings.agent_port)


if __name__ == "__main__":
    main()
