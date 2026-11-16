"""Computing on workbooks (step 6b): every table of the indexed workbooks in an in-memory SQLite database, and
three tools the LLM can call to find a table, read its columns and run a SELECT.

A RAG hands the LLM five chunks and lets it compare or add numbers in its head: it fails as soon as the rows
are spread over several chunks or files. Here the LLM writes the query, SQLite computes.
"""
import json
import logging
import re
import sqlite3
from functools import cache

from rag_calorvia import db
from rag_calorvia.config import settings
from rag_calorvia.etl.excel import Table, read_workbook

logger = logging.getLogger(__name__)

MAX_ROWS = 50        # rows returned by run_sql: enough to read, not enough to flood the context
FIND_LIMIT = 8       # tables returned by find_tables


def table_name(index):
    return f"t{index:03d}"


def column_type(values):
    """SQLite type of a column: REAL when every non-empty value is a number, else TEXT."""
    present = [v for v in values if v is not None]
    return "REAL" if present and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in present) else "TEXT"


def column_names(header):
    """Header cells as column names; empty or repeated ones get a position-based name."""
    names, seen = [], set()
    for i, header_cell in enumerate(header, 1):
        name = header_cell.strip() or f"col{i}"
        if name in seen:
            name = f"{name} ({i})"
        seen.add(name)
        names.append(name)
    return names


def quote(identifier):
    return '"' + identifier.replace('"', '""') + '"'


def build_store(documents):
    """An in-memory SQLite database: one table per workbook table, plus a `catalog` describing them all.

    documents: registry rows (only indexed, non-excluded workbooks: personal data never reaches the tools).
    """
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    # By default SQLite reads "Chiffre" as the string 'Chiffre' when no column has that name: a misspelled
    # column would silently give a wrong result. Off: an unknown double-quoted name is an error the LLM can fix.
    conn.setconfig(sqlite3.SQLITE_DBCONFIG_DQS_DML, False)
    conn.setconfig(sqlite3.SQLITE_DBCONFIG_DQS_DDL, False)
    conn.execute("""CREATE TABLE catalog (name TEXT, document TEXT, sheet TEXT, title TEXT, columns TEXT,
                    n_rows INTEGER, doc_date TEXT, status TEXT, version TEXT)""")
    index = 0
    for document in documents:
        for block in read_workbook(settings.corpus_path / document["path"]):
            if not isinstance(block, Table) or not block.values:
                continue
            index += 1
            name, columns = table_name(index), column_names(block.header)
            types = [column_type([row[i] if i < len(row) else None for row in block.values]) for i in range(len(columns))]
            conn.execute(f"CREATE TABLE {name} (" + ", ".join(f"{quote(c)} {t}" for c, t in zip(columns, types)) + ")")
            conn.executemany(f"INSERT INTO {name} VALUES (" + ", ".join("?" * len(columns)) + ")",
                             [(row + [None] * len(columns))[:len(columns)] for row in block.values])
            conn.execute("INSERT INTO catalog VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (
                name, document["path"], block.sheet, block.title, json.dumps(columns, ensure_ascii=False),
                len(block.values), document["doc_date"].isoformat() if document["doc_date"] else None,
                document["status"], document["version"]))
    conn.commit()
    conn.execute("PRAGMA query_only = ON")  # from here on, any write is refused by SQLite itself
    logger.info("table store: %d tables", index)
    return conn


@cache
def get_store():
    """The store of the indexed workbooks, built once per process."""
    with db.connect(read_only=True) as conn:
        documents = [d for d in db.load_indexable_documents(conn) if d["format"] == "xlsx"]
    return build_store(documents)


def words(text):
    return {w for w in re.findall(r"\w+", text.casefold()) if len(w) > 2}


def find_tables(store, query):
    """The catalog entries whose document, sheet, title or columns share the most words with the query."""
    wanted = words(query)
    rows = store.execute("SELECT name, document, sheet, title, columns, n_rows, doc_date, status, version FROM catalog")
    scored = []
    for name, document, sheet, title, columns, n_rows, doc_date, status, version in rows:
        haystack = words(" ".join([document, sheet, title or "", " ".join(json.loads(columns))]))
        score = len(wanted & haystack)
        if score:
            scored.append((score, {"table": name, "document": document, "sheet": sheet, "title": title,
                                   "columns": json.loads(columns), "rows": n_rows, "date": doc_date,
                                   "status": status, "version": version}))
    scored.sort(key=lambda item: -item[0])
    return [entry for _, entry in scored[:FIND_LIMIT]]


def describe_table(store, name):
    """Columns with their SQLite type, and three sample rows."""
    if not re.fullmatch(r"t\d{3}", name or ""):
        return {"error": f"unknown table {name!r}: use a name returned by find_tables"}
    info = store.execute(f"PRAGMA table_info({name})").fetchall()
    if not info:
        return {"error": f"unknown table {name!r}"}
    sample = store.execute(f"SELECT * FROM {name} LIMIT 3").fetchall()
    return {"table": name, "columns": [{"name": c[1], "type": c[2]} for c in info], "sample_rows": sample}


def run_sql(store, sql):
    """Run one SELECT. Errors come back as text, so the LLM can correct its query."""
    statement = sql.strip().rstrip(";")
    if not re.match(r"(?is)^\s*(select|with)\b", statement) or ";" in statement:
        return {"error": "only one SELECT statement is allowed"}
    try:
        cursor = store.execute(statement)
        rows = cursor.fetchmany(MAX_ROWS + 1)
    except sqlite3.Error as error:
        return {"error": str(error)}
    columns = [d[0] for d in cursor.description]
    return {"columns": columns, "rows": rows[:MAX_ROWS], "truncated": len(rows) > MAX_ROWS}


TOOLS = [
    {"type": "function", "function": {
        "name": "find_tables",
        "description": "Cherche les tableaux des classeurs Excel de Calorvia par mots-clés (fichier, onglet, titre, "
                       "colonnes). Renvoie leur nom SQL, leur document, leur date et leur statut (projet, copie...).",
        "parameters": {"type": "object", "properties": {"keywords": {"type": "string"}}, "required": ["keywords"]}}},
    {"type": "function", "function": {
        "name": "describe_table",
        "description": "Colonnes (avec leur type) et trois lignes d'exemple d'un tableau trouvé par find_tables.",
        "parameters": {"type": "object", "properties": {"table": {"type": "string"}}, "required": ["table"]}}},
    {"type": "function", "function": {
        "name": "run_sql",
        "description": "Exécute une requête SQLite SELECT sur les tableaux (noms de colonnes entre guillemets doubles). "
                       "Les pourcentages sont stockés en fraction (0.324 = 32,4 %). Au plus 50 lignes.",
        "parameters": {"type": "object", "properties": {"sql": {"type": "string"}}, "required": ["sql"]}}},
]


def call_tool(store, name, arguments):
    """Dispatch one tool call; the result is JSON text for the LLM."""
    try:
        args = json.loads(arguments or "{}")
    except json.JSONDecodeError:
        return json.dumps({"error": "arguments are not valid JSON"})
    if name == "find_tables":
        result = find_tables(store, args.get("keywords", ""))
    elif name == "describe_table":
        result = describe_table(store, args.get("table", ""))
    elif name == "run_sql":
        result = run_sql(store, args.get("sql", ""))
    else:
        result = {"error": f"unknown tool {name!r}"}
    return json.dumps(result, ensure_ascii=False, default=str)
