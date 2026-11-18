from functools import cache

import psycopg
import pymssql
import pytest


@cache
def _up(name):
    from text2sql_calorvia.sources import connect
    try:
        connect(name).close()
        return True
    except (psycopg.Error, pymssql.Error):
        return False


@cache
def _log_up():
    try:
        from text2sql_calorvia.execution import create_log_table
        create_log_table()
        return True
    except psycopg.Error:
        return False


@pytest.fixture
def sources():
    """Skip unless the three sources and the logging PostgreSQL are running."""
    down = [n for n in ("erp", "compta", "paie") if not _up(n)]
    if down:
        pytest.skip(f"sources not running: {', '.join(down)}")
    if not _log_up():
        pytest.skip("the logging PostgreSQL (5432) is not running")


@pytest.fixture(autouse=True)
def forget_payroll_queries():
    """The server's memory of payroll aggregates (overlap.py) must not carry from one test to the next."""
    from text2sql_calorvia.overlap import guard
    guard.clear()
