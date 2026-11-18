"""The agent's graph (step 13) with a scripted LLM: the control flow is code and is tested as code.

The real MCP server runs in memory (as in test_mcp); only the model is replaced, by a script of replies. What is
tested is what must not depend on the model: the footer of executed queries, the bound on failed queries and tool
calls, reconcile reading results from the state, the grounding check.
"""
import anyio
import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from text2sql_calorvia import agent as agent_module, grounding
from text2sql_calorvia.agent import Agent, numbers, previous_answer, tool_schema, ungrounded
from text2sql_calorvia.config import settings
from text2sql_calorvia.mcp_server import server

MARCH = ("SELECT SUM(CASE WHEN FAC_TYPE = 'A' THEN -FAC_MT_HT ELSE FAC_MT_HT END) AS ca FROM VTE_FACT "
         "WHERE FAC_DT >= '2026-03-01' AND FAC_DT < '2026-04-01'")


class ScriptedLLM:
    """Replies in order; a reply may be a function of the messages (to read a tool result)."""

    def __init__(self, *replies):
        self.replies, self.calls = list(replies), []

    def bind_tools(self, tools):
        self.tools = tools
        return self

    async def ainvoke(self, messages):
        self.calls.append(list(messages))
        reply = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        reply = reply(messages) if callable(reply) else reply
        return reply.model_copy(update={"id": None})   # a new message each time: add_messages replaces by id


def call(name, n=1, **args):
    return {"name": name, "args": args, "id": f"call_{name}_{n}", "type": "tool_call"}


def run(llm, question="Quel est le CA de mars 2026 ?", history=()):
    agent = Agent(mcp_target=server, llm=llm)
    messages = [*history, {"role": "user", "content": question}]
    return anyio.run(lambda: agent.ask(messages, "test-session"))


def last_tool_result(messages):
    return next(m for m in reversed(messages) if isinstance(m, ToolMessage)).content


# --- without databases ----------------------------------------------------------------------------------------------
def test_numbers_are_read_in_french_and_json_formats():
    assert [v for _, v in numbers("13 599 646,63 € ; 13599646.63 ; 1.234.567 ; 12,5 %")] == [
        13599646.63, 13599646.63, 1234567.0, 12.5]


def test_ungrounded_numbers_are_the_ones_found_in_no_result():
    corpus = '{"rows": [[13599646.63]]} {"rows": [[12099823.09]]}'
    answer = "Avril : 12 099 823 € (−1 499 823,54 € sur mars), soit −11 % ; en 2026. Inventé : 13 999 646,63 €."
    assert ungrounded(answer, corpus + " 2026") == ["13 999 646,63"]


def test_a_count_needs_a_query_result():
    known = grounding.result_numbers({"rows": [["Gand", 190], ["Namur", 126]], "row_count": 2})
    assert grounding.unsupported("**316 personnes** : 190 à Gand, 126 à Namur, sur 2 sites.", known) == []
    assert grounding.unsupported("219 clients sur 2 sites", known) == ["219 clients"]
    assert grounding.unsupported("219 clients", {203.0}) == ["219 clients"]
    assert grounding.unsupported("au moins 5 personnes", {203.0}, allowed=[5]) == []


def test_only_figures_that_say_what_they_are_are_checked():
    assert grounding.unsupported("En 2026, le 12 mars, comptes 60 à 64, classe 7, `LIMIT 50 lignes`.", {1.0}) == []
    assert grounding.unsupported("1 facture", {3.0}) == []
    assert grounding.unsupported("3 860 factures", {3860.0}) == []    # from 1 000 up: the other check


def test_a_percentage_is_found_or_computed_from_two_results():
    assert grounding.unsupported("marge de 9,4 %", {1278366.78, 13599646.63}) == []
    assert grounding.unsupported("taux de 0,1 %", {0.1}) == []
    assert grounding.unsupported("baisse de 11 %", {13599646.63, 12099823.09}) == []
    assert grounding.unsupported("marge de 25,0 %", {1278366.78, 13599646.63}) == ["25,0 %"]


def test_days_between_two_dates_of_a_result_are_known():
    known = grounding.result_numbers({"rows": [["2026-03-03"], ["2026-03-10"]], "row_count": 2})
    assert grounding.unsupported("arrivés 7 jours plus tard", known) == []


def test_a_count_from_no_result_is_sent_back_then_flagged(sources):
    llm = ScriptedLLM(AIMessage("", tool_calls=[call("execute_sql", source="erp", sql=MARCH)]),
                      AIMessage("Le mois compte 219 factures."))
    answer = run(llm)["answer"]
    assert len(llm.calls) == 3 and "Vérification automatique" in str(llm.calls[-1][-1].content)
    assert "⚠️" in answer and "219 factures" in answer.split("⚠️")[1]


def test_previous_answers_lose_their_chart_links():
    answer = "CA : 5 €\n\n![CA [2026]](http://x/charts/0123456789abcdef.png?exp=1&sig=abc)"
    assert previous_answer(answer) == "CA : 5 €"


def test_previous_answers_lose_their_footer_but_keep_their_queries():
    answer = ("**CA : 5 €**\n\n---\n**Comment ce résultat a été obtenu** (journal, session `x`)\n\n"
              "**q1** · erp (SQL Server) · 1 ligne(s)\n```sql\nSELECT 1\nFROM t\n```")
    assert previous_answer(answer) == "**CA : 5 €**\n\n[Requêtes exécutées pour cette réponse : SELECT 1 FROM t]"


def test_the_model_never_sees_the_parameters_the_agent_fills():
    class Tool:
        name, description = "execute_sql", "x"
        input_schema = {"type": "object", "required": ["source", "sql"], "properties": {
            "source": {}, "sql": {}, "question": {}, "session_id": {}, "max_rows": {}}}
    schema = tool_schema(Tool())["function"]["parameters"]
    assert set(schema["properties"]) == {"source", "sql"} and schema["required"] == ["source", "sql"]


# --- with the sources -----------------------------------------------------------------------------------------------
def test_an_answer_gets_the_queries_that_ran(sources):
    llm = ScriptedLLM(AIMessage("", tool_calls=[call("execute_sql", source="erp", sql=MARCH)]),
                      lambda ms: AIMessage(f"CA de mars : {last_tool_result(ms).split('[[')[1].split(']]')[0]} €"))
    result = run(llm)
    assert "13599646.63 €" in result["answer"]
    assert "**q1** · erp (SQL Server) · 1 ligne(s)" in result["answer"] and "FAC_DT >= '2026-03-01'" in result["answer"]
    assert "session `test-session`" in result["answer"]
    step = result["steps"][0]
    assert step["ok"] and step["id"] == "q1" and "question" not in step["args"]


def test_the_model_sees_a_preview_and_reconcile_reads_every_row(sources, monkeypatch):
    monkeypatch.setattr(settings, "rows_to_model", 3)
    per_client = ("SELECT c.CLI_TVA, SUM(CASE WHEN f.FAC_TYPE = 'A' THEN -f.FAC_MT_HT ELSE f.FAC_MT_HT END) AS ca "
                  "FROM VTE_FACT f JOIN CLI_CLIENT c ON c.CLI_ID = f.CLI_ID "
                  "WHERE f.FAC_DT >= '2026-05-01' AND f.FAC_DT < '2026-06-01' GROUP BY c.CLI_TVA")
    seen = {}

    def answer(ms):
        seen["reconcile"] = last_tool_result(ms)
        return AIMessage("Rapprochement fait.")
    llm = ScriptedLLM(AIMessage("", tool_calls=[call("execute_sql", 1, source="erp", sql=per_client),
                                                call("execute_sql", 2, source="erp", sql=per_client + " ORDER BY 1")]),
                      lambda ms: AIMessage("", tool_calls=[call("reconcile", left="q1", right="q2", left_key="CLI_TVA",
                                                                right_key="cli_tva", key_type="vat",
                                                                compare=[["ca", "ca"]])]),
                      answer)
    result = run(llm, "Compare deux fois la même chose")
    preview = llm.calls[1][-1].content
    assert '"note": "3 premières lignes sur' in preview
    assert '"matched": 224' in seen["reconcile"] and '"differences": 0' in seen["reconcile"]
    assert "Rapprochement en Python : q1.CLI_TVA ↔ q2.cli_tva (clé vat)" in result["answer"]


def test_failed_queries_are_bounded(sources):
    bad = AIMessage("", tool_calls=[call("execute_sql", source="erp", sql="SELECT NOPE FROM VTE_FACT")])
    llm = ScriptedLLM(bad, AIMessage("Je ne sais pas : la requête échoue."))
    llm.replies = [bad] * settings.max_sql_errors + [bad, AIMessage("Je ne sais pas : la requête échoue.")]
    result = run(llm)
    failed = [s for s in result["steps"] if not s["ok"]]
    assert len(failed) == settings.max_sql_errors          # the next attempt was not run
    final_prompt = llm.calls[-1]
    assert isinstance(final_prompt[-1], HumanMessage) and "Limite atteinte" in final_prompt[-1].content
    assert final_prompt[-2].content.startswith("Non exécuté")
    assert result["answer"].startswith("Je ne sais pas")


def test_tool_calls_are_bounded(sources, monkeypatch):
    monkeypatch.setattr(settings, "max_tool_calls", 3)
    card = AIMessage("", tool_calls=[call("get_table_card", source="erp", table="VTE_FACT")])
    llm = ScriptedLLM(card, card, card, card, AIMessage("Je ne sais pas."))
    result = run(llm)
    assert len(result["steps"]) == 3 and result["answer"] == "Je ne sais pas."


def test_an_invented_figure_is_sent_back_then_refused(sources):
    invented = AIMessage("Le CA d'avril est de 13 999 646,63 €.")
    llm = ScriptedLLM(invented, invented)
    result = run(llm, "et pour avril ?", history=[
        {"role": "user", "content": "Quel est le CA de mars 2026 ?"},
        {"role": "assistant", "content": "CA de mars : 13 599 646,63 €."}])
    assert "Vérification automatique : 13 999 646,63" in llm.calls[1][-1].content
    assert result["answer"].startswith("Je ne sais pas") and "13 999 646" not in result["answer"]


def test_a_figure_from_the_conversation_needs_no_query(sources):
    llm = ScriptedLLM(AIMessage("Comme dit plus haut, 13 599 646,63 € en mars."))
    result = run(llm, "Tu peux me redire le chiffre de mars ?", history=[
        {"role": "user", "content": "Quel est le CA de mars 2026 ?"},
        {"role": "assistant", "content": "CA de mars : 13 599 646,63 €."}])
    assert len(llm.calls) == 1 and result["answer"].startswith("Comme dit plus haut")


def test_a_copied_footer_is_replaced_by_the_real_one(sources):
    llm = ScriptedLLM(AIMessage("", tool_calls=[call("execute_sql", source="erp", sql=MARCH)]),
                      AIMessage("CA : 13 599 646,63 €\n\n[Requêtes exécutées pour cette réponse : SELECT 42]\n\n---\n"
                                "**Comment ce résultat a été obtenu** (session `fausse`)\n\n**q9** · erp"))
    answer = run(llm)["answer"]
    assert "SELECT 42" not in answer and "fausse" not in answer and "**q1** · erp" in answer


@pytest.mark.parametrize("name", ["get_sales_commission", "execute_sql"])
def test_the_query_log_gets_the_question_and_session(sources, name, monkeypatch):
    sent = {}

    async def spy(self, tool, args):
        sent.update(args)
        return await original(self, tool, args)
    from mcp.client import Client
    original = Client.call_tool
    monkeypatch.setattr(Client, "call_tool", spy)
    args = {"staff_number": "10405", "month": "2026-03"} if name == "get_sales_commission" else {"source": "erp", "sql": MARCH}
    run(ScriptedLLM(AIMessage("", tool_calls=[call(name, **args)]), AIMessage("ok")), "Q?")
    assert sent["question"] == "Q?" and sent["session_id"] == "test-session"
    assert ("max_rows" in sent) == (name == "execute_sql")


def test_the_system_prompt_carries_the_ontology(sources):
    llm = ScriptedLLM(AIMessage("Pouvez-vous préciser : facturé ou comptabilisé ?"))
    run(llm, "Quel est le chiffre d'affaires de mai ?")
    system = llm.calls[0][0].content
    assert "erp.VTE_FACT : Customer Invoice and Credit Note" in system
    assert "**EBITDA** (compta, ligne_ecriture)" in system
    assert settings.data_until in system and "{" not in system.split("# Méthode")[1][:50]
    assert {t["function"]["name"] for t in llm.tools} >= {"execute_sql", "reconcile", "get_table_card"}


def test_the_model_reads_the_warning_of_a_query(sources):
    sql = "SELECT COUNT(*) FROM ecriture e JOIN ligne_ecriture l ON l.id_ecriture = e.id_ecriture"
    seen = []
    def reply(messages):
        seen.append(last_tool_result(messages))
        return AIMessage("Voici le résultat.")
    run(ScriptedLLM(AIMessage("", tool_calls=[call("execute_sql", source="compta", sql=sql)]), reply))
    assert "COUNT(DISTINCT e.id_ecriture)" in seen[0]


def test_the_other_readings_come_before_the_footer_when_a_query_ran(sources):
    llm = ScriptedLLM(AIMessage("", tool_calls=[call("execute_sql", source="erp", sql=MARCH)]),
                      AIMessage("Le chiffre d'affaires net facturé de mars 2026 est celui de l'ERP."))
    answer = run(llm, "Quel est le chiffre d'affaires de mars 2026 ?")["answer"]
    assert "comptabilisé (comptes 70)" in answer
    assert answer.index("peut aussi se lire") < answer.index("Comment ce résultat a été obtenu")


def test_no_other_readings_when_no_query_ran(sources):
    llm = ScriptedLLM(AIMessage("Voulez-vous le chiffre d'affaires facturé ou comptabilisé ?"))
    assert "peut aussi se lire" not in run(llm, "Quel est le chiffre d'affaires de mars ?")["answer"]


def test_agent_module_exposes_a_default_agent():
    assert callable(agent_module.default_agent)


def test_without_ontology_neither_the_prompt_nor_the_cards_carry_it(sources):
    llm = ScriptedLLM(AIMessage("", tool_calls=[call("get_table_card", source="erp", table="VTE_FACT")]),
                      AIMessage("Pouvez-vous préciser ?"))
    anyio.run(lambda: Agent(mcp_target=server, llm=llm, use_ontology=False).ask(
        [{"role": "user", "content": "CA ?"}], "test"))
    system, card = llm.calls[0][0].content, llm.calls[1][-1].content
    assert "ontologie" not in system.lower() and "EBITDA" not in system and "{" not in system
    assert "ontology_terms" not in card and "FAC_TYPE" in card


def test_failed_queries_say_where_they_failed(sources):
    llm = ScriptedLLM(AIMessage("", tool_calls=[call("execute_sql", 1, source="erp", sql="SELECT NOPE FROM VTE_FACT"),
                                                call("execute_sql", 2, source="erp", sql="SELECT 1/0 AS x")]),
                      AIMessage("Je ne sais pas."))
    steps = run(llm)["steps"]
    assert [s["stage"] for s in steps] == ["validation", "execution"]


def test_the_same_query_twice_is_not_run_again(sources):
    again = AIMessage("", tool_calls=[call("execute_sql", source="erp", sql=MARCH + "  ;")])
    llm = ScriptedLLM(AIMessage("", tool_calls=[call("execute_sql", source="erp", sql=MARCH)]), again,
                      AIMessage("CA de mars : 13 599 646,63 €"))
    result = run(llm)
    assert [s.get("stage") for s in result["steps"]] == [None, "repeat"]
    assert "Requête identique à q1" in llm.calls[2][-1].content
    assert result["answer"].count("**q") == 1


def test_a_figure_in_thousands_is_grounded_by_the_figure_in_euros():
    # Step 15: a remembered preference ("en milliers d'euros") must not force a second query to pass the check
    corpus = '{"rows": [[13599646.63]]}'
    assert ungrounded("**13 599,6 k€** en mars, soit 13,6 millions", corpus) == []
    assert ungrounded("**13 724,1 k€** en mars", corpus) == ["13 724,1"]
    assert ungrounded("13 599 646,63 k€", corpus) == ["13 599 646,63"]   # a unit can also make a figure wrong
