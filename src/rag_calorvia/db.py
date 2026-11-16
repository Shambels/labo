"""PostgreSQL: connection, tables, inserts. The only module that runs SQL; the queries are in sql/."""
from importlib.resources import files

import psycopg
from psycopg.types.json import Jsonb

from rag_calorvia.config import settings
from rag_calorvia.git_state import git_state


def load_sql(name):
    """Read a query from src/rag_calorvia/sql/, wherever the program is started from."""
    return files("rag_calorvia").joinpath("sql", f"{name}.sql").read_text(encoding="utf-8")


def connect(read_only=False):
    """Open a connection. Use it as `with connect() as conn:`: commit on success, rollback on error.

    read_only=True makes PostgreSQL refuse any write on this connection (used by the UI).
    """
    conn = psycopg.connect(settings.postgres_url)
    conn.read_only = read_only
    return conn


def create_tables(conn):
    """Create the tables if they don't exist yet. Safe to call before every run."""
    conn.execute(load_sql("schema"))


def start_experiment(conn, name, config):
    """Insert an experiment with status 'running', stamped with the current git commit, and return its id."""
    commit, dirty = git_state()
    row = conn.execute(load_sql("start_experiment"), (name, Jsonb(config), commit, dirty)).fetchone()
    conn.commit()  # visible right away, even if the run crashes later
    return row[0]


def finish_experiment(conn, experiment_id, status, duration_s):
    """Mark an experiment as 'done' or 'failed' and record how long it took."""
    conn.execute(load_sql("finish_experiment"), (status, duration_s, experiment_id))
    conn.commit()


def insert_answers(conn, experiment_id, answers):
    """Insert dicts with keys question_id, chunks, answer and latency_ms."""
    with conn.cursor() as cur:
        cur.executemany(
            load_sql("insert_answers"),
            [(experiment_id, a["question_id"], Jsonb(a["chunks"]), a["answer"], a["latency_ms"]) for a in answers],
        )
    conn.commit()


def insert_scores(conn, experiment_id, scores):
    """Insert dicts with keys question_id, question_type, metric, value and reason (optional).

    A score already stored for the same question and metric is replaced: re-running the judge overwrites it.
    """
    with conn.cursor() as cur:
        cur.executemany(
            load_sql("insert_scores"),
            [
                (experiment_id, s["question_id"], s["question_type"], s["metric"], s["value"], s.get("reason"))
                for s in scores
            ],
        )
    conn.commit()


def load_experiment(conn, experiment_id):
    """(id, name, config, status) of an experiment, or None if the id doesn't exist."""
    return conn.execute(load_sql("load_experiment"), (experiment_id,)).fetchone()


def find_experiment(conn, name):
    """Id of the most recent finished run of an experiment name, or None."""
    row = conn.execute(load_sql("find_experiment"), (name,)).fetchone()
    return row[0] if row else None


def load_answers(conn, experiment_id):
    """{question_id: (chunks, answer)} of an experiment."""
    return {qid: (chunks, answer) for qid, chunks, answer in conn.execute(load_sql("load_answers"), (experiment_id,))}


def load_score_keys(conn, experiment_id):
    """The (question_id, metric) pairs already scored (non-NULL): lets an interrupted judge pass resume."""
    return set(conn.execute(load_sql("load_score_keys"), (experiment_id,)).fetchall())


def question_answers(conn, question_id):
    """Rows of (experiment id, name, answer, chunks, latency_ms) for one question, in every finished experiment."""
    return conn.execute(load_sql("question_answers"), (question_id,)).fetchall()


def question_scores(conn, question_id):
    """Rows of (experiment id, metric, value, reason) for one question."""
    return conn.execute(load_sql("question_scores"), (question_id,)).fetchall()


def compare_experiments(conn):
    """Mean of each metric for each experiment: rows of (name, metric, mean, n), best first."""
    return conn.execute(load_sql("compare_experiments")).fetchall()


def list_experiments(conn):
    """Every experiment, oldest first: rows of (id, name, config, started_at, duration_s, status, git_commit, git_dirty)."""
    return conn.execute(load_sql("report_experiments")).fetchall()


def list_scores(conn):
    """Every score: rows of (experiment_id, question_id, question_type, metric, value)."""
    return conn.execute(load_sql("report_scores")).fetchall()


def save_documents(conn, rows):
    """Write the inventory: upsert every row, then drop the rows of files no longer in the corpus."""
    with conn.cursor() as cur:
        cur.executemany(load_sql("upsert_document"), rows)
        cur.execute(load_sql("delete_missing_documents"), ([row["path"] for row in rows],))
    conn.commit()


def inventory_summary(conn):
    """Rows of (format, files, indexed, duplicate, other_excluded, scans), biggest formats first."""
    return conn.execute(load_sql("inventory_summary")).fetchall()


def load_registry(conn):
    """{path: {format, source_type, excluded_reason, duplicate_of}} of every file of the corpus."""
    rows = conn.execute(load_sql("load_registry")).fetchall()
    return {
        path: {"format": fmt, "source_type": source, "excluded_reason": reason, "duplicate_of": duplicate_of}
        for path, fmt, source, reason, duplicate_of in rows
    }


def load_indexable_documents(conn):
    """The registry rows of the documents to chunk, as dicts (column -> value), in path order."""
    cursor = conn.execute(load_sql("load_indexable_documents"))
    columns = [c.name for c in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def experiment_scores(conn, experiment_id):
    """{question_id: {metric: value}} of one experiment."""
    scores = {}
    for question_id, metric, value in conn.execute(load_sql("experiment_scores"), (experiment_id,)):
        scores.setdefault(question_id, {})[metric] = value
    return scores
