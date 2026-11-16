import json
import sqlite3
from datetime import date

import pytest
from openpyxl import Workbook

from rag_calorvia.config import settings
from rag_calorvia.rag import tables
from rag_calorvia.rag.tables import build_store, call_tool, describe_table, find_tables, run_sql


@pytest.fixture
def store(tmp_path, monkeypatch):
    wb = Workbook()
    ws = wb.active
    ws.title = "Ventes par région"
    ws.append(["Chiffre d'affaires par région (k€)"])
    ws.append(["Région", "CA du mois", "Part"])
    for region, revenue, share in [("Wallonie", 4555, 0.32), ("Flandre", 4568, 0.33), ("Total", 13900, 1.0)]:
        ws.append([region, revenue, share])
    (tmp_path / "01_Finance").mkdir()
    wb.save(tmp_path / "01_Finance" / "Reporting 2025-10.xlsx")
    monkeypatch.setattr(settings, "corpus_path", tmp_path)
    document = {"path": "01_Finance/Reporting 2025-10.xlsx", "doc_date": date(2025, 10, 1), "status": None, "version": None}
    return build_store([document])


def test_find_tables_by_keywords(store):
    [entry] = find_tables(store, "chiffre d'affaires par région octobre")
    assert entry["table"] == "t001" and entry["sheet"] == "Ventes par région" and entry["rows"] == 3
    assert entry["columns"] == ["Région", "CA du mois", "Part"]


def test_numbers_are_real_columns(store):
    columns = {c["name"]: c["type"] for c in describe_table(store, "t001")["columns"]}
    assert columns == {"Région": "TEXT", "CA du mois": "REAL", "Part": "REAL"}


def test_run_sql_computes(store):
    result = run_sql(store, """SELECT "Région" FROM t001 WHERE "Région" <> 'Total' ORDER BY "CA du mois" DESC LIMIT 1""")
    assert result["rows"] == [("Flandre",)]


def test_errors_come_back_as_text(store):
    assert "no such column" in run_sql(store, 'SELECT "Chiffre" FROM t001')["error"]
    assert "unknown table" in describe_table(store, "users; DROP TABLE t001")["error"]


@pytest.mark.parametrize("sql", ["DELETE FROM t001", "SELECT 1; DROP TABLE t001", "UPDATE t001 SET Part = 0"])
def test_only_one_select_is_accepted(store, sql):
    assert run_sql(store, sql) == {"error": "only one SELECT statement is allowed"}


def test_sqlite_itself_refuses_writes_even_if_the_check_is_bypassed(store):
    with pytest.raises(sqlite3.OperationalError, match="readonly|read-only|query_only|attempt to write"):
        store.execute("DELETE FROM t001")


def test_results_are_capped(store, monkeypatch):
    monkeypatch.setattr(tables, "MAX_ROWS", 2)
    result = run_sql(store, "SELECT * FROM t001")
    assert len(result["rows"]) == 2 and result["truncated"]


def test_call_tool_returns_json(store):
    assert json.loads(call_tool(store, "run_sql", '{"sql": "SELECT COUNT(*) FROM t001"}'))["rows"] == [[3]]
    assert "error" in json.loads(call_tool(store, "nope", "{}"))
