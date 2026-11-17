"""Layers 3 and 4: execution (read-only transaction, timeout, row limit) and logging.

The `run_unvalidated` tests send writes past the validation layer, straight to execution: the statement asks
for proof that a write is refused "even if validation is bypassed".
"""
import time

import psycopg
import pymssql
import pytest

from text2sql_calorvia import execution
from text2sql_calorvia.config import settings
from text2sql_calorvia.execution import QueryTimeout, execute, run_unvalidated

DB_ERRORS = (psycopg.Error, pymssql.Error)


def last_log(log_id=None):
    with execution.log_connect() as conn:
        if log_id:
            return conn.execute("SELECT status, error, row_count, truncated, sql_executed FROM t2sql_query_log "
                                "WHERE id = %s", (log_id,)).fetchone()
        return conn.execute("SELECT status, error, row_count, truncated, sql_executed, tool, question "
                            "FROM t2sql_query_log ORDER BY id DESC LIMIT 1").fetchone()


# --- Layer 3 alone: validation bypassed -------------------------------------------------------------

@pytest.mark.parametrize("source, sql", [
    ("compta", "DELETE FROM budget WHERE false"),
    ("compta", "UPDATE ecriture SET libelle = libelle WHERE false"),
    ("paie", "TRUNCATE timesheets"),
    ("paie", "CREATE TEMP TABLE t AS SELECT 1 AS a"),   # allowed by the role once its default is off, not here
    ("erp", "DELETE FROM PAR_CODE WHERE 1 = 0"),
    ("erp", "UPDATE CLI_CLIENT SET CLI_NOM = CLI_NOM WHERE 1 = 0"),
    ("erp", "DROP TABLE PAR_CODE"),
])
def test_writes_fail_even_without_validation(sources, source, sql):
    with pytest.raises(DB_ERRORS):
        run_unvalidated(source, sql)


def test_postgres_transaction_stays_read_only_even_if_the_query_tries_to_change_it(sources):
    """BEGIN READ ONLY is set by the execution layer; SET inside the query can't undo it after the first query."""
    with pytest.raises(psycopg.Error, match="read-only|READ WRITE|permission denied"):
        run_unvalidated("compta", "SET default_transaction_read_only = off; "
                                  "SET TRANSACTION READ WRITE; DELETE FROM budget WHERE false")


def test_sql_server_temp_table_does_not_outlive_the_call(sources):
    """The known gap of layer 1 (tempdb): validation refuses it; if bypassed, it is rolled back and gone."""
    _, rows, _ = run_unvalidated("erp", "SELECT TOP 1 * INTO #agent_tmp FROM PAR_CODE; SELECT COUNT(*) FROM #agent_tmp")
    assert rows == [[1]]
    with pytest.raises(pymssql.Error, match="agent_tmp"):
        run_unvalidated("erp", "SELECT COUNT(*) FROM #agent_tmp")


@pytest.mark.parametrize("source, sql", [
    ("compta", "SELECT pg_sleep(30)"),
    ("erp", "SELECT COUNT(*) FROM STK_MVT a CROSS JOIN STK_MVT b CROSS JOIN STK_MVT c"),
])
def test_client_side_timeout_on_both_engines(sources, source, sql):
    start = time.perf_counter()
    with pytest.raises(QueryTimeout):
        run_unvalidated(source, sql, timeout_s=2)
    assert time.perf_counter() - start < 6


@pytest.mark.parametrize("source, sql", [
    ("erp", "SELECT CLI_NOM FROM CLI_CLIENT"),
    ("compta", "SELECT libelle FROM ecriture"),
])
def test_row_limit_and_truncation_flag(sources, source, sql):
    columns, rows, truncated = run_unvalidated(source, sql, max_rows=7)
    assert len(rows) == 7 and truncated


# --- The whole path: validate, privacy, run, log ----------------------------------------------------

def test_execute_returns_rows_and_logs(sources):
    r = execute("erp", "SELECT TOP 3 CLI_CODE FROM CLI_CLIENT ORDER BY CLI_CODE", question="test: trois clients")
    assert r["ok"] and r["rows"] == [["CL00001"], ["CL00002"], ["CL00003"]] and not r["truncated"]
    status, error, row_count, truncated, sql_executed = last_log(r["log_id"])
    assert (status, error, row_count, truncated) == ("ok", None, 3, False)


def test_execute_refusal_is_logged(sources):
    r = execute("compta", "DELETE FROM budget", question="test: supprime le budget")
    assert not r["ok"]
    status, error, *_, tool, question = last_log()
    assert status == "refused" and "DELETE" in error and question == "test: supprime le budget"


def test_execution_error_is_returned_and_logged(sources):
    r = execute("compta", "SELECT 1 / 0 FROM plan_comptable")
    assert not r["ok"] and "division by zero" in r["errors"][0]
    assert last_log()[0] == "error"


def test_no_log_no_query(sources, monkeypatch):
    """Traceability is not optional: if the log can't be written, nothing runs."""
    monkeypatch.setattr(settings, "postgres_url", "postgresql://nobody:wrong@localhost:5432/nothing")
    monkeypatch.setattr(execution, "run_unvalidated", lambda *a, **k: pytest.fail("the query ran without a log"))
    with pytest.raises(psycopg.Error):
        execute("erp", "SELECT TOP 1 CLI_NOM FROM CLI_CLIENT")


# --- The payroll rule, end to end ------------------------------------------------------------------

AVG_PER_SITE = ("SELECT d.site_code, ROUND(AVG(p.gross_amount), 2) AS brut_moyen FROM payslips p "
                "JOIN contracts c ON c.contract_id = p.contract_id "
                "JOIN departments d ON d.department_code = c.department_code GROUP BY d.site_code")


def test_payroll_aggregate_over_sites_is_shown(sources):
    r = execute("paie", AVG_PER_SITE)
    assert r["ok"] and len(r["rows"]) == 4


def test_payroll_aggregate_over_one_person_is_refused(sources):
    r = execute("paie", "SELECT AVG(gross_amount) FROM payslips WHERE employee_id = 'M10405'")
    assert not r["ok"] and "1 personne" in r["errors"][0]
    assert last_log()[0] == "refused"


def test_sales_commission_tool(sources):
    from text2sql_calorvia.commission import get_sales_commission
    r = get_sales_commission("10405", "2026-03")
    assert r["ok"] and r["payroll_employee_id"] == "M10405"
    line = r["commission_lines"][0]
    assert (line["base_sales"], line["rate_percent"], line["amount"]) == (731384.61, 0.1, 731.38)
    refused = get_sales_commission("M10230", "2026-03")   # not a salesperson: no individual amount
    assert not refused["ok"] and "pas un commercial" in refused["errors"][0]
    assert not get_sales_commission("10405'; DROP TABLE x --", "2026-03")["ok"]
