"""Phase D: the roles of policy/roles.yaml, their logins and the role token. The logins are created by
scripts/apply_roles.py; the database tests are skipped if it hasn't run. Statements go straight to the database,
past validation: what is tested is what the login itself may do."""
import anyio
import psycopg
import pymssql
import pytest
from mcp.client import Client

from text2sql_calorvia import access
from langchain_core.messages import AIMessage

from text2sql_calorvia.agent import Agent, tool_schema
from text2sql_calorvia.catalog import describe
from text2sql_calorvia.execution import execute, run_unvalidated
from text2sql_calorvia.mcp_server import server
from text2sql_calorvia.sources import SOURCES, connect

DB_ERRORS = (psycopg.Error, pymssql.Error)
ACTIVE = [r for r, d in access.roles().items() if not d["site"]]
SAMPLE = {"erp": "VTE_FACT", "compta": "ecriture", "paie": "payslips"}


def granted(role, source):
    tables = access.tables_of(role, source)
    return {t["table_name"] for t in describe(source)} if tables == "*" else set(tables)


@pytest.fixture
def logins(sources):
    try:
        connect("compta", role="finance").close()
    except DB_ERRORS:
        pytest.skip("run scripts/apply_roles.py first")


def test_the_approved_roles_are_there():
    assert set(access.policy()["roles"]) == {"direction", "finance", "rh", "commercial", "achats", "operations",
                                             "qualite", "responsable_site", "it", "employe"}
    assert {r for r in access.roles() if r.startswith("responsable_site_")} == {
        f"responsable_site_{s}" for s in ("gent", "seneffe", "namur", "herstal")}


@pytest.mark.parametrize("role", ["it", "employe"])
def test_some_roles_read_no_database(role):
    assert not any(access.tables_of(role, source) for source in SOURCES)


def test_every_listed_table_exists(sources):
    for source in SOURCES:
        known = {t["table_name"] for t in describe(source)}
        for role in access.roles():
            tables = access.tables_of(role, source)
            assert tables == "*" or set(tables) <= known, (role, source)


def test_the_approved_decisions_are_in_the_policy():
    assert access.tables_of("rh", "compta") == []
    assert "VDR_VENDEUR" in access.tables_of("rh", "erp")
    assert "00_Direction/CODIR" in access.roles()["finance"]["documents"]
    assert "04_Qualite" not in access.roles()["operations"]["documents"]
    assert access.roles()["qualite"]["documents"] == ["04_Qualite"]
    assert "employees" not in access.tables_of("finance", "paie")


def test_a_token_names_its_role_and_cannot_be_altered_or_reused_late():
    token = access.issue_token("finance", "alice", now=1000)
    assert access.read_token(token, now=1001) == "finance"
    forged = access.issue_token("direction", "alice", now=1000).split(".")[0] + "." + token.split(".")[1]
    with pytest.raises(access.AccessDenied):
        access.read_token(forged, now=1001)
    with pytest.raises(access.AccessDenied):
        access.read_token(token, now=1000 + access.TOKEN_SECONDS + 1)
    with pytest.raises(access.AccessDenied):
        access.read_token("nothing", now=1001)


def test_users_get_their_role_and_everyone_else_the_default(monkeypatch):
    monkeypatch.setattr(access.settings, "user_roles", "alice:finance, webui/bob:rh, eve:unknown")
    assert access.role_of("alice") == "finance" and access.role_of("webui/bob") == "rh"
    assert access.role_of("mallory") == access.role_of("eve") == access.DEFAULT_ROLE


def test_keys_make_the_token_mandatory(monkeypatch):
    assert access.caller_role(None) is None
    monkeypatch.setattr(access.settings, "api_keys", "alice:k")
    with pytest.raises(access.AccessDenied):
        access.caller_role(None)


def test_the_model_never_sees_the_token():
    async def tools():
        async with Client(server) as client:
            return (await client.list_tools()).tools
    for tool in anyio.run(tools):
        assert "access_token" not in tool_schema(tool)["function"]["parameters"]["properties"]


def test_a_site_role_is_refused_until_its_rows_are_limited():
    with pytest.raises(access.AccessDenied, match="pas encore activé"):
        connect("paie", role="responsable_site_gent")


@pytest.mark.parametrize("role", ACTIVE)
@pytest.mark.parametrize("source", list(SOURCES))
def test_a_login_reads_its_tables_and_nothing_else(logins, role, source):
    if not access.tables_of(role, source):
        with pytest.raises(access.AccessDenied):
            connect(source, role=role)
        return
    allowed = granted(role, source)
    for table in {t["table_name"] for t in describe(source)}:
        column = "COUNT(*)" if table != "employees" else "COUNT(employee_id)"
        if table in allowed:
            run_unvalidated(source, f"SELECT {column} FROM {table}", max_rows=1, role=role)
        else:
            with pytest.raises(DB_ERRORS):
                run_unvalidated(source, f"SELECT {column} FROM {table}", max_rows=1, role=role)


@pytest.mark.parametrize("role, source, sql", [
    ("direction", "paie", "UPDATE contracts SET weekly_hours = 0"),
    ("direction", "compta", "DELETE FROM budget"),
    ("direction", "erp", "DELETE FROM VTE_FACT"),
    ("finance", "compta", "CREATE TABLE x (a int)"),
    ("commercial", "erp", "DROP TABLE VTE_FACT"),
    ("direction", "erp", "EXEC xp_cmdshell 'dir'"),
])
def test_a_login_cannot_write(logins, role, source, sql):
    with pytest.raises(DB_ERRORS):
        run_unvalidated(source, sql, role=role)


@pytest.mark.parametrize("role", ["direction", "rh"])
@pytest.mark.parametrize("column", ["national_number", "iban", "street_address"])
def test_hidden_payroll_columns_stay_hidden(logins, role, column):
    with pytest.raises(psycopg.Error):
        run_unvalidated("paie", f"SELECT {column} FROM employees", role=role)


def test_a_role_cannot_turn_its_read_only_default_off_and_write(logins):
    conn = connect("compta", role="finance")
    try:
        cur = conn.cursor()
        cur.execute("SET default_transaction_read_only = off")
        with pytest.raises(psycopg.Error):
            cur.execute("DELETE FROM budget")
    finally:
        conn.rollback()
        conn.close()


def test_execute_runs_under_the_role(logins):
    assert execute("compta", "SELECT COUNT(*) FROM ecriture", role="finance")["ok"]
    assert not execute("compta", "SELECT COUNT(*) FROM ecriture", role="rh")["ok"]
    assert not execute("erp", "SELECT COUNT(*) FROM VTE_FACT", role="achats")["ok"]
    assert execute("erp", "SELECT COUNT(*) FROM ACH_FACT", role="achats")["ok"]


def test_the_mcp_server_uses_the_role_of_the_token(logins):
    async def call(token):
        async with Client(server) as client:
            return (await client.call_tool("execute_sql", {"source": "compta", "sql": "SELECT COUNT(*) FROM ecriture",
                                                           "access_token": token})).structured_content
    assert anyio.run(call, access.issue_token("finance", "alice"))["ok"]
    assert not anyio.run(call, access.issue_token("commercial", "bob"))["ok"]
    assert not anyio.run(call, "forged.token")["ok"]


class OneQuery:
    """A model that runs one query, then answers."""

    def __init__(self, source, sql):
        self.replies = [AIMessage("", tool_calls=[{"name": "execute_sql", "args": {"source": source, "sql": sql},
                                                   "id": "c1", "type": "tool_call"}]), AIMessage("Terminé.")]

    def bind_tools(self, tools):
        return self

    async def ainvoke(self, messages):
        return self.replies.pop(0).model_copy(update={"id": None})


@pytest.mark.parametrize("role, allowed", [("finance", True), ("commercial", False)])
def test_the_real_agent_queries_under_the_role_of_its_token(logins, role, allowed):
    agent = Agent(mcp_target=server, llm=OneQuery("compta", "SELECT COUNT(*) FROM ecriture"), use_memory=False)
    token = access.issue_token(role, "someone")
    result = anyio.run(lambda: agent.ask([{"role": "user", "content": "Combien ?"}], "t", access_token=token))
    assert result["steps"][0]["ok"] is allowed


def tool(name, **args):
    async def call():
        async with Client(server) as client:
            return (await client.call_tool(name, args)).structured_content
    result = anyio.run(call)
    return result.get("result", result) if isinstance(result, dict) else result


def test_a_role_sees_only_its_sources_tables_cards_and_values(logins):
    commercial, finance = access.issue_token("commercial", "c"), access.issue_token("finance", "f")
    assert [s["source"] for s in tool("list_sources", access_token=commercial)] == ["erp"]
    assert tool("list_sources", access_token=access.issue_token("employe", "e")) == []
    assert "error" in tool("get_table_card", source="compta", table="ecriture", access_token=commercial)
    assert "columns" in tool("get_table_card", source="compta", table="ecriture", access_token=finance)
    assert "error" in tool("get_table_card", source="erp", table="ACH_FACT", access_token=commercial)
    tables = {t["table"] for t in tool("list_tables", source="erp", access_token=commercial)}
    assert "VTE_FACT" in tables and "ACH_FACT" not in tables
    assert "error" in tool("find_values", source="compta", value="Distrinergie", access_token=commercial)
    found = tool("find_values", source="erp", value="Kompra", access_token=commercial)
    assert found["matches"] == []       # a supplier: commercial doesn't read suppliers or purchases
    assert tool("find_values", source="erp", value="Distrinergie", access_token=commercial)["matches"]
