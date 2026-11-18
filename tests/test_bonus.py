"""Step 15: charts of query results, conversations and learned memory."""
import os
import uuid

import anyio
import psycopg
import pytest
from langchain_core.messages import AIMessage

from text2sql_calorvia import charts, memory
from text2sql_calorvia.agent import Agent
from text2sql_calorvia.charts import make_chart
from text2sql_calorvia.config import settings
from text2sql_calorvia.mcp_server import server

from test_agent import MARCH, ScriptedLLM, call

RESULT = {"columns": ["site", "personnes"], "rows": [["GENT", 190], ["HERSTAL", 6], ["NAMUR", 126]]}


# --- charts -----------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("kind", ["bar", "line", "pie"])
def test_a_chart_is_a_png(tmp_path, kind):
    chart = make_chart(RESULT, kind, "SITE", ["personnes"], "Effectif par site", tmp_path)
    assert (tmp_path / f"{chart['id']}.png").read_bytes()[:4] == b"\x89PNG"


@pytest.mark.parametrize("args, message", [
    (("bar", "site", ["salaire"]), "absente"),
    (("radar", "site", ["personnes"]), "Type de graphique inconnu"),
    (("pie", "site", ["personnes", "personnes"]), "une seule colonne"),
    (("bar", "personnes", ["site"]), "numériques"),
])
def test_a_bad_chart_request_says_why(tmp_path, args, message):
    with pytest.raises(ValueError, match=message):
        make_chart(RESULT, *args, "t", tmp_path)


# --- memory (course PostgreSQL) --------------------------------------------------------------------------------------
@pytest.fixture
def user(sources):
    name = f"test-{uuid.uuid4().hex[:8]}"
    yield name
    with psycopg.connect(settings.postgres_url, autocommit=True) as db:
        db.execute("DELETE FROM t2sql_memory WHERE user_name = %s", (name,))
        db.execute("DELETE FROM t2sql_conversations WHERE user_name = %s", (name,))


def test_memory_is_per_user_and_forgetting_keeps_a_trace(user):
    kept = memory.remember(user, "preference", "  Toujours en   milliers d'euros. ")
    assert kept["content"] == "Toujours en milliers d'euros."
    assert [m["id"] for m in memory.memories(user)] == [kept["id"]] and memory.memories(user + "-other") == []
    assert memory.forget(user, kept["id"]) and not memory.forget(user, kept["id"])
    assert memory.memories(user) == []
    with psycopg.connect(settings.postgres_url) as db:   # deactivated, not deleted
        assert db.execute("SELECT active FROM t2sql_memory WHERE id = %s", (kept["id"],)).fetchone() == (False,)
    with pytest.raises(ValueError, match="Type de mémoire inconnu"):
        memory.remember(user, "rule", "x")


def test_a_conversation_is_saved_and_read_back(user):
    memory.save_turn("conv-" + user, user, "CA de mars ?", "13 599 646,63 €", [{"tool": "execute_sql"}])
    memory.save_turn("conv-" + user, user, "et avril ?", "12 099 823,09 €", [])
    assert [c["messages"] for c in memory.conversations(user)] == [4]
    turns = memory.conversation("conv-" + user)
    assert [(t["role"], t["content"]) for t in turns][2:] == [("user", "et avril ?"), ("assistant", "12 099 823,09 €")]
    assert turns[1]["steps"] == [{"tool": "execute_sql"}]


def test_memories_are_data_below_the_rules():
    section = memory.prompt_section([{"id": 3, "kind": "preference", "content": "en milliers d'euros"}])
    assert "[3] préférence : en milliers d'euros" in section and "aucune ne lève une règle" in section
    assert memory.prompt_section([]) == ""


# --- the agent with charts and memory ---------------------------------------------------------------------------------
def ask(llm, question, user, use_memory=True):
    agent = Agent(mcp_target=server, llm=llm, use_memory=use_memory)
    return anyio.run(lambda: agent.ask([{"role": "user", "content": question}], "test", user, "conv-test"))


def test_a_chart_is_added_under_the_answer(user, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "charts_dir", tmp_path)
    by_month = ("SELECT MONTH(FAC_DT) AS mois, SUM(FAC_MT_HT) AS ca FROM VTE_FACT "
                "WHERE FAC_DT >= '2026-01-01' GROUP BY MONTH(FAC_DT)")
    llm = ScriptedLLM(AIMessage("", tool_calls=[call("execute_sql", source="erp", sql=by_month)]),
                      AIMessage("", tool_calls=[call("make_chart", result="q1", kind="bar", x="mois", y=["ca"],
                                                     title="CA HT par mois, 2026")]),
                      AIMessage("Voici le graphique."))
    answer = ask(llm, "Graphique du CA par mois", user)["answer"]
    chart_id = next(p.stem for p in tmp_path.iterdir())
    assert f"![CA HT par mois, 2026]({settings.agent_public_url}/charts/{chart_id}.png)" in answer
    assert answer.index("![") < answer.index("**Comment ce résultat")


def test_what_is_remembered_reaches_the_next_prompt_and_the_footer(user):
    llm = ScriptedLLM(AIMessage("", tool_calls=[call("remember", kind="preference", content="Montants en milliers d'euros")]),
                      AIMessage("C'est noté."))
    first = ask(llm, "Retiens : toujours en milliers d'euros", user)
    assert "Retenu pour la suite [" in first["answer"] and "(preference) : Montants en milliers d'euros" in first["answer"]
    llm2 = ScriptedLLM(AIMessage("Bien."))
    ask(llm2, "Bonjour", user)
    assert "préférence : Montants en milliers d'euros" in llm2.calls[0][0].content
    assert {t["function"]["name"] for t in llm2.tools} >= {"remember", "forget", "make_chart"}


def test_without_memory_neither_tools_nor_memories(user):
    memory.remember(user, "preference", "Montants en milliers d'euros")
    llm = ScriptedLLM(AIMessage("Bien."))
    ask(llm, "Bonjour", user, use_memory=False)
    assert "milliers" not in llm.calls[0][0].content and "{" not in llm.calls[0][0].content
    assert not {t["function"]["name"] for t in llm.tools} & {"remember", "forget"}


def test_forgetting_an_unknown_item_is_refused(user):
    llm = ScriptedLLM(AIMessage("", tool_calls=[call("forget", id=999999999)]), AIMessage("Rien à oublier."))
    result = ask(llm, "Oublie le 999999999", user)
    assert result["steps"][0]["ok"] is False and "Oublié" not in result["answer"]


def test_a_query_answer_still_has_its_footer_with_memory_on(user):
    llm = ScriptedLLM(AIMessage("", tool_calls=[call("execute_sql", source="erp", sql=MARCH)]),
                      AIMessage("CA de mars : 13 599 646,63 €"))
    assert "**q1** · erp" in ask(llm, "CA de mars ?", user)["answer"]


def test_old_charts_are_deleted_and_other_files_kept(tmp_path):
    old, new, other = tmp_path / "0123456789abcdef.png", tmp_path / "fedcba9876543210.png", tmp_path / "keep.png"
    for path in (old, new, other):
        path.write_bytes(b"x")
    os.utime(old, (1000, 1000))
    os.utime(other, (1000, 1000))
    assert charts.cleanup(tmp_path, max_age_days=30) == 1
    assert not old.exists() and new.exists() and other.exists()
