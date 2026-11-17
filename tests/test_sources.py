"""Integration tests on the three source databases, as agent_ro: layer 1 of the read-only protection.

Every write below is sent straight to the database, without any validation in front: this is what still holds
if step 11's sqlglot check is ever bypassed. Skipped when the sources aren't running
(docker compose -f enonces/calorvia_t2sql/sources_calorvia/docker/docker-compose.yml --env-file .env up -d).
"""
import psycopg
import pymssql
import pytest

from text2sql_calorvia.sources import SOURCES, connect, run_query

DB_ERRORS = (psycopg.Error, pymssql.Error)


def _reachable(name):
    try:
        connect(name).close()
        return True
    except DB_ERRORS:
        return False


@pytest.fixture(params=list(SOURCES))
def source(request):
    if not _reachable(request.param):
        pytest.skip(f"source {request.param} is not running")
    return request.param


def needs(name):
    return pytest.mark.skipif(not _reachable(name), reason=f"source {name} is not running")


def refused(name, *statements, autocommit=False):
    """Run statements in one session; return the error of the first one refused, or fail if all pass."""
    conn = connect(name)
    try:
        if autocommit:
            conn.autocommit(True) if name == "erp" else setattr(conn, "autocommit", True)
        cur = conn.cursor()
        for sql in statements:
            cur.execute(sql)
    except DB_ERRORS as error:
        return str(error)
    finally:
        try:
            conn.rollback()
        except DB_ERRORS:
            pass
        conn.close()
    pytest.fail(f"{name} accepted: {statements}")


# The row counts given by the restore guide: the restore is complete
EXPECTED_COUNTS = {"erp": ("VTE_FACT", 10185), "compta": ("ecriture", 20562), "paie": ("payslips", 7298)}


def test_restored_and_readable(source):
    table, count = EXPECTED_COUNTS[source]
    _, rows = run_query(source, f"SELECT COUNT(*) FROM {table}")
    assert rows[0][0] == count


@needs("erp")
@pytest.mark.parametrize("sql", [
    "DELETE FROM PAR_CODE WHERE 1 = 0",
    "UPDATE CLI_CLIENT SET CLI_NOM = CLI_NOM WHERE 1 = 0",
    "INSERT INTO SOC_SITE (SIT_CODE) SELECT 'X' WHERE 1 = 0",
    "SELECT TOP 1 * INTO dbo.AGENT_COPY FROM PAR_CODE",  # SELECT INTO a real table = CREATE TABLE
    "CREATE TABLE dbo.AGENT_T (a int)",
    "DROP TABLE PAR_CODE",
    "EXEC xp_cmdshell 'whoami'",
])
def test_erp_refuses_writes(sql):
    assert "permission" in refused("erp", sql)


@needs("erp")
def test_erp_account_is_reader_only():
    _, rows = run_query("erp", "SELECT IS_ROLEMEMBER('db_datareader'), IS_ROLEMEMBER('db_datawriter'), "
                               "IS_ROLEMEMBER('db_owner'), IS_SRVROLEMEMBER('sysadmin')")
    assert rows[0] == (1, 0, 0, 0)


@needs("erp")
def test_erp_temp_table_is_allowed():
    """Known gap of layer 1: any login may write to tempdb. Harmless to GESPRO, but step 11's validation
    must refuse SELECT INTO all the same."""
    conn = connect("erp")
    try:
        cur = conn.cursor()
        cur.execute("SELECT TOP 1 * INTO #agent_tmp FROM PAR_CODE")
        cur.execute("SELECT COUNT(*) FROM #agent_tmp")
        assert cur.fetchone()[0] == 1
    finally:
        conn.close()


@pytest.mark.parametrize("name, sql", [
    ("compta", "DELETE FROM budget WHERE false"),
    ("compta", "UPDATE ecriture SET libelle = libelle WHERE false"),
    ("paie", "UPDATE payslips SET net_amount = net_amount WHERE false"),
    ("paie", "TRUNCATE timesheets"),
])
def test_postgres_refuses_writes_even_without_the_read_only_default(name, sql):
    """default_transaction_read_only is one SET away (the statement warns): the grants must hold on their own."""
    if not _reachable(name):
        pytest.skip(f"source {name} is not running")
    error = refused(name, "SET default_transaction_read_only = off", sql, autocommit=True)
    assert "permission denied" in error


@pytest.mark.parametrize("name", ["compta", "paie"])
def test_postgres_session_defaults(name):
    if not _reachable(name):
        pytest.skip(f"source {name} is not running")
    _, rows = run_query(name, "SELECT current_setting('default_transaction_read_only'), "
                              "current_setting('statement_timeout')")
    assert rows[0] == ("on", "30s")
    assert "read-only transaction" in refused(name, "DELETE FROM pg_class WHERE false")
    assert "permission denied" in refused(name, "COPY (SELECT 1) TO '/tmp/agent_copy'")


@needs("paie")
@pytest.mark.parametrize("column", ["national_number", "iban", "street_address"])
def test_payroll_personal_columns_are_hidden(column):
    assert "permission denied" in refused("paie", f"SELECT {column} FROM employees")


@needs("paie")
def test_payroll_star_is_refused_but_named_columns_are_readable():
    assert "permission denied" in refused("paie", "SELECT * FROM employees")
    _, rows = run_query("paie", "SELECT employee_id, last_name FROM employees LIMIT 1")
    assert len(rows) == 1
