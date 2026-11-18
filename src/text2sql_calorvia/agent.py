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
- **local tools** (step 15): `make_chart` draws a result as a PNG served by the endpoint, added under the answer by
  finish; `remember` / `forget` keep what the user asks to retain (memory.py), shown in the next prompts as data.
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

from text2sql_calorvia import access, charts, grounding, memory, ontology
from text2sql_calorvia.config import settings
from text2sql_calorvia.reconcile import KEY_TYPES, reconcile

PROMPT = Path(__file__).resolve().parents[2] / "prompts" / "agent.txt"
ONTOLOGY_PROMPT = PROMPT.with_name("agent_ontology.txt")   # the ontology's part, left out when use_ontology is off
INJECTED = {"question", "session_id", "max_rows", "access_token"}   # filled by the agent (query log, row budget), never by the model
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


CHART_TOOL = {"type": "function", "function": {
    "name": "make_chart",
    "description": ("Dessine un graphique (barres, courbe ou secteurs) à partir d'un résultat déjà exécuté (q1, q2...). "
                    "Le graphique est ajouté automatiquement à votre réponse. À utiliser quand l'utilisateur demande un "
                    "graphique, ou pour une série (par mois, par site) de plus de quelques valeurs."),
    "parameters": {"type": "object", "required": ["result", "kind", "x", "y", "title"], "properties": {
        "result": {"type": "string", "description": "identifiant du résultat (q1, q2...)"},
        "kind": {"type": "string", "enum": list(charts.KINDS)},
        "x": {"type": "string", "description": "colonne des étiquettes (mois, site...)"},
        "y": {"type": "array", "items": {"type": "string"}, "description": "colonne(s) de valeurs numériques"},
        "title": {"type": "string", "description": "titre, avec l'unité et la période"}}}}}

REMEMBER_TOOL = {"type": "function", "function": {
    "name": "remember",
    "description": ("Retient pour les conversations suivantes une préférence, une définition corrigée ou une requête "
                    "validée. Seulement quand l'utilisateur le demande explicitement (« retiens », « à l'avenir », "
                    "« toujours », « cette requête est la bonne »)."),
    "parameters": {"type": "object", "required": ["kind", "content"], "properties": {
        "kind": {"type": "string", "enum": list(memory.KINDS)},
        "content": {"type": "string", "description": "ce qu'il faut retenir, en une ou deux phrases (pour une requête "
                                                     "validée : la question et le SQL)"}}}}}

FORGET_TOOL = {"type": "function", "function": {
    "name": "forget",
    "description": "Oublie un élément retenu, quand l'utilisateur le demande. id : le numéro entre crochets.",
    "parameters": {"type": "object", "required": ["id"], "properties": {"id": {"type": "integer"}}}}}

LOCAL_TOOLS = {"reconcile", "make_chart", "remember", "forget"}


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
    charts: list[dict]           # {id, title} drawn for this answer (step 15)
    user: str                    # whose memory (step 15)
    conversation_id: str | None
    access_token: str | None     # the caller's role, signed by the endpoint (access.py); never shown to the model
    scope: dict | None           # what that role can read (access.scope_of); None in local mode
    answer: str


ROLE_RULE = ("# Votre périmètre\nVous ne voyez que les sources et les tables de ce message, selon le rôle de "
             "l'utilisateur. Si l'information demandée n'y figure pas, dites simplement que vous ne disposez pas de "
             "cette information : ne citez aucune base, table ou indicateur qui pourrait la contenir, et ne devinez "
             "pas.\n\n")


def scoped_prompt(text: str, scope: dict) -> str:
    """The prompt's sentences that name a source, rewritten for what the role can read."""
    dialects = {"erp": "T-SQL pour erp", "compta": "PostgreSQL pour compta", "paie": "PostgreSQL pour paie"}
    edits = {
        "dans le dialecte de la source : T-SQL pour erp, PostgreSQL pour compta et paie.":
            "dans le dialecte de la source : " + ", ".join(v for k, v in dialects.items() if k in scope) + "."
            if scope else "dans le dialecte de la source.",
        " (ventes facturées dans l'ERP, ventes comptabilisées au journal VEN)": "",
        "Ne retenez jamais un montant individuel de la paie ni une donnée personnelle.":
            "Ne retenez jamais une donnée personnelle.",
    }
    if not {"erp", "compta"} <= set(scope):
        edits[" (par exemple « le chiffre d'affaires » : facturé dans l'ERP ou comptabilisé ?)"] = ""
    if len(scope) < 2:
        edits[" Quand deux sources mesurent la même chose, un écart est une information à expliquer, pas une erreur à "
              "cacher."] = ""
    for old, new in edits.items():
        text = text.replace(old, new)
    lines = text.split("\n")
    if len(scope) < 2:
        lines = ["4. Ne recopiez jamais des lignes à la main." if line.startswith("4. Plusieurs bases") else line
                 for line in lines]
    if "paie" not in scope:
        lines = [line for line in lines if not line.startswith("- Paie :")]
    return "\n".join(lines)


def scoped_tools(tools: list[dict], scope: dict) -> list[dict]:
    """The tools a role can use, their descriptions naming no source it can't read."""
    dropped = set()
    if len(scope) < 2:
        dropped.add("reconcile")
    if not {"erp", "paie"} <= set(scope):
        dropped.add("get_sales_commission")
    kept = json.dumps([t for t in tools if t["function"]["name"] not in dropped], ensure_ascii=False)
    for old, new in (("(erp, compta ou paie)", "(voir list_sources)"), ("règle de confidentialité de la paie", "règles de confidentialité"),
                     ('ca_erp', 'montant_a'), ('ca_compta', 'montant_b')):
        kept = kept.replace(old, new)
    return json.loads(kept)


def system_prompt(sources: list[dict], use_ontology: bool = True, memories: str = "", scope: dict | None = None) -> str:
    """scope (access.scope_of): the role's tables. Without one, the prompt is the same as before roles existed."""
    index = ontology.table_index(scope) if use_ontology else ""
    section = (ONTOLOGY_PROMPT.read_text(encoding="utf-8").format(tables=index, metrics=ontology.glossary(scope))
               if index else "")
    if scope is not None:
        memories = ROLE_RULE + ("" if scope else "Votre rôle ne donne accès à aucune donnée chiffrée.\n\n") + memories
    text = PROMPT.read_text(encoding="utf-8").format(ontology=section, memory=memories,
        sources="\n".join(f"- {s['source']} ({s['engine']}, dialecte {s['dialect']}) : {s['description']}"
                          for s in sources),
        data_until=settings.data_until,
        max_sql_errors=settings.max_sql_errors, min_group_size=settings.min_group_size,
        rows_to_model=settings.rows_to_model)
    return scoped_prompt(text, scope) if scope is not None else text


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


def same_query(results: dict[str, dict], args: dict) -> str | None:
    """The id of an earlier result of exactly this query (same source, same text up to spacing and the row limit)."""
    def key(source, sql):
        sql = re.sub(r"\s+", " ", sql or "").strip().rstrip("; ")
        return source, re.sub(r" LIMIT \d+$", "", sql, flags=re.I)
    wanted = key(args.get("source"), args.get("sql"))
    return next((qid for qid, r in results.items() if key(r["source"], r["sql"]) == wanted), None)


def for_model(qid: str, output: dict) -> dict:
    """A query result as the model sees it: its id, the first rows, and where the rest is."""
    shown = output["rows"][:settings.rows_to_model]
    view = {"id": qid, "source": output["source"], "sql": output["sql"], "columns": output["columns"], "rows": shown,
            "row_count": output["row_count"], "truncated": output["truncated"]}
    if output.get("warnings"):
        view["warnings"] = output["warnings"]
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
# A unit after a number scales it: "13 599,6 k€" is 13 599 600 € (a remembered preference, step 15)
SCALE = re.compile(r"\s?(k€|K€|M€|Md€|millions?\b|milliers?\b|milliards?\b)")
SCALES = {"k€": 1e3, "K€": 1e3, "millier": 1e3, "milliers": 1e3, "M€": 1e6, "million": 1e6, "millions": 1e6,
          "Md€": 1e9, "milliard": 1e9, "milliards": 1e9}


def own_text(content: str | None) -> str:
    """The model's answer without what it copied from earlier answers (footer, query note): the code adds the real ones."""
    return HISTORY_NOTE.sub("", OWN_FOOTER.sub("", content or "")).strip()


def numbers(text: str, scaled: bool = False) -> list[tuple[str, float]]:
    """Numbers as written and their value: '13 599 646,63' (French), '13599646.63' (JSON), '1.234.567'.
    scaled: a unit after the number multiplies it ('13 599,6 k€' -> 13 599 600, '1,2 M€' -> 1 200 000)."""
    found = []
    for match in NUMBER.finditer(text):
        token = match.group()
        t = re.sub(r"[ \u00a0\u202f]", "", token)
        if re.fullmatch(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?", t):   # dots as thousands separators
            t = t.replace(".", "")
        value = float(t.replace(",", "."))
        if scaled and (unit := SCALE.match(text, match.end())):
            value *= SCALES[unit.group(1)]
        found.append((token, value))
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
    return [token for token, v in numbers(answer, scaled=True) if abs(v) >= minimum and not is_known(abs(v))]


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

    def __init__(self, mcp_target: Any = None, llm: Any = None, use_ontology: bool = True, use_memory: bool = True):
        self.mcp_target = mcp_target or settings.mcp_url
        self.use_memory = use_memory       # off: no remember/forget tools, no memories in the prompt (evaluation)
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
        sql_errors, messages, drawn = state.get("sql_errors", 0), [], list(state.get("charts", []))
        calls = state["messages"][-1].tool_calls
        for call in calls:
            name, args = call["name"], dict(call["args"])
            step = {"tool": name, "args": dict(args)}   # what the model asked, before the agent adds its own fields
            if name in LOCAL_TOOLS:
                try:
                    output = self._local_tool(name, args, state, results, drawn)
                    step["ok"] = True
                    if name in ("make_chart", "remember"):
                        step["result"] = output
                except KeyError as e:
                    output = {"error": f"Résultat inconnu : {e}. Résultats disponibles : {', '.join(results) or 'aucun'}."}
                    step["ok"] = False
                except ValueError as e:
                    output, step["ok"] = {"error": str(e)}, False
            elif name == "execute_sql" and (same := same_query(results, args)):
                # Seen in step 14 (X05): the model sent the same query 8 times in a row until the budget ran out
                output = {"ok": False, "errors": [
                    f"Requête identique à {same}, déjà exécutée pour cette question : le résultat ne changera pas. "
                    "Utilisez ce résultat, changez d'approche, ou répondez avec ce que vous avez."]}
                step.update(ok=False, stage="repeat", errors=output["errors"])
                sql_errors += 1
            else:
                if state.get("access_token"):
                    args["access_token"] = state["access_token"]
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
                                truncated=output["truncated"], warnings=output.get("warnings", []))
                    output = for_model(qid, output)
            steps.append(step)
            messages.append(ToolMessage(as_tool_text(output), tool_call_id=call["id"], name=name))
        return {"messages": messages, "results": results, "steps": steps, "sql_errors": sql_errors,
                "tool_calls": state.get("tool_calls", 0) + len(calls), "charts": drawn}

    def _local_tool(self, name: str, args: dict, state: AgentState, results: dict, drawn: list) -> dict:
        """The tools that run in the agent: they read the state (results by id) or the memory tables."""
        if name == "reconcile":
            return reconcile(results[args["left"]], results[args["right"]], args["left_key"], args["right_key"],
                             args.get("key_type", "exact"), args.get("compare"), args.get("tolerance", 0.01))
        if name == "make_chart":
            y = args.get("y") or []
            chart = charts.make_chart(results[args["result"]], args.get("kind", "bar"), args.get("x", ""),
                                      [y] if isinstance(y, str) else y, args.get("title", ""))
            drawn.append({"id": chart["id"], "title": chart["title"]})
            return {"chart": chart["id"], "note": "Graphique créé ; il sera ajouté sous votre réponse, ne mettez pas de lien."}
        if not self.use_memory:
            raise ValueError("Mémoire désactivée.")
        if name == "remember":
            return memory.remember(state["user"], args.get("kind", ""), args.get("content", ""), state.get("conversation_id"))
        if not memory.forget(state["user"], int(args.get("id", 0))):
            raise ValueError(f"Aucun élément retenu n°{args.get('id')} (voir la liste entre crochets).")
        return {"forgotten": int(args["id"])}

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

    @staticmethod
    def _evidence(state: AgentState) -> set[float]:
        """The numbers small figures may come from (D71): query results, reconciliations, what the client's messages
        hold; not the prompt or the table cards, which are full of small numbers."""
        known = set()
        for result in state.get("results", {}).values():
            known |= grounding.result_numbers(result)
        for i, message in enumerate(state["messages"]):
            if isinstance(message, ToolMessage) and message.name in {"reconcile", "get_sales_commission"}:
                known |= grounding.tool_numbers(str(message.content))
            elif 0 < i < state["history_len"]:
                known |= {abs(v) for _, v in numbers(str(message.content))}
        return known

    async def _check(self, state: AgentState) -> dict:
        answer = own_text(state["messages"][-1].content)
        # The conversation as the client sent it, and tool results; never the agent's own instructions (this check's
        # message quotes the very number it questions)
        corpus = "\n".join(str(m.content) for i, m in enumerate(state["messages"])
                           if i < state["history_len"] or isinstance(m, ToolMessage))
        missing = ungrounded(answer, corpus)
        if any(step["tool"] in {"execute_sql", "get_sales_commission"} and step.get("ok") for step in state.get("steps", [])):
            missing += grounding.unsupported(answer, self._evidence(state),
                                             (settings.min_group_size, settings.rows_to_model))
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
        if ran and self.use_ontology:
            text += ontology.other_readings(state.get("question", ""), text, state.get("scope"))   # D68, by code
        images = "".join(f"\n\n![{c['title']}]({charts.chart_url(c['id'])})" for c in state.get("charts", []))
        return {"answer": text + images + footer(steps, state["session_id"])}

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
    async def stream(self, messages: list[dict], session_id: str | None = None, user: str = "default",
                     conversation_id: str | None = None, access_token: str | None = None):
        """Run the graph on an OpenAI-style conversation; yields (node, state update) as each node finishes.
        `user` selects the memory; `conversation_id` records where a memory was learned."""
        question = next(m["content"] for m in reversed(messages) if m["role"] == "user")
        session_id = session_id or uuid.uuid4().hex
        scope = access.scope_of(access.read_token(access_token)) if access_token else None
        async with Client(self.mcp_target) as client:
            mcp_tools = (await client.list_tools()).tools
            tools = [tool_schema(t) for t in mcp_tools] + [RECONCILE_TOOL, CHART_TOOL]
            if scope is not None:
                tools = scoped_tools(tools, scope)
            remembered = ""
            if self.use_memory:
                tools += [REMEMBER_TOOL, FORGET_TOOL]
                remembered = memory.prompt_section(memory.memories(user))
            sources = structured(await client.call_tool(
                "list_sources", {"access_token": access_token} if access_token else {}))
            history = [SystemMessage(system_prompt(sources, self.use_ontology, remembered, scope))] + [
                HumanMessage(m["content"]) if m["role"] == "user" else AIMessage(previous_answer(m["content"]))
                for m in messages if m["role"] in ("user", "assistant")]
            state = {"messages": history, "question": question, "session_id": session_id,
                     "results": {}, "steps": [], "tool_calls": 0, "sql_errors": 0,
                     "history_len": len(history), "grounding_retry": False, "unverified": [],
                     "charts": [], "user": user, "conversation_id": conversation_id,
                     "access_token": access_token, "scope": scope}
            config = {"configurable": {"client": client, "tools": tools},
                      "recursion_limit": 4 * settings.max_tool_calls + 10}
            async for update in self.graph.astream(state, config, stream_mode="updates"):
                for node, change in update.items():
                    yield node, change

    async def ask(self, messages: list[dict], session_id: str | None = None, user: str = "default",
                  conversation_id: str | None = None, access_token: str | None = None) -> dict:
        """Run to the end; returns {"answer", "steps", "results"} (results: every row of q1, q2...)."""
        steps, answer, results = [], "", {}
        async for node, change in self.stream(messages, session_id, user, conversation_id, access_token):
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
        elif s["tool"] == "remember" and s.get("ok"):
            lines.append(f"Retenu pour la suite [{s['result']['id']}] ({s['result']['kind']}) : {s['result']['content']}")
        elif s["tool"] == "forget" and s.get("ok"):
            lines.append(f"Oublié : élément [{s['args'].get('id')}]")
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
