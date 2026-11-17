"""The three Calorvia databases: what they are and how to query them, always as the read-only agent_ro account.

The only module that opens connections to the sources. There is no admin connection anywhere in the code.
"""
from dataclasses import dataclass
from importlib.resources import files

import psycopg
import pymssql

from text2sql_calorvia.config import settings


@dataclass(frozen=True)
class Source:
    name: str      # short id used everywhere: erp, compta, paie
    label: str
    engine: str    # sqlserver or postgres: picks the driver and the catalog queries
    dialect: str   # sqlglot dialect, for step 11's validation: tsql or postgres
    database: str
    port: int


SOURCES = {
    "erp": Source("erp", "ERP GesPro 7", "sqlserver", "tsql", "GESPRO", settings.erp_port),
    "compta": Source("compta", "Comptabilité", "postgres", "postgres", "compta", settings.compta_port),
    "paie": Source("paie", "Paie", "postgres", "postgres", "paie", settings.paie_port),
}


def load_sql(path):
    """Read a query from src/text2sql_calorvia/sql/ (path like 'catalog/tables_postgres')."""
    return files("text2sql_calorvia").joinpath("sql", f"{path}.sql").read_text(encoding="utf-8")


def connect(name, query_timeout_s=0):
    """Open a connection to a source as agent_ro. Both drivers use %s placeholders.

    query_timeout_s: SQL Server only, a client-side limit per query (0 = none); PostgreSQL gets its own
    in execution.py (statement_timeout + cancel).
    """
    source = SOURCES[name]
    if source.engine == "sqlserver":
        return pymssql.connect(
            server=settings.sources_host, port=source.port, database=source.database,
            user="agent_ro", password=settings.agent_ro_password,
            login_timeout=settings.connect_timeout_s, timeout=query_timeout_s, charset="UTF-8",
        )
    return psycopg.connect(
        host=settings.sources_host, port=source.port, dbname=source.database,
        user="agent_ro", password=settings.agent_ro_password,
        connect_timeout=settings.connect_timeout_s,
    )


def run_query(name, sql, params=None):
    """Run one query on a source and return (column names, rows). The transaction is always rolled back."""
    conn = connect(name)
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        columns = [d[0] for d in cur.description]
        rows = cur.fetchall()
        return columns, rows
    finally:
        conn.rollback()  # nothing to keep: a read never needs a commit
        conn.close()
