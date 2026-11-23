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

from text2sql_calorvia import ontology
from text2sql_calorvia.agent import Agent, RECONCILE_TOOL, scoped_tools, system_prompt, tool_schema
from text2sql_calorvia.catalog import describe
from text2sql_calorvia.execution import execute, log_connect, run_unvalidated
from text2sql_calorvia.mcp_server import server
from text2sql_calorvia.sources import SOURCES, connect
from text2sql_calorvia.validation import validate

DB_ERRORS = (psycopg.Error, pymssql.Error)
ACTIVE = list(access.roles())
GENT, SENEFFE, NAMUR, HERSTAL = (f"responsable_site_{s}" for s in ("gent", "seneffe", "namur", "herstal"))
SITES = {GENT: ("GENT", 3), SENEFFE: ("SENEFFE", 2), NAMUR: ("NAMUR", 1), HERSTAL: ("HERSTAL", 5)}
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

    def bind_tools(self, tools, tool_choice=None):
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


# Step 26: what the model and the messages reveal
def test_a_forbidden_table_looks_like_one_that_does_not_exist(sources):
    forbidden = validate("erp", "SELECT COUNT(*) FROM ACH_FACT", role="commercial")
    assert not forbidden.ok and forbidden.errors[0].startswith("Table inconnue dans erp : ACH_FACT.")
    assert "ACH_CDE" not in forbidden.errors[0] and "ACH_RECEP" not in forbidden.errors[0]
    assert "ACH_FACT" not in validate("erp", "SELECT COUNT(*) FROM ACH_FAC", role="commercial").errors[0]


def test_no_message_points_to_a_source_the_role_cannot_read(sources):
    error = validate("erp", "SELECT COUNT(*) FROM ecriture", role="commercial").errors[0]
    assert "compta" not in error
    assert validate("compta", "SELECT 1", role="commercial").errors == ["Source inconnue : compta. Sources : erp."]
    assert validate("compta", "SELECT 1", role="employe").errors == ["Source inconnue : compta. Sources : aucune."]
    assert "compta" in validate("erp", "SELECT COUNT(*) FROM ecriture", role="finance").errors[0]


def test_validation_accepts_the_tables_of_the_role(sources):
    assert validate("erp", "SELECT COUNT(*) FROM VTE_FACT", role="commercial").ok
    assert validate("paie", "SELECT COUNT(*) FROM timesheets", role="rh").ok


def test_the_prompt_shows_only_what_the_role_reads():
    scope = access.scope_of("commercial")
    prompt = system_prompt([{"source": "erp", "engine": "e", "dialect": "d", "description": "ERP"}], scope=scope)
    assert "Net invoiced revenue" in prompt and "erp.VTE_FACT" in prompt and "Votre périmètre" in prompt
    for hidden in ("Booked revenue", "EBITDA", "Headcount on a date", "compta.ecriture", "paie.contracts", "erp.ACH_FACT"):
        assert hidden not in prompt


def test_without_a_role_the_prompt_has_no_scope_section():
    assert "Votre périmètre" not in system_prompt([])
    assert system_prompt([], scope=None) == system_prompt([])


def test_a_metric_needs_every_table_it_uses():
    assert "Units sold net of returns" not in ontology.glossary({"erp": {"vte_fact"}})
    assert "Units sold net of returns" in ontology.glossary({"erp": {"vte_fact", "vte_fact_lig"}})


def test_a_reading_the_role_cannot_compute_is_not_offered():
    question, answer = "Quel est le chiffre d'affaires de mai ?", "10 €"
    assert "comptabilisé" in ontology.other_readings(question, answer, access.scope_of("finance"))
    assert ontology.other_readings(question, answer, access.scope_of("commercial")) == ""


def test_a_card_names_no_table_the_role_cannot_read(logins):
    card = tool("get_table_card", source="erp", table="VTE_CDE", access_token=access.issue_token("achats", "a"))
    assert "Table inconnue" in card["error"]
    keys = tool("get_table_card", source="erp", table="ART_ARTICLE",
                access_token=access.issue_token("commercial", "c"))["keys"]
    assert not any("FRN_FOURNISSEUR" in k for k in keys)
    assert any("FRN_FOURNISSEUR" in k for k in tool("get_table_card", source="erp", table="ART_ARTICLE")["keys"])


def test_the_log_records_who_asked(logins):
    result = execute("compta", "SELECT COUNT(*) FROM budget", role="finance", user="ana")
    with log_connect() as db:
        row = db.execute("SELECT user_name, role FROM t2sql_query_log WHERE id = %s", (result["log_id"],)).fetchone()
    assert row == ("ana", "finance")


@pytest.mark.parametrize("role, hidden", [("commercial", ["compta", "paie", "comptabilis", "- Paie :"]),
                                          ("employe", ["compta", "T-SQL", "comptabilis", "- Paie :"]),
                                          ("rh", ["compta", "comptabilis"])])
def test_the_prompt_names_no_source_the_role_cannot_read(role, hidden):
    scope = access.scope_of(role)
    sources = [{"source": s, "engine": "e", "dialect": "d", "description": ""} for s in scope]
    prompt = system_prompt(sources, memories="", scope=scope).lower()
    assert not [word for word in hidden if word.lower() in prompt]


def test_the_tools_name_no_source_the_role_cannot_read():
    async def schemas():
        async with Client(server) as client:
            return [tool_schema(t) for t in (await client.list_tools()).tools] + [RECONCILE_TOOL]
    tools = scoped_tools(anyio.run(schemas), access.scope_of("commercial"))
    names, text = {t["function"]["name"] for t in tools}, str(tools).lower()
    assert "reconcile" not in names and "get_sales_commission" not in names and "execute_sql" in names
    assert "compta" not in text and "paie" not in text
    both = {t["function"]["name"] for t in scoped_tools(anyio.run(schemas), access.scope_of("rh"))}
    assert {"reconcile", "get_sales_commission"} <= both


# Step 27: rows
def count(source, sql, role=None):
    return run_unvalidated(source, sql, max_rows=1, role=role, timeout_s=30)[1][0][0]


@pytest.mark.parametrize("role", list(SITES))
@pytest.mark.parametrize("table", ["PRD_OF", "STK_ETAT", "STK_MVT", "ACH_RECEP", "ACH_CDE", "LOG_EXPED"])
def test_a_site_role_sees_its_erp_rows(logins, role, table):
    expected = count("erp", f"SELECT COUNT(*) FROM {table} WHERE SIT_ID = {SITES[role][1]}")
    assert count("erp", f"SELECT COUNT(*) FROM {table}", role) == expected


@pytest.mark.parametrize("role", list(SITES))
@pytest.mark.parametrize("lines, parent, key", [("ACH_RECEP_LIG", "ACH_RECEP", "REC_ID"), ("ACH_CDE_LIG", "ACH_CDE", "AC_ID")])
def test_erp_lines_follow_their_parent(logins, role, lines, parent, key):
    expected = count("erp", f"SELECT COUNT(*) FROM {lines} l JOIN {parent} p ON p.{key} = l.{key} "
                            f"WHERE p.SIT_ID = {SITES[role][1]}")
    assert count("erp", f"SELECT COUNT(*) FROM {lines}", role) == expected


@pytest.mark.parametrize("role", list(SITES))
def test_a_site_role_sees_its_payroll_rows(logins, role):
    site = SITES[role][0]
    assert count("paie", "SELECT COUNT(*) FROM departments", role) == count(
        "paie", f"SELECT COUNT(*) FROM departments WHERE site_code = '{site}'")
    in_site = f"JOIN departments d ON d.department_code = c.department_code WHERE d.site_code = '{site}'"
    assert count("paie", "SELECT COUNT(*) FROM contracts", role) == count(
        "paie", f"SELECT COUNT(*) FROM contracts c {in_site}")
    assert count("paie", "SELECT COUNT(*) FROM timesheets WHERE work_date = '2026-03-10'", role) == count(
        "paie", "SELECT COUNT(*) FROM timesheets t WHERE t.work_date = '2026-03-10' AND EXISTS (SELECT 1 FROM contracts c "
                f"{in_site} AND c.employee_id = t.employee_id AND c.start_date <= t.work_date "
                "AND (c.end_date IS NULL OR c.end_date >= t.work_date))")


@pytest.mark.parametrize("source, sql, role", [
    ("erp", "SELECT COUNT(*) FROM STK_MVT", "direction"), ("erp", "SELECT COUNT(*) FROM STK_MVT", "achats"),
    ("paie", "SELECT COUNT(*) FROM timesheets", "rh"), ("paie", "SELECT COUNT(*) FROM contracts", "direction"),
])
def test_other_roles_keep_every_row(logins, source, sql, role):
    assert count(source, sql, role) == count(source, sql)


@pytest.mark.parametrize("source, sql", [
    ("paie", "SET ROLE agent_ro"),
    ("paie", "SET ROLE agent_r_direction"),
    ("paie", "ALTER TABLE contracts DISABLE ROW LEVEL SECURITY"),
    ("paie", "DROP POLICY site_rows ON contracts"),
    ("paie", "DELETE FROM access_control.role_site"),
    ("erp", "EXECUTE AS USER = 'dbo'"),
    ("erp", "ALTER SECURITY POLICY access_control.site_rows WITH (STATE = OFF)"),
    ("erp", "DELETE FROM access_control.role_site"),
    ("erp", "SELECT * FROM access_control.role_site"),
])
def test_a_site_login_cannot_remove_its_limit(logins, source, sql):
    with pytest.raises(DB_ERRORS):
        run_unvalidated(source, sql, role=GENT)


def test_row_security_cannot_be_switched_off_for_the_session(logins):
    conn = connect("paie", role=GENT)
    try:
        cur = conn.cursor()
        cur.execute("SET row_security = off")
        with pytest.raises(psycopg.Error):
            cur.execute("SELECT COUNT(*) FROM contracts")
    finally:
        conn.rollback()
        conn.close()


def test_what_a_site_role_is_shown_comes_from_its_rows(logins):
    token = access.issue_token(GENT, "g")
    departments = tool("get_table_card", source="paie", table="departments", access_token=token)
    assert departments["rows"] == count("paie", "SELECT COUNT(*) FROM departments WHERE site_code = 'GENT'")
    assert {v["value"] for v in departments["code_columns"]["site_code"]["values"]} == {"GENT"}
    tables = {t["table"]: t["rows"] for t in tool("list_tables", source="erp", access_token=token)}
    assert tables["PRD_OF"] == count("erp", "SELECT COUNT(*) FROM PRD_OF WHERE SIT_ID = 3") and "VTE_FACT" not in tables
    seneffe = tool("find_values", source="paie", value="Maintenance Seneffe", access_token=token)["matches"]
    assert not [m for m in seneffe if "Seneffe" in str(m["value"])]
    assert [m for m in tool("find_values", source="paie", value="Onderhoud Gent", access_token=token)["matches"]]


def test_the_prompt_of_a_site_role_names_its_site():
    prompt = system_prompt([], scope=access.scope_of(GENT), site=access.site_label(GENT))
    assert "site de Gand" in prompt


def test_payroll_rules_still_apply_inside_a_site(logins):
    assert not execute("paie", "SELECT t.employee_id, t.work_date FROM timesheets t WHERE t.absence_code = 'MAL'",
                       role=GENT)["ok"]
    assert execute("paie", "SELECT COUNT(*) FROM timesheets t WHERE t.absence_code IN ('MAL', 'MAL_MUT')", role=GENT)["ok"]
