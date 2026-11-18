"""Layers 3 and 4 of the read-only protection: run a validated query, and log it.

- Layer 3, execution: a read-only transaction (PostgreSQL; SQL Server has no such mode, its grants do the work),
  always rolled back; a client-side timeout on every engine; at most max_rows rows returned, with a flag.
- Layer 4, traceability: a log row is written *before* the query runs and completed after. If it can't be
  written, the query doesn't run.

`run_unvalidated` is the bare layer 3: the tests send writes through it to show they fail even when
validation is bypassed. Only `execute` (validation first) and the commission tool use it.
"""
import datetime as dt
import threading
import time
from decimal import Decimal

import psycopg
import pymssql

from text2sql_calorvia import access, overlap
from text2sql_calorvia.config import settings
from text2sql_calorvia.sources import SOURCES, connect, load_sql
from text2sql_calorvia.validation import validate

DB_ERRORS = (psycopg.Error, pymssql.Error)


class QueryTimeout(Exception):
    pass


def log_connect():
    return psycopg.connect(settings.postgres_url, autocommit=True)


def create_log_table():
    with log_connect() as conn:
        conn.execute(load_sql("log/schema"))


def log_start(tool, source, question, sql, session_id=None, user=None, role=None):
    with log_connect() as conn:
        return conn.execute(load_sql("log/start"),
                            (tool, source, question, sql, session_id, user, role)).fetchone()[0]


def log_finish(log_id, status, sql_executed=None, error=None, duration_ms=None, row_count=None, truncated=None):
    with log_connect() as conn:
        conn.execute(load_sql("log/finish"),
                     (sql_executed, status, error, duration_ms, row_count, truncated, log_id))


def to_json(value):
    """A value the model can read in JSON: exact amounts stay numbers, dates become ISO strings."""
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, (dt.date, dt.datetime, dt.time)):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray)):
        return value.hex()
    return value


def run_unvalidated(source, sql, max_rows=None, timeout_s=None, role=None):
    """Run one statement in a read-only, rolled-back transaction with a timeout. Returns (columns, rows, truncated)."""
    max_rows = max_rows or settings.max_rows
    timeout_s = timeout_s or settings.query_timeout_s
    engine = SOURCES[source].engine
    conn = connect(source, query_timeout_s=int(timeout_s) if engine == "sqlserver" else 0, role=role)
    timer = None
    try:
        if engine == "postgres":
            conn.read_only = True   # BEGIN READ ONLY: refuses writes even if the role's default were turned off
            cur = conn.cursor()
            cur.execute(f"SET LOCAL statement_timeout = {int(timeout_s * 1000)}")
            timer = threading.Timer(timeout_s + 2, conn.cancel_safe)  # client side, if the server doesn't stop
            timer.start()
        else:
            cur = conn.cursor()
            cur.execute(f"SET LOCK_TIMEOUT {int(timeout_s * 1000)}")  # don't wait on locks either
            # The row limit, applied by the server to this session, without rewriting the query's text
            cur.execute(f"SET ROWCOUNT {int(max_rows) + 1}")
        start = time.perf_counter()
        try:
            cur.execute(sql)
        except psycopg.errors.QueryCanceled as error:
            raise QueryTimeout(f"Délai dépassé ({timeout_s} s).") from error
        except pymssql.Error as error:
            # pymssql drops the connection when its timeout fires; the message varies ("timed out", "not connected")
            if time.perf_counter() - start >= timeout_s - 0.1:
                raise QueryTimeout(f"Délai dépassé ({timeout_s} s).") from error
            raise
        if cur.description is None:
            return [], [], False
        columns = [d[0] for d in cur.description]
        rows = cur.fetchmany(max_rows + 1)
        truncated = len(rows) > max_rows
        return columns, [[to_json(v) for v in row] for row in rows[:max_rows]], truncated
    finally:
        if timer:
            timer.cancel()
        try:
            conn.rollback()   # a read has nothing to keep; also undoes any temp table
        except Exception:     # noqa: BLE001 - after a timeout the connection is gone: nothing left to undo
            pass
        try:
            conn.close()
        except Exception:     # noqa: BLE001
            pass


def _db_message(error):
    """The first line of a driver error, without pymssql's bytes wrapping."""
    args = getattr(error, "args", ())
    if len(args) == 2 and isinstance(args[1], bytes):
        return args[1].decode("utf-8", "replace").split("DB-Lib error")[0].strip()
    return str(error).splitlines()[0]


def _overlap_refusal(source, population, role=None):
    """A refusal if these rows differ from an earlier aggregate's by too few people (overlap.py, D73)."""
    table, sql = population
    _, rows, truncated = run_unvalidated(source, sql, max_rows=settings.overlap_max_rows, role=role)
    if truncated:
        return "Règle de confidentialité : trop de lignes pour vérifier ce calcul. Restreignez la période."
    groups = {}
    for *key, row_id, person in rows:
        groups.setdefault(tuple(key), {})[row_id] = person
    people = overlap.guard.admit(table, list(groups.values()), settings.min_group_size)
    if people is None:
        return None
    return (f"Règle de confidentialité : ce calcul ne diffère d'un calcul précédent que par {people} personne(s) "
            f"(minimum {settings.min_group_size}) : la comparaison montrerait leur montant. Élargissez le périmètre.")


def execute(source, sql, question=None, max_rows=None, session_id=None, tool="execute_sql", role=None, user=None):
    """Validate, check the payroll rule, run, log. Returns a dict for the model, never raises on a bad query."""
    max_rows = max_rows or settings.max_rows
    log_id = log_start(tool, source, question, sql, session_id, user, role)
    start = time.perf_counter()
    ms = lambda: round((time.perf_counter() - start) * 1000, 1)  # noqa: E731

    validation = validate(source, sql, max_rows, role)
    if not validation.ok:
        log_finish(log_id, "refused", error=" | ".join(validation.errors), duration_ms=ms())
        return {"ok": False, "source": source, "errors": validation.errors}
    try:
        if validation.privacy_check:
            _, rows, _ = run_unvalidated(source, validation.privacy_check, max_rows=1, role=role)
            smallest = rows[0][0] if rows else None
            if smallest is not None and smallest < settings.min_group_size:
                message = (f"Règle de confidentialité : un groupe du résultat ne compte que {smallest} personne(s) "
                           f"(minimum {settings.min_group_size}). Élargissez les groupes ou retirez le filtre "
                           "qui isole des personnes.")
                log_finish(log_id, "refused", validation.sql, message, ms())
                return {"ok": False, "source": source, "errors": [message]}
            if (message := _overlap_refusal(source, validation.population, role)):
                log_finish(log_id, "refused", validation.sql, message, ms())
                return {"ok": False, "source": source, "errors": [message]}
        columns, rows, truncated = run_unvalidated(source, validation.sql, max_rows, role=role)
    except access.AccessDenied as error:
        log_finish(log_id, "refused", validation.sql, str(error), ms())
        return {"ok": False, "source": source, "errors": [str(error)]}
    except (QueryTimeout, *DB_ERRORS) as error:
        message = str(error) if isinstance(error, QueryTimeout) else _db_message(error)
        log_finish(log_id, "error", validation.sql, message, ms())
        return {"ok": False, "source": source, "sql": validation.sql,
                "errors": [f"Erreur à l'exécution : {message}"]}
    log_finish(log_id, "ok", validation.sql, None, ms(), len(rows), truncated)
    return {"ok": True, "source": source, "sql": validation.sql, "columns": columns, "rows": rows,
            "row_count": len(rows), "truncated": truncated, "log_id": log_id,
            **({"warnings": validation.warnings} if validation.warnings else {})}
