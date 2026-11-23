"""Step 44: fewer wasted rounds. Hints after a database error, no second run of a query that failed, a wrap_up that
keeps the server's cache (the same tools, tool_choice="none")."""
from langchain_core.messages import AIMessage

from text2sql_calorvia.agent import query_key
from text2sql_calorvia.execution import execute
from text2sql_calorvia.sql_hints import hint, select_aliases

from test_agent import ScriptedLLM, call, run

# The query of the trace that took 283 s: an alias in an ORDER BY expression, sent three times
ALIAS_SQL = ("SELECT a.ART_LIB, SUM(l.FL_MT_HT) AS ca_2025, SUM(l.FL_QTE) AS unites FROM VTE_FACT_LIG l "
             "JOIN ART_ARTICLE a ON a.ART_ID = l.ART_ID GROUP BY a.ART_LIB ORDER BY ca_2025 + unites DESC")


# --- hints, without databases ------------------------------------------------------------------------------------------
def test_an_alias_in_an_order_by_expression_gets_the_rewrite():
    for source, message in (("erp", "Invalid column name 'ca_2025'."), ("compta", 'column "ca_2025" does not exist')):
        advice = hint(source, ALIAS_SQL, message)
        assert "« ca_2025 » est un alias du SELECT" in advice and "SELECT * FROM (…) t ORDER BY" in advice


def test_a_column_that_is_not_an_alias_gets_no_hint():
    assert hint("erp", ALIAS_SQL, "Invalid column name 'NOPE'.") is None


def test_the_aliases_are_those_of_the_outer_select():
    assert select_aliases(ALIAS_SQL, "tsql") == {"ca_2025", "unites"}
    assert select_aliases("SELECT x FROM (SELECT 1 AS inner_one) t", "postgres") == set()
    assert select_aliases("SELECT 1 AS a FROM", "tsql") == {"a"}   # unparsable: the aliases are still found


def test_order_by_a_sum_of_column_numbers_gets_the_rewrite():
    advice = hint("erp", "SELECT 1, 2 ORDER BY 2 + 3 DESC",
                  "A constant expression was encountered in the ORDER BY list, position 1.")
    assert "ORDER BY 2 DESC" in advice and "SELECT * FROM (…) t" in advice


def test_a_table_prefixed_with_the_source_name_gets_its_sql_name():
    assert hint("erp", "SELECT 1", "Invalid object name 'erp.dbo.STK_MVT'.").endswith("écrivez dbo.STK_MVT.")
    assert "list_tables" in hint("compta", "SELECT 1", 'relation "ecritures" does not exist')


def test_a_column_outside_group_by_gets_both_fixes():
    erp = hint("erp", "SELECT 1", "Column 'VTE_FACT_LIG.ART_ID' is invalid in the select list because it is not "
               "contained in either an aggregate function or the GROUP BY clause.")
    assert "Ajoutez VTE_FACT_LIG.ART_ID au GROUP BY" in erp and "MAX(VTE_FACT_LIG.ART_ID)" in erp
    assert "GROUP BY" in hint("paie", "SELECT 1", 'column "e.site" must appear in the GROUP BY clause or be used in an '
                              "aggregate function")


def test_top_with_offset_gets_the_t_sql_form():
    assert "FETCH NEXT" in hint("erp", "SELECT 1", "A TOP can not be used in the same query or sub-query as a OFFSET.")


def test_queries_compare_up_to_spacing_and_the_row_limit():
    assert query_key("erp", "SELECT 1\n  FROM t ;") == query_key("erp", "SELECT 1 FROM t")
    assert query_key("compta", "SELECT 1 LIMIT 5") == query_key("compta", "SELECT 1")
    assert query_key("erp", "SELECT 1") != query_key("compta", "SELECT 1")


# --- with the course databases --------------------------------------------------------------------------------------------
def test_the_database_error_comes_with_its_hint(sources):
    r = execute("erp", ALIAS_SQL)
    assert not r["ok"] and r["errors"][0] == "Erreur à l'exécution : Invalid column name 'ca_2025'."
    assert r["errors"][1].startswith("Piste : « ca_2025 » est un alias du SELECT")


def test_a_query_that_failed_is_not_run_again(sources):
    bad = AIMessage("", tool_calls=[call("execute_sql", source="erp", sql=ALIAS_SQL)])
    again = AIMessage("", tool_calls=[call("execute_sql", 2, source="erp", sql=ALIAS_SQL.replace(" DESC", "  DESC"))])
    llm = ScriptedLLM(bad, again, AIMessage("Je ne sais pas : la requête échoue."))
    steps = run(llm)["steps"]
    assert [s["stage"] for s in steps] == ["execution", "repeat"]
    assert "déjà refusée" in steps[1]["errors"][0] and "est un alias du SELECT" in steps[1]["errors"][0]


def test_wrap_up_keeps_the_tools_without_letting_the_model_call_them(sources, monkeypatch):
    from text2sql_calorvia.config import settings
    monkeypatch.setattr(settings, "max_tool_calls", 2)
    card = AIMessage("", tool_calls=[call("get_table_card", source="erp", table="VTE_FACT")])
    llm = ScriptedLLM(card, card, card, AIMessage("Je ne sais pas."))
    run(llm)
    assert llm.choices[-1] == "none" and llm.choices[:-1] == [None] * (len(llm.choices) - 1)
    assert {t["function"]["name"] for t in llm.tools} >= {"execute_sql", "get_table_card"}
