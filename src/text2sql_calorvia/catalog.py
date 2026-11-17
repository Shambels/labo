"""What a source contains: tables, columns, keys, row counts. Read from the database catalog, never guessed.

Step 11's `list_tables` and `get_table_card` tools are built on these functions.
"""
from text2sql_calorvia.sources import SOURCES, connect, load_sql


def _fetch(conn, sql):
    cur = conn.cursor()
    cur.execute(sql)
    columns = [d[0] for d in cur.description]
    return [dict(zip(columns, row)) for row in cur.fetchall()]


def quote(engine, table_schema, table_name):
    """A safely quoted table name in the engine's syntax: [dbo].[VTE_FACT] or "public"."ecriture"."""
    if engine == "sqlserver":
        return "[{}].[{}]".format(table_schema.replace("]", "]]"), table_name.replace("]", "]]"))
    return '"{}"."{}"'.format(table_schema.replace('"', '""'), table_name.replace('"', '""'))


def describe(name):
    """Every table of a source with its comment, row count, columns and keys."""
    engine = SOURCES[name].engine
    conn = connect(name)
    try:
        tables = _fetch(conn, load_sql(f"catalog/tables_{engine}"))
        columns = _fetch(conn, load_sql(f"catalog/columns_{engine}"))
        keys = _fetch(conn, load_sql(f"catalog/keys_{engine}"))
        for table in tables:
            ident = (table["table_schema"], table["table_name"])
            table["columns"] = [c for c in columns if (c["table_schema"], c["table_name"]) == ident]
            table["keys"] = [k for k in keys if (k["table_schema"], k["table_name"]) == ident]
            # COUNT(*) needs SELECT on at least one column: true even for payroll's partly hidden employees table
            cur = conn.cursor()
            cur.execute(f"SELECT COUNT(*) FROM {quote(engine, *ident)}")
            table["rows"] = cur.fetchone()[0]
        return tables
    finally:
        conn.rollback()
        conn.close()
