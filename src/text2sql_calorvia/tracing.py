"""Monitoring with Langfuse (step 32, D81): one trace per question the endpoint answers.

    trace "calorvia-sql"  user, session = the conversation id, tags = model and client
    ├── generation "agent"             the messages the model saw, its reply and tool calls, tokens, latency
    ├── tool "execute_sql"             the model's arguments, what it got back (the rows it saw, or the errors)
    ├── generation "agent" ...
    ├── guardrail "grounding_check"    the numbers found in no tool result
    └── scores                         tool_calls, sql_errors, unverified_numbers, grounding_retry

Langfuse is OpenTelemetry underneath: a span opened here becomes the parent of whatever starts inside it, in this
task and in the tasks and threads it starts (asyncio copies the context). The LLM calls are traced by Langfuse's
LangChain handler, given to each call rather than to the graph: on the graph, every node's input would be the whole
state, the up to 2000 rows of each query included, copied into every node's span.

Off (every function a no-op) while LANGFUSE_PUBLIC_KEY or LANGFUSE_SECRET_KEY is empty: the tests, a fresh clone.
Spans are only made inside a trace: an evaluation script calling the agent directly is not traced.
What never goes in a trace: the role token (added to the tool arguments after the step is recorded) and API keys.
"""
import subprocess
from contextlib import contextmanager
from functools import cache
from typing import Any

from text2sql_calorvia.config import settings

TAG_CHARS = 200   # Langfuse's limit for user ids, session ids, tags and propagated metadata values


@cache
def client():
    """The Langfuse client, or None when tracing is off."""
    if not (settings.langfuse_public_key and settings.langfuse_secret_key):
        return None
    from langfuse import Langfuse
    try:
        from rag_calorvia.git_state import git_state
        release = git_state()[0][:12]   # which code answered: traces compare across commits, like experiment runs
    except (OSError, subprocess.CalledProcessError):   # no git, or not a repository (a deployed copy)
        release = None
    return Langfuse(public_key=settings.langfuse_public_key, secret_key=settings.langfuse_secret_key,
                    base_url=settings.langfuse_url, environment=settings.langfuse_environment, release=release)


def active() -> bool:
    """True inside a trace (tracing on, and a trace opened by `trace` in this context)."""
    if client() is None:
        return False
    # OpenTelemetry's context, not lf.get_current_trace_id(): that one logs an error each time no span is open
    from opentelemetry import trace as otel
    return otel.get_current_span().get_span_context().is_valid


class Observation:
    """What `trace` and `observe` yield: the span, or nothing when tracing is off. Callers never test which."""

    def __init__(self, span=None):
        self.span = span

    @property
    def trace_id(self) -> str | None:
        return self.span.trace_id if self.span is not None else None

    def update(self, **fields):
        if self.span is not None:
            self.span.update(**fields)

    def score(self, name: str, value: float, comment: str | None = None):
        """A score of the whole trace (Langfuse charts and filters them)."""
        if self.span is not None:
            self.span.score_trace(name=name, value=value, comment=comment)


def short(text: Any) -> str:
    return str(text)[:TAG_CHARS]


@contextmanager
def trace(name: str, *, question: str, user: str, session_id: str | None, tags: list[str] = (),
          metadata: dict[str, str] | None = None):
    """The trace of one question: everything traced inside it becomes its child. Yields an Observation."""
    lf = client()
    if lf is None:
        yield Observation()
        return
    from langfuse import propagate_attributes
    from opentelemetry import context as otel_context
    # A question is the root of its trace. FastAPI (0.16x) opens an OpenTelemetry span per request, recording once
    # Langfuse has set the global provider but never exported: as a parent, it would leave the trace hanging under
    # a span Langfuse never receives. So the trace starts from an empty context.
    token = otel_context.attach(otel_context.Context())
    try:
        with lf.start_as_current_observation(name=name, as_type="agent", input=question) as span, propagate_attributes(
                trace_name=name, user_id=short(user), session_id=short(session_id) if session_id else None,
                tags=[short(t) for t in tags],
                metadata={k: short(v) for k, v in (metadata or {}).items() if v is not None}):
            yield Observation(span)
    finally:
        otel_context.detach(token)


@contextmanager
def observe(name: str, as_type: str = "span", **fields):
    """A child of the current span (a tool call, a search, a check), only inside a trace. Yields an Observation."""
    if not active():
        yield Observation()
        return
    with client().start_as_current_observation(name=name, as_type=as_type, **fields) as span:
        yield Observation(span)


def score(name: str, value: float, comment: str | None = None):
    """A score of the current trace, from anywhere inside it (a graph node)."""
    if active():
        client().score_current_trace(name=name, value=value, comment=comment)


def llm_kwargs(run_name: str) -> dict:
    """Keyword arguments for one LangChain LLM call: Langfuse's handler when inside a trace, else nothing.
    Nothing rather than {"callbacks": []}: an explicit list replaces the callbacks LangGraph passes down."""
    if not active():
        return {}
    from langfuse.langchain import CallbackHandler
    # The handler finds its client by public key: the key of the client in use (the SDK keeps it in _resources)
    key = getattr(getattr(client(), "_resources", None), "public_key", settings.langfuse_public_key)
    return {"config": {"callbacks": [CallbackHandler(public_key=key)], "run_name": run_name}}
