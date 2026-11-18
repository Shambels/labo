"""Layer 2 of the read-only protection: check a query before it runs, with sqlglot in the source's dialect.

Refuses anything but one read (SELECT, UNION...), with errors written for the model so it can correct itself.
Tables and columns must exist and be readable by agent_ro; a row limit is added if the query has none; on the
payroll source, the privacy rule is checked (privacy.py).
"""
import difflib
import re
from dataclasses import dataclass, field
from functools import cache

import sqlglot
from sqlglot import exp
from sqlglot.errors import OptimizeError, ParseError
from sqlglot.optimizer.qualify import qualify

from text2sql_calorvia import joins, privacy
from text2sql_calorvia.catalog import describe
from text2sql_calorvia.config import settings
from text2sql_calorvia.sources import SOURCES

# Statements and clauses that write, change the session or run code. Searched in the whole tree:
# PostgreSQL accepts "WITH d AS (DELETE ... RETURNING *) SELECT ...", which parses as a SELECT.
FORBIDDEN = {
    exp.Insert: "INSERT", exp.Update: "UPDATE", exp.Delete: "DELETE", exp.Merge: "MERGE",
    exp.Create: "CREATE", exp.Drop: "DROP", exp.Alter: "ALTER", exp.TruncateTable: "TRUNCATE",
    exp.Into: "SELECT INTO", exp.Lock: "FOR UPDATE / FOR SHARE (verrous)", exp.Copy: "COPY",
    exp.Set: "SET", exp.Execute: "EXEC", exp.Command: "commande", exp.Transaction: "transaction",
    exp.Commit: "COMMIT", exp.Rollback: "ROLLBACK", exp.Grant: "GRANT", exp.Revoke: "REVOKE", exp.Use: "USE",
    exp.Analyze: "ANALYZE", exp.Kill: "KILL", exp.Pragma: "PRAGMA", exp.LoadData: "LOAD DATA",
}
# Functions that read files, reach other servers, sleep, change settings, or run SQL given as text
FORBIDDEN_FUNCTIONS = re.compile(
    r"^(pg_|lo_|dblink|xp_|sp_|fn_|open(rowset|datasource|query|xml)|set_config|current_setting|"
    r"query_to_xml|table_to_xml|cursor_to_xml|schema_to_xml|database_to_xml|ts_stat|ts_rewrite|nextval|setval|txid_|waitfor|bulk|sleep)", re.I)


@dataclass
class Validation:
    ok: bool
    errors: list = field(default_factory=list)
    sql: str | None = None             # what will run: the query with its row limit
    tables: list = field(default_factory=list)
    privacy_check: str | None = None   # payroll: the group-size query to run first (privacy.py)
    warnings: list = field(default_factory=list)   # valid, but probably not what was meant (joins.py)

    def as_dict(self):
        return {"ok": self.ok, "errors": self.errors, "sql": self.sql, "tables": self.tables,
                "privacy_rule_applies": self.privacy_check is not None, "warnings": self.warnings}


@cache
def schema(source):
    """{table: {column: type}} of the readable columns, and {table: [hidden columns]}, from the catalog."""
    readable, hidden = {}, {}
    for t in describe(source):
        name = t["table_name"]
        readable[name] = {c["column_name"]: c["data_type"] for c in t["columns"] if c["readable"]}
        hidden[name] = [c["column_name"] for c in t["columns"] if not c["readable"]]
    return readable, hidden


@cache
def foreign_keys(source):
    """{table: [(columns, referenced table, referenced columns)]}, lower case, from the catalog."""
    keys = {}
    for t in describe(source):
        parsed = [joins.parse_foreign_key(k["definition"]) for k in t["keys"] if k["kind"] == "foreign"]
        keys[t["table_name"].lower()] = [k for k in parsed if k]
    return keys


def _default_schema(source):
    return "dbo" if SOURCES[source].engine == "sqlserver" else "public"


def _parse(source, sql):
    """One statement, parsed in the source's dialect, or a readable error."""
    dialect = SOURCES[source].dialect
    try:
        statements = [s for s in sqlglot.parse(sql.strip().rstrip(";"), read=dialect) if s is not None]
    except ParseError as error:
        first = error.errors[0] if error.errors else {}
        where = f" (ligne {first.get('line')}, colonne {first.get('col')})" if first else ""
        return None, [f"Erreur de syntaxe {dialect}{where} : {first.get('description', str(error))}. "
                      f"Vérifiez la syntaxe du dialecte {dialect}."]
    if len(statements) != 1:
        return None, [f"Une seule instruction par requête ({len(statements)} reçues)."]
    return statements[0], []


def _check_read_only(tree):
    errors = []
    if not isinstance(tree, exp.Query):
        errors.append(f"Seules les lectures (SELECT) sont permises : {tree.key.upper()} refusé.")
    for node_type, label in FORBIDDEN.items():
        if tree.find(node_type) is not None:
            errors.append(f"Interdit : {label}. Le serveur est en lecture seule.")
    if any(not select.expressions for select in tree.find_all(exp.Select)):
        errors.append("SELECT sans colonne : indiquez les colonnes ou expressions à lire.")
    for func in tree.find_all(exp.Func):
        name = func.name if isinstance(func, exp.Anonymous) else func.sql_name()
        if name and FORBIDDEN_FUNCTIONS.match(name):
            errors.append(f"Fonction interdite : {name}.")
    return sorted(set(errors), key=errors.index)


def _check_tables(source, tree):
    """Every table exists in this source (CTE names aside). Suggest close names, or the source that has it."""
    readable, _ = schema(source)
    by_lower = {t.lower(): t for t in readable}
    ctes = {cte.alias_or_name.lower() for cte in tree.find_all(exp.CTE)}
    errors, used = [], []
    for table in tree.find_all(exp.Table):
        name = table.name
        if not name or name.lower() in ctes:
            continue
        if table.db and table.db.lower() != _default_schema(source):
            errors.append(f"Schéma inconnu : {table.db}. Utilisez {_default_schema(source)}.")
        if name.lower() in by_lower:
            used.append(by_lower[name.lower()])
            continue
        hint = difflib.get_close_matches(name.lower(), by_lower, n=3, cutoff=0.6)
        elsewhere = [s for s in SOURCES if s != source and name.lower() in {t.lower() for t in schema(s)[0]}]
        message = f"Table inconnue dans {source} : {name}."
        if elsewhere:
            message += f" Elle est dans la source {elsewhere[0]} : pas de jointure entre sources, interrogez-les séparément."
        elif hint:
            message += " Tables proches : " + ", ".join(by_lower[h] for h in hint) + "."
        errors.append(message)
    return errors, sorted(set(used))


def _qualify(source, tree, tables):
    """Resolve every column against the readable schema; a readable message when one doesn't exist."""
    readable, hidden = schema(source)
    mapping = {_default_schema(source): {t: cols for t, cols in readable.items()}}
    try:
        return qualify(tree.copy(), schema=mapping, dialect=SOURCES[source].dialect,
                       db=_default_schema(source), validate_qualify_columns=True, identify=False), []
    except OptimizeError as error:
        text = str(error)
        match = re.search(r"Unknown column: (\w+)|Column '(\w+)' could not be resolved", text)
        column = next((g for g in (match.groups() if match else ()) if g), None)
        if column:
            # qualify lower-cases names: give the model back its own spelling
            column = next((c.name for c in tree.find_all(exp.Column) if c.name.lower() == column.lower()), column)
            for t in tables:
                if column.lower() in {h.lower() for h in hidden.get(t, [])}:
                    return None, [f"Colonne non lisible : {t}.{column} (donnée personnelle, inaccessible au compte "
                                  "de l'agent). Nommez les colonnes au lieu de SELECT *."]
            known = {c.lower(): f"{t}.{c}" for t in tables for c in readable[t]}
            hint = difflib.get_close_matches(column.lower(), known, n=3, cutoff=0.6)
            message = f"Colonne inconnue : {column}."
            if hint:
                message += " Colonnes proches : " + ", ".join(known[h] for h in hint) + "."
            message += " Lisez la fiche de la table (get_table_card)."
            return None, [message]
        if "*" in text or "star" in text.lower():
            return None, ["SELECT * impossible ici : nommez les colonnes (certaines ne sont pas lisibles)."]
        return None, [f"Requête non résolue : {text}. Lisez la fiche des tables utilisées (get_table_card)."]


def _with_limit(source, sql, tree, max_rows):
    """The query to run: the model's own text, plus a row limit when the outer query has none.

    The text is never regenerated by sqlglot: its output can differ from what the model wrote (casts added,
    functions renamed), and what runs must be what the CFO reads. PostgreSQL: LIMIT appended (valid after any
    top-level SELECT, UNION or ORDER BY). SQL Server: SET ROWCOUNT in the execution session (execution.py),
    since TOP can't be added to a text without parsing it. One extra row tells truncation.
    """
    sql = sql.strip().rstrip(";").rstrip()
    if SOURCES[source].engine == "postgres" and tree.args.get("limit") is None and tree.args.get("fetch") is None:
        return f"{sql}\nLIMIT {max_rows + 1}"
    return sql


def validate(source, sql, max_rows=None):
    if source not in SOURCES:
        return Validation(False, [f"Source inconnue : {source}. Sources : {', '.join(SOURCES)}."])
    if not sql or not sql.strip():
        return Validation(False, ["Requête vide."])
    max_rows = max_rows or settings.max_rows
    dialect = SOURCES[source].dialect
    tree, errors = _parse(source, sql)
    if errors:
        return Validation(False, errors)
    errors = _check_read_only(tree)
    if errors:
        return Validation(False, errors)
    errors, tables = _check_tables(source, tree)
    if errors:
        return Validation(False, errors, tables=tables)
    _, hidden = schema(source)
    # COUNT(*) reads no column: only a star that selects columns (SELECT *, t.*) can reach the hidden ones.
    # Found by step 14's evaluation: "SELECT exit_reason, COUNT(*) FROM employees" was refused as a SELECT *
    star = any(not isinstance(s.parent, exp.Count) for s in tree.find_all(exp.Star))
    if star and any(hidden.get(t) for t in tables):
        partly = [t for t in tables if hidden.get(t)]
        return Validation(False, [f"SELECT * refusé sur {', '.join(partly)} : certaines colonnes sont des données "
                                  "personnelles non lisibles. Nommez les colonnes (get_table_card)."], tables=tables)
    qualified, errors = _qualify(source, tree, tables)
    if errors:
        return Validation(False, errors, tables=tables)
    privacy_check = None
    if source == "paie":
        try:
            if privacy.check(qualified):
                privacy_check = privacy.group_size_query(qualified, dialect)
        except privacy.PrivacyError as error:
            return Validation(False, [str(error)], tables=tables)
    return Validation(True, [], _with_limit(source, sql, tree, max_rows), tables, privacy_check,
                      joins.fan_out_warnings(qualified, foreign_keys(source)))
