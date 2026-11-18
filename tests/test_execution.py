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
    assert not r["ok"] and "désigne une personne" in r["errors"][0]
    assert last_log()[0] == "refused"


@pytest.mark.parametrize("sql", [
    "SELECT row_to_json(p) FROM payslips p",
    "SELECT SUM(CASE WHEN p.employee_id = 'M10405' THEN p.net_amount END) FROM payslips p",
    "SELECT AVG(s.monthly_gross) FROM payslips p JOIN salary_history s ON s.employee_id = 'M10405'",
    "SELECT e.last_name FROM employees e JOIN payslips p ON p.employee_id = e.employee_id WHERE p.net_amount > 3000",
    "SELECT p.employee_id FROM payslips p GROUP BY p.employee_id HAVING SUM(p.net_amount) > 1000000000",
    "SELECT word FROM ts_stat('SELECT to_tsvector(net_amount::text) FROM payslips')",
    "SELECT schema_to_xml('public', true, false, '')",
])
def test_individual_pay_cannot_be_reached_by_a_detour(sources, sql):   # step 17, D65
    r = execute("paie", sql)
    assert not r["ok"] and "rows" not in r
    assert last_log()[0] == "refused"


SITE_AVERAGE = ("SELECT AVG(p.gross_amount) FROM payslips p JOIN contracts c ON c.contract_id = p.contract_id "
                "JOIN departments d ON d.department_code = c.department_code "
                "JOIN payroll_runs r ON r.run_id = p.run_id WHERE r.period_month = '{month}' AND r.run_type = 'MENSUEL' "
                "AND d.site_code = 'HRST'{more}")


def test_two_aggregates_cannot_differ_by_a_few_people(sources):   # step 24, D73
    site = next(row[0] for row in run_unvalidated("paie", "SELECT site_code, COUNT(*) FROM departments GROUP BY 1 "
                                                          "ORDER BY 2 DESC", max_rows=1)[1])
    base = SITE_AVERAGE.replace("HRST", site)
    full = base.format(month="2026-05-01", more="")
    assert execute("paie", full)["ok"]
    assert execute("paie", full)["ok"]                                       # the same query again changes nothing
    assert execute("paie", base.format(month="2026-04-01", more=""))["ok"]   # another month shares no rows
    _, rows, _ = run_unvalidated("paie", "SELECT MAX(p.gross_amount) FROM payslips p JOIN payroll_runs r USING (run_id) "
                                         "WHERE r.period_month = '2026-05-01'", max_rows=1)
    r = execute("paie", base.format(month="2026-05-01", more=f" AND p.gross_amount < {rows[0][0]}"))
    assert not r["ok"] and "ne diffère d'un calcul précédent" in r["errors"][0]
    assert last_log()[0] == "refused"


def test_every_cost_centre_has_enough_people_on_every_pay_run(sources):   # why accounting needs no rule of its own
    _, rows, _ = run_unvalidated("paie", "SELECT MIN(n) FROM (SELECT COUNT(DISTINCT employee_id) AS n FROM payslips "
                                         "GROUP BY run_id, cost_center_code) x", max_rows=1)
    assert rows[0][0] >= settings.min_group_size


def test_a_warning_comes_with_the_rows(sources):   # step 21: the query still runs
    r = execute("compta", "SELECT COUNT(*) FROM ecriture e JOIN ligne_ecriture l ON l.id_ecriture = e.id_ecriture "
                          "WHERE e.statut = 'BROUILLARD'")
    assert r["ok"] and r["rows"] == [[47]] and "COUNT(DISTINCT e.id_ecriture)" in r["warnings"][0]
    assert "warnings" not in execute("compta", "SELECT COUNT(*) FROM ecriture")


def test_sales_commission_tool(sources):
    from text2sql_calorvia.commission import get_sales_commission
    r = get_sales_commission("10405", "2026-03")
    assert r["ok"] and r["payroll_employee_id"] == "M10405"
    line = r["commission_lines"][0]
    assert (line["base_sales"], line["rate_percent"], line["amount"]) == (731384.61, 0.1, 731.38)
    refused = get_sales_commission("M10230", "2026-03")   # not a salesperson: no individual amount
    assert not refused["ok"] and "pas un commercial" in refused["errors"][0]
    assert not get_sales_commission("10405'; DROP TABLE x --", "2026-03")["ok"]
