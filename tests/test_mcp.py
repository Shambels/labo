"""The MCP server through a real MCP client (in memory), plus the cards and value search it serves."""
import anyio

from mcp.client import Client

from text2sql_calorvia.cards import get_table_card
from text2sql_calorvia.mcp_server import server
from text2sql_calorvia.sources import run_query
from text2sql_calorvia.values import find_values

TOOLS = {"list_sources", "list_tables", "get_table_card", "find_values", "validate_sql", "execute_sql",
         "get_sales_commission"}


def call(name, arguments):
    async def go():
        async with Client(server) as client:
            return (await client.call_tool(name, arguments)).structured_content
    return anyio.run(go)


def test_tools_are_listed_and_all_read_only():
    async def go():
        async with Client(server) as client:
            return (await client.list_tools()).tools
    tools = anyio.run(go)
    assert {t.name for t in tools} == TOOLS
    assert all(t.annotations.read_only_hint and not t.annotations.destructive_hint for t in tools)


def test_execute_through_mcp_matches_a_direct_query(sources):
    sql = ("SELECT SUM(CASE FAC_TYPE WHEN 'A' THEN -FAC_MT_HT ELSE FAC_MT_HT END) FROM VTE_FACT "
           "WHERE FAC_DT >= '2026-03-01' AND FAC_DT < '2026-04-01'")
    result = call("execute_sql", {"source": "erp", "sql": sql, "question": "test: CA de mars"})
    assert result["ok"]
    assert result["rows"][0][0] == float(run_query("erp", sql)[1][0][0])


def test_write_through_mcp_is_refused(sources):
    result = call("execute_sql", {"source": "paie", "sql": "UPDATE payslips SET net_amount = 0"})
    assert not result["ok"] and any("UPDATE" in e for e in result["errors"])


def test_validate_sql_through_mcp(sources):
    result = call("validate_sql", {"source": "compta", "sql": "SELECT libelle FROM journal"})
    assert result["ok"] and result["sql"].endswith("LIMIT 201") and result["tables"] == ["journal"]


def test_table_card_of_the_erp_explains_codes(sources):
    card = get_table_card("erp", "vte_fact")   # case-insensitive
    assert card["table"] == "VTE_FACT" and card["rows"] == 10185
    fac_type = card["code_columns"]["FAC_TYPE"]
    assert fac_type["code_list"] == "TYPE_FACT"
    assert any(v["value"] == "A" and "positifs" in v["label"] for v in fac_type["values"])
    assert "PRIMARY KEY (FAC_ID)" in card["keys"]


def test_table_card_of_payroll_protects_people(sources):
    card = get_table_card("paie", "employees")
    assert card["hidden_columns"]["columns"] == ["national_number", "iban", "street_address"]
    names = {c["name"]: c for c in card["columns"]}
    assert "national_number" not in names
    assert "examples" not in names["last_name"] and "examples" not in names["birth_date"]
    payslips = {c["name"]: c for c in get_table_card("paie", "payslips")["columns"]}
    assert "examples" not in payslips["gross_amount"] and "privacy" in payslips["gross_amount"]


def test_find_values(sources):
    def first(source, value, **kw):
        matches = find_values(source, value, **kw)["matches"]
        return matches[0]["value"] if matches else None
    assert first("erp", "distrinergie") == "Distrinergie SA"
    assert first("erp", "Aeris 12") == "Pompe à chaleur Aéris 12"              # accents
    assert first("erp", "Distrinergy") == "Distrinergie SA"                    # a typo
    assert first("compta", "BE0236099757") == "BE 0236.099.757"                # the ERP's VAT format
    kompra = {m["value"] for m in find_values("erp", "Kompra", table="FRN_FOURNISSEUR")["matches"]}
    assert kompra == {"Kompra GmbH", "KOMPRA GMBH (NE PAS UTILISER)"}         # both records, for the model to see
    from text2sql_calorvia.privacy import SENSITIVE
    for m in find_values("paie", "4330")["matches"]:               # salary amounts are never indexed
        assert m["column"] not in SENSITIVE.get(m["table"], set())
