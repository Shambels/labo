"""Variant (a) of O6: a PostgreSQL copy of the ERP (GESPRO), for auto-ontology, which can't read SQL Server.

Tooling for step 12, not part of the agent: the agent always queries the real ERP through the MCP server.
The copy is read from SQL Server as agent_ro and written to its own database (port 5436), with:

- table and column names in lower case (SQL Server is case-insensitive here, PostgreSQL folds unquoted names
  to lower case: the same names then work unquoted on both sides);
- the declared primary, unique and foreign keys (41 FKs: what Trino can't pass on);
- types mapped one to one (nvarchar(n) -> varchar(n), decimal(p,s) -> numeric(p,s), bit -> boolean...).

The ERP is a frozen snapshot (extracted 31/05/2026, replaced by Atlas the next day): a copy costs no freshness.
"""
import re

import psycopg
from psycopg import sql as pgsql

from text2sql_calorvia.catalog import describe
from text2sql_calorvia.sources import run_query

SCHEMA = "dbo"
_SIMPLE = {
    "int": "integer", "bigint": "bigint", "smallint": "smallint", "tinyint": "smallint", "bit": "boolean",
    "date": "date", "datetime": "timestamp", "datetime2": "timestamp", "smalldatetime": "timestamp",
    "time": "time", "float": "double precision", "real": "real", "money": "numeric(19,4)",
    "uniqueidentifier": "uuid", "ntext": "text", "text": "text",
}


def pg_type(sqlserver_type):
    """'nvarchar(60)' -> 'varchar(60)', 'decimal(14,2)' -> 'numeric(14,2)', 'nvarchar(max)' -> 'text'."""
    t = sqlserver_type.lower().strip()
    if t in _SIMPLE:
        return _SIMPLE[t]
    m = re.fullmatch(r"(n?varchar|n?char)\((max|\d+)\)", t)
    if m:
        kind, size = m.groups()
        if size == "max":
            return "text"
        return f"{'varchar' if kind.endswith('varchar') else 'char'}({size})"
    m = re.fullmatch(r"(decimal|numeric)\((\d+),(\d+)\)", t)
    if m:
        return f"numeric({m.group(2)},{m.group(3)})"
    raise ValueError(f"no PostgreSQL type for SQL Server type {sqlserver_type!r}")


def ddl(tables):
    """CREATE TABLE statements (columns + primary/unique keys), then the foreign keys once every table exists."""
    creates, foreign = [], []
    for t in tables:
        name = t["table_name"].lower()
        cols = [f"{c['column_name'].lower()} {pg_type(c['data_type'])}{'' if c['nullable'] else ' NOT NULL'}"
                for c in t["columns"]]
        keys = [k["definition"].lower() for k in t["keys"] if k["kind"] in ("primary", "unique")]
        creates.append(f"CREATE TABLE {SCHEMA}.{name} (\n  " + ",\n  ".join(cols + keys) + "\n)")
        for i, k in enumerate(k for k in t["keys"] if k["kind"] == "foreign"):
            definition = k["definition"].lower().replace("references ", f"REFERENCES {SCHEMA}.")
            foreign.append(f"ALTER TABLE {SCHEMA}.{name} ADD CONSTRAINT fk_{name}_{i + 1} {definition}")
    return creates, foreign


def copy(admin_url, ro_password):
    """(Re)build the copy: drop the schema, recreate the tables, copy every row, add the keys, grant read access."""
    tables = describe("erp")
    creates, foreign = ddl(tables)
    counts = {}
    with psycopg.connect(admin_url) as conn:
        conn.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
        conn.execute(f"CREATE SCHEMA {SCHEMA}")
        for statement in creates:
            conn.execute(statement)
        for t in tables:
            name = t["table_name"].lower()
            columns = [c["column_name"] for c in t["columns"]]
            _, rows = run_query("erp", "SELECT {} FROM [dbo].[{}]".format(
                ", ".join(f"[{c}]" for c in columns), t["table_name"]))
            target = pgsql.SQL("COPY {}.{} ({}) FROM STDIN").format(
                pgsql.Identifier(SCHEMA), pgsql.Identifier(name),
                pgsql.SQL(", ").join(pgsql.Identifier(c.lower()) for c in columns))
            with conn.cursor().copy(target) as cp:
                for row in rows:
                    cp.write_row(row)
            counts[name] = len(rows)
        for statement in foreign:
            conn.execute(statement)
        # The read-only account auto-ontology uses: the same three layers as agent_ro on the sources
        conn.execute(pgsql.SQL("DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ontology_ro') "
                               "THEN CREATE ROLE ontology_ro LOGIN; END IF; END $$"))
        conn.execute(pgsql.SQL("ALTER ROLE ontology_ro PASSWORD {}").format(pgsql.Literal(ro_password)))
        conn.execute("ALTER ROLE ontology_ro SET default_transaction_read_only = on")
        conn.execute("ALTER ROLE ontology_ro SET statement_timeout = '30s'")
        conn.execute(f"GRANT USAGE ON SCHEMA {SCHEMA} TO ontology_ro")
        conn.execute(f"GRANT SELECT ON ALL TABLES IN SCHEMA {SCHEMA} TO ontology_ro")
        conn.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
    return counts, len(foreign)
