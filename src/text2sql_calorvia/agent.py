"""The text-to-SQL agent (step 13): a LangGraph graph over the MCP server and the certified ontology.

    agent ──tool calls──> tools ──> agent ... ──answer──> check ──> finish
      │                                                     └──ungrounded number (once)──> agent
      └──budget spent (tool calls or failed queries)──> wrap_up ──> finish

- **agent**: the LLM with the MCP server's tools and `reconcile`; the certified ontology is in its system prompt
  (where each notion lives, the certified metrics) and in every table card (D49).
- **tools**: calls the MCP server, the only component holding database connections. Each successful query is kept
  in the state under an id (q1, q2...) so `reconcile` can match two results in Python without the rows passing
  through the model; failed queries are counted.
- **check**: every number of the answer (≥ 1000) must be found, within 0.5 %, in a tool result of this question or in
  the conversation. Otherwise the model is sent back once ("run the query or drop the number"); if it still cannot,
  an answer with no query at all becomes "je ne sais pas", any other gets the unverified numbers listed under it.
  Found in testing: asked "et pour avril ?", the model copied its previous answer's layout, footer included, and
  invented a figure without calling a single tool.
- **wrap_up**: the retry bound. Past `max_tool_calls` calls or `max_sql_errors` failed queries, the pending calls are
  answered "not run" and the model must answer without tools, with what it has or "je ne sais pas".
- **finish**: appends every executed query (source, SQL as run, rows) to the answer. Transparency is done by code,
  not asked of the model: the CFO sees exactly what ran, also when the model forgets to say it.
"""
import json
import re
import uuid
from functools import cache
from pathlib import Path
from typing import Annotated, Any, TypedDict

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from mcp.client import Client

from text2sql_calorvia import ontology
from text2sql_calorvia.config import settings
from text2sql_calorvia.reconcile import KEY_TYPES, reconcile

PROMPT = Path(__file__).resolve().parents[2] / "prompts" / "agent.txt"
ONTOLOGY_PROMPT = PROMPT.with_name("agent_ontology.txt")   # the ontology's part, left out when use_ontology is off
INJECTED = {"question", "session_id", "max_rows"}   # filled by the agent (query log, row budget), never by the model
SQL_TOOLS = {"execute_sql", "validate_sql"}
ENGINE = {"erp": "SQL Server", "compta": "PostgreSQL", "paie": "PostgreSQL"}

RECONCILE_TOOL = {"type": "function", "function": {
    "name": "reconcile",
    "description": ("Rapproche deux résultats de requêtes déjà exécutées (souvent de deux bases différentes) sur une "
                    "clé normalisée, et compare des colonnes numériques. Renvoie le nombre de clés rapprochées, "
                    "celles présentes d'un seul côté, les écarts et les totaux."),
    "parameters": {"type": "object", "required": ["left", "right", "left_key", "right_key", "key_type"], "properties": {
        "left": {"type": "string", "description": "identifiant du premier résultat (q1, q2...)"},
        "right": {"type": "string", "description": "identifiant du second résultat"},
        "left_key": {"type": "string", "description": "colonne clé du premier résultat"},
        "right_key": {"type": "string", "description": "colonne clé du second résultat"},
        "key_type": {"type": "string", "enum": list(KEY_TYPES),
                     "description": "vat : numéro de TVA ; staff_number : matricule (M10405 = 10405) ; "
                                   "text : nom sans casse ni accents ; exact : tel quel"},
        "compare": {"type": "array", "items": {"type": "array", "items": {"type": "string"}},
                    "description": "paires [colonne du premier, colonne du second] à comparer, ex. [[\"ca_erp\", \"ca_compta\"]]"},
        "tolerance": {"type": "number", "description": "écart toléré (défaut 0.01)"}}}}}


class AgentState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    question: str
    session_id: str
    results: dict[str, dict]     # q1, q2... -> {source, sql, columns, rows, row_count, truncated}
    steps: list[dict]            # every tool call, for the footer and the progress stream
    tool_calls: int
    sql_errors: int
    history_len: int             # messages given by the client (system prompt included): the grounding corpus
    grounding_retry: bool
    unverified: list[str]
    answer: str


def system_prompt(sources: list[dict], use_ontology: bool = True) -> str:
    section = (ONTOLOGY_PROMPT.read_text(encoding="utf-8").format(tables=ontology.table_index(), metrics=ontology.glossary())
               if use_ontology else "")
    return PROMPT.read_text(encoding="utf-8").format(ontology=section,
        sources="\n".join(f"- {s['source']} ({s['engine']}, dialecte {s['dialect']}) : {s['description']}"
                          for s in sources),
        data_until=settings.data_until,
        max_sql_errors=settings.max_sql_errors, min_group_size=settings.min_group_size,
        rows_to_model=settings.rows_to_model)


def tool_schema(tool) -> dict:
    """An MCP tool as an OpenAI function, without the parameters the agent fills itself."""
    schema = json.loads(json.dumps(tool.input_schema))
    for name in INJECTED:
        schema.get("properties", {}).pop(name, None)
    schema["required"] = [r for r in schema.get("required", []) if r not in INJECTED]
    return {"type": "function", "function": {"name": tool.name, "description": tool.description or "",
                                             "parameters": schema}}


def structured(result) -> Any:
    """What a tool returned: its structured content (a list comes wrapped in {"result": ...}), else its text."""
    content = result.structured_content
    if content is not None:
        return content["result"] if set(content) == {"result"} else content
    return {"error": " ".join(getattr(c, "text", "") for c in result.content)}


def as_tool_text(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False, default=str)
    if len(text) > settings.tool_result_chars:
        text = text[:settings.tool_result_chars] + " ... [tronqué : affinez la requête ou agrégez]"
    return text


def for_model(qid: str, output: dict) -> dict:
    """A query result as the model sees it: its id, the first rows, and where the rest is."""
    shown = output["rows"][:settings.rows_to_model]
    view = {"id": qid, "source": output["source"], "sql": output["sql"], "columns": output["columns"], "rows": shown,
            "row_count": output["row_count"], "truncated": output["truncated"]}
    if len(shown) < output["row_count"]:
        view["note"] = (f"{len(shown)} premières lignes sur {output['row_count']} : les autres sont gardées sous "
                        f"{qid} pour reconcile. Pour un total ou un classement, agrégez en SQL (SUM, GROUP BY, TOP/LIMIT).")
    if output["truncated"]:
        view["note"] = (view.get("note", "") + f" Résultat tronqué à {output['row_count']} lignes : ne le traitez pas "
                        "comme complet ; agrégez ou filtrez davantage.").strip()
    return view


def fit(messages: list[AnyMessage]) -> list[AnyMessage]:
    """Keep the conversation under the context budget: shorten the oldest tool answers first (≈ 3 characters a
    token for French and JSON). The last round of tool answers is never shortened."""
    def size(ms):
        return sum(len(str(m.content)) for m in ms) // 3
    if size(messages) <= settings.context_tokens:
        return messages
    messages = list(messages)
    last_ai = max(i for i, m in enumerate(messages) if isinstance(m, AIMessage)) if any(
        isinstance(m, AIMessage) for m in messages) else len(messages)
    for i, m in enumerate(messages[:last_ai]):
        if isinstance(m, ToolMessage) and len(m.content) > 400:
            messages[i] = ToolMessage(m.content[:300] + " ... [raccourci : réponse ancienne, déjà utilisée]",
                                      tool_call_id=m.tool_call_id, name=m.name)
            if size(messages) <= settings.context_tokens:
                break
    return messages


NUMBER = re.compile(r"\d{1,3}(?:[ \u00a0\u202f.]\d{3})+(?:,\d+)?|\d+(?:[.,]\d+)?")
OWN_FOOTER = re.compile(r"\n*-{3,}\s*\n\*\*Comment ce résultat a été obtenu.*", re.S)
HISTORY_NOTE = re.compile(r"\s*\[Requêtes exécutées pour cette réponse :.*?\]", re.S)


def own_text(content: str | None) -> str:
    """The model's answer without what it copied from earlier answers (footer, query note): the code adds the real ones."""
    return HISTORY_NOTE.sub("", OWN_FOOTER.sub("", content or "")).strip()


def numbers(text: str) -> list[tuple[str, float]]:
    """Numbers as written and their value: '13 599 646,63' (French), '13599646.63' (JSON), '1.234.567'."""
    found = []
    for token in NUMBER.findall(text):
        t = re.sub(r"[ \u00a0\u202f]", "", token)
        if re.fullmatch(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?", t):   # dots as thousands separators
            t = t.replace(".", "")
        found.append((token, float(t.replace(",", "."))))
    return found


def ungrounded(answer: str, corpus: str, minimum: float = 1000, max_pairs_of: int = 400) -> list[str]:
    """Numbers of the answer (≥ minimum) found nowhere in the corpus, within 0.5 % (rounding, sign).

    The sum or difference of two known numbers counts as known ("1 499 823,54 € de moins que mars"), as long as the
    corpus has at most `max_pairs_of` distinct numbers (beyond, almost any value would be some pair's difference)."""
    known = sorted({abs(v) for _, v in numbers(corpus) if v})
    if len(known) <= max_pairs_of:
        known = sorted(set(known) | {round(a + b, 2) for a in known for b in known}
                       | {round(abs(a - b), 2) for a in known for b in known})

    def is_known(v):
        return any(abs(v - k) <= max(0.01, 0.005 * k) for k in known)
    return [token for token, v in numbers(answer) if abs(v) >= minimum and not is_known(abs(v))]


def previous_answer(text: str) -> str:
    """An earlier answer as the model sees it again: the queries as a short note, not the footer's layout,
    which the model otherwise copies (invented footer and figure included)."""
    head, _, tail = text.partition("\n---\n**Comment ce résultat a été obtenu**")
    if not tail:
        return text
    queries = [" ".join(q.split()) for q in re.findall(r"```sql\n(.*?)```", tail, re.S)]
    return head.strip() + ("\n\n[Requêtes exécutées pour cette réponse : " + " ; ".join(queries) + "]" if queries else "")


class Agent:
    """One graph, one MCP client per question. `mcp_target` is a URL, or the server object in tests."""

    def __init__(self, mcp_target: Any = None, llm: Any = None, use_ontology: bool = True):
        self.mcp_target = mcp_target or settings.mcp_url
        self.use_ontology = use_ontology   # off: no ontology in the prompt nor in the cards (step 14's comparison)
        self.llm = llm or ChatOpenAI(model=settings.llm_model, base_url=settings.llm_url, api_key="local",
                                     temperature=0, timeout=300)
        self.graph = self._build()

    # --- nodes ------------------------------------------------------------------------------------------------------
    async def _agent(self, state: AgentState, config) -> dict:
        tools = config["configurable"]["tools"]
        reply = await self.llm.bind_tools(tools).ainvoke(fit(state["messages"]))
        return {"messages": [reply]}

    async def _tools(self, state: AgentState, config) -> dict:
        client: Client = config["configurable"]["client"]
        results, steps = dict(state.get("results", {})), list(state.get("steps", []))
        sql_errors, messages = state.get("sql_errors", 0), []
        calls = state["messages"][-1].tool_calls
        for call in calls:
            name, args = call["name"], dict(call["args"])
            step = {"tool": name, "args": dict(args)}   # what the model asked, before the agent adds its own fields
            if name == "reconcile":
                try:
                    left, right = results[args["left"]], results[args["right"]]
                    output = reconcile(left, right, args["left_key"], args["right_key"], args.get("key_type", "exact"),
                                       args.get("compare"), args.get("tolerance", 0.01))
                    step["ok"] = True
                except KeyError as e:
                    output = {"error": f"Résultat inconnu : {e}. Résultats disponibles : {', '.join(results) or 'aucun'}."}
                    step["ok"] = False
                except ValueError as e:
                    output, step["ok"] = {"error": str(e)}, False
            else:
                if name in {"execute_sql", "get_sales_commission"}:
                    args.update(question=state["question"], session_id=state["session_id"])
                if name == "execute_sql":
                    args["max_rows"] = settings.agent_fetch_rows
                output = structured(await client.call_tool(name, args))
                ok = not (isinstance(output, dict) and (output.get("ok") is False or "error" in output))
                step["ok"] = ok
                if name in SQL_TOOLS and not ok:
                    sql_errors += 1
                    step["errors"] = output.get("errors") or [output.get("error")]
                    # execute returns the SQL it ran only when validation passed: then the database refused it
                    step["stage"] = "execution" if name == "execute_sql" and "sql" in output else "validation"
                if name == "get_table_card" and ok and not self.use_ontology:
                    output.pop("ontology_terms", None)
                if name == "execute_sql" and ok:
                    qid = f"q{len(results) + 1}"
                    results[qid] = {k: output.get(k) for k in ("source", "sql", "columns", "rows", "row_count", "truncated")}
                    step.update(id=qid, sql=output["sql"], source=output["source"], row_count=output["row_count"],
                                truncated=output["truncated"])
                    output = for_model(qid, output)
            steps.append(step)
            messages.append(ToolMessage(as_tool_text(output), tool_call_id=call["id"], name=name))
        return {"messages": messages, "results": results, "steps": steps, "sql_errors": sql_errors,
                "tool_calls": state.get("tool_calls", 0) + len(calls)}

    async def _wrap_up(self, state: AgentState, config) -> dict:
        pending = [ToolMessage("Non exécuté : limite d'appels atteinte.", tool_call_id=c["id"], name=c["name"])
                   for c in state["messages"][-1].tool_calls]
        why = (f"{state.get('sql_errors', 0)} requêtes refusées ou en erreur"
               if state.get("sql_errors", 0) >= settings.max_sql_errors else f"{state.get('tool_calls', 0)} appels d'outils")
        instruction = HumanMessage(
            f"Limite atteinte ({why}). N'appelez plus d'outil. Répondez maintenant avec les seuls résultats obtenus ; "
            "s'ils ne suffisent pas, dites que vous ne savez pas et expliquez ce qui a bloqué.")
        reply = await self.llm.ainvoke(fit(state["messages"] + pending + [instruction]))
        return {"messages": pending + [instruction, reply]}

    async def _check(self, state: AgentState) -> dict:
        answer = own_text(state["messages"][-1].content)
        # The conversation as the client sent it, and tool results; never the agent's own instructions (this check's
        # message quotes the very number it questions)
        corpus = "\n".join(str(m.content) for i, m in enumerate(state["messages"])
                           if i < state["history_len"] or isinstance(m, ToolMessage))
        missing = ungrounded(answer, corpus)
        if not missing:
            return {"unverified": []}
        if not state.get("grounding_retry"):
            return {"grounding_retry": True, "messages": [HumanMessage(
                f"Vérification automatique : {', '.join(missing)} ne figure(nt) dans aucun résultat d'outil de cette "
                "question. Chaque chiffre doit venir d'une requête exécutée pour cette question : exécutez-la, ou "
                "retirez ce chiffre de la réponse. Les réponses précédentes de la conversation ne sont pas des résultats. "
                "Rédigez ensuite la réponse comme si c'était la première : l'utilisateur ne voit pas cette vérification, "
                "ne la mentionnez pas.")]}
        return {"unverified": missing}

    def _after_check(self, state: AgentState) -> str:
        last = state["messages"][-1]
        return "agent" if isinstance(last, HumanMessage) else "finish"

    async def _finish(self, state: AgentState) -> dict:
        steps, missing = state.get("steps", []), state.get("unverified") or []
        text = own_text(state["messages"][-1].content)
        ran = any(s["tool"] in {"execute_sql", "get_sales_commission"} and s.get("ok") for s in steps)
        if missing and not ran:
            text = ("Je ne sais pas : je n'ai exécuté aucune requête qui donne ce chiffre, et je ne donne pas de chiffre "
                    "que je n'ai pas obtenu des données. Pouvez-vous reformuler la question ?")
        elif missing:
            text += f"\n\n⚠️ Nombre(s) non retrouvé(s) dans les résultats des requêtes, à vérifier : {', '.join(missing)}"
        return {"answer": text + footer(steps, state["session_id"])}

    # --- graph ------------------------------------------------------------------------------------------------------
    def _route(self, state: AgentState) -> str:
        last = state["messages"][-1]
        if not getattr(last, "tool_calls", None):
            return "check"
        if (state.get("tool_calls", 0) + len(last.tool_calls) > settings.max_tool_calls
                or state.get("sql_errors", 0) >= settings.max_sql_errors):
            return "wrap_up"
        return "tools"

    def _build(self):
        g = StateGraph(AgentState)
        g.add_node("agent", self._agent)
        g.add_node("tools", self._tools)
        g.add_node("wrap_up", self._wrap_up)
        g.add_node("check", self._check)
        g.add_node("finish", self._finish)
        g.add_edge(START, "agent")
        g.add_conditional_edges("agent", self._route, ["tools", "wrap_up", "check"])
        g.add_edge("tools", "agent")
        g.add_conditional_edges("check", self._after_check, ["agent", "finish"])
        g.add_edge("wrap_up", "finish")
        g.add_edge("finish", END)
        return g.compile()

    # --- running ----------------------------------------------------------------------------------------------------
    async def stream(self, messages: list[dict], session_id: str | None = None):
        """Run the graph on an OpenAI-style conversation; yields (node, state update) as each node finishes."""
        question = next(m["content"] for m in reversed(messages) if m["role"] == "user")
        session_id = session_id or uuid.uuid4().hex
        async with Client(self.mcp_target) as client:
            mcp_tools = (await client.list_tools()).tools
            tools = [tool_schema(t) for t in mcp_tools] + [RECONCILE_TOOL]
            sources = structured(await client.call_tool("list_sources", {}))
            history = [SystemMessage(system_prompt(sources, self.use_ontology))] + [
                HumanMessage(m["content"]) if m["role"] == "user" else AIMessage(previous_answer(m["content"]))
                for m in messages if m["role"] in ("user", "assistant")]
            state = {"messages": history, "question": question, "session_id": session_id,
                     "results": {}, "steps": [], "tool_calls": 0, "sql_errors": 0,
                     "history_len": len(history), "grounding_retry": False, "unverified": []}
            config = {"configurable": {"client": client, "tools": tools},
                      "recursion_limit": 4 * settings.max_tool_calls + 10}
            async for update in self.graph.astream(state, config, stream_mode="updates"):
                for node, change in update.items():
                    yield node, change

    async def ask(self, messages: list[dict], session_id: str | None = None) -> dict:
        """Run to the end; returns {"answer", "steps", "results"} (results: every row of q1, q2...)."""
        steps, answer, results = [], "", {}
        async for node, change in self.stream(messages, session_id):
            if node == "tools":
                steps, results = change["steps"], change["results"]
            if node == "finish":
                answer = change["answer"]
        return {"answer": answer, "steps": steps, "results": results}


def footer(steps: list[dict], session_id: str) -> str:
    """The executed queries and reconciliations under the answer, for the reader to check."""
    lines = []
    for s in steps:
        if s["tool"] == "execute_sql" and s.get("ok"):
            more = " (tronqué)" if s.get("truncated") else ""
            lines.append(f"**{s['id']}** · {s['source']} ({ENGINE[s['source']]}) · {s['row_count']} ligne(s){more}\n"
                         f"```sql\n{s['sql'].strip()}\n```")
        elif s["tool"] == "get_sales_commission" and s.get("ok"):
            lines.append(f"Commission (paie, outil get_sales_commission) : matricule {s['args'].get('staff_number')}, "
                         f"mois {s['args'].get('month')}")
        elif s["tool"] == "reconcile" and s.get("ok"):
            a = s["args"]
            lines.append(f"Rapprochement en Python : {a['left']}.{a['left_key']} ↔ {a['right']}.{a['right_key']} "
                         f"(clé {a.get('key_type', 'exact')})")
    if not lines:
        return ""
    failed = sum(1 for s in steps if s["tool"] in SQL_TOOLS and not s.get("ok"))
    note = f" · {failed} requête(s) refusée(s) ou en erreur, corrigée(s) en cours de route" if failed else ""
    return (f"\n\n---\n**Comment ce résultat a été obtenu** (journal `t2sql_query_log`, session `{session_id}`{note})\n\n"
            + "\n\n".join(lines))


@cache
def default_agent() -> Agent:
    return Agent()
