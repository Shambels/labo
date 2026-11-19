"""What the experiment comparison page shows (app/experiments.py), as plain functions over the two result stores.

- RAG runs: table `experiments` + `scores` (this package); the means per group are those of scripts/report.py
  (evaluation/report.summarize), so the page and the command line always agree.
- Text-to-SQL runs: `t2sql_experiments` + `t2sql_results`; per category as scripts/t2sql_report.py.
- Both: the questions whose result differs between runs, and the settings that differ between their configurations.
"""
import hashlib
import json

from rag_calorvia import db
from rag_calorvia.evaluation.report import summarize

LOWER_IS_BETTER = {"trap_hit@5", "trap_hit@3"}   # the share of questions whose top k holds a trap
RETRIEVAL_METRICS = ["recall@5", "mrr@5", "hit@5", "ndcg@5", "trap_hit@5"]
JUDGED_METRICS = ["correctness", "faithfulness", "answer_relevancy", "contextual_precision", "contextual_recall"]
LONG_TEXT = 120   # a configuration string longer than this (a stored prompt) is compared by its hash


# --- RAG ------------------------------------------------------------------------------------------------------------
RAG_RUNS = """
SELECT e.id, e.name, e.started_at, e.duration_s, e.git_commit, e.git_dirty,
       (e.config->'generation'->>'enabled')::boolean AS generation,
       e.config->'evaluation'->>'split' AS split,
       count(DISTINCT s.question_id) FILTER (WHERE s.metric = 'correctness') AS judged
FROM experiments e LEFT JOIN scores s ON s.experiment_id = e.id
WHERE e.status = 'done'
GROUP BY e.id ORDER BY e.id"""


def rag_runs(conn):
    """Every finished RAG run: id, name, date, duration, commit, dirty, generation on/off, split, judged questions."""
    columns = ["id", "name", "started_at", "duration_s", "git_commit", "git_dirty", "generation", "split", "judged"]
    return [dict(zip(columns, row)) | {"split": row[7] or "dev"} for row in conn.execute(RAG_RUNS)]


def rag_scores(conn, run_ids):
    """{run id: {question id: {metric: value}}}."""
    return {run_id: db.experiment_scores(conn, run_id) for run_id in run_ids}


def rag_configs(conn, run_ids):
    return {run_id: db.load_experiment(conn, run_id)[2] for run_id in run_ids}


def metric_table(scores, questions, registry, metric, by):
    """Rows {group, <run>: mean, <run> n: count}, groups sorted and 'all' last; by = 'type', 'format' or 'all'."""
    summary = summarize(scores, questions, registry, metric, "type" if by == "all" else by)
    groups = ["all"] if by == "all" else sorted(g for g in summary if g != "all") + ["all"]
    rows = []
    for group in groups:
        row = {"group": group}
        for run in scores:
            mean, n = summary.get(group, {}).get(run, (None, 0))
            row[run], row[f"{run} n"] = mean, n
        rows.append(row)
    return rows


def best_run(row, runs, metric):
    """The run with the best mean in a row (None on a tie or with fewer than two values)."""
    values = {run: row[run] for run in runs if row.get(run) is not None}
    if len(values) < 2 or len(set(round(v, 6) for v in values.values())) == 1:
        return None
    pick = min if metric in LOWER_IS_BETTER else max
    best = pick(values.values())
    winners = [run for run, v in values.items() if round(v, 6) == round(best, 6)]
    return winners[0] if len(winners) == 1 else None


def question_diffs(scores, metric, questions):
    """The questions whose value of `metric` differs between runs: [{question, type, <run>: value}]."""
    types = {q["id"]: q["type"] for q in questions}
    rows = []
    for qid in sorted(types):
        values = {run: per_run.get(qid, {}).get(metric) for run, per_run in scores.items()}
        present = [v for v in values.values() if v is not None]
        if len(present) >= 2 and len({round(v, 6) for v in present}) > 1:
            rows.append({"question": qid, "type": types[qid], **values})
    return rows


# --- text-to-SQL ------------------------------------------------------------------------------------------------------
T2SQL_RUNS = """
SELECT e.id, e.name, e.split, e.started_at, e.git_commit, e.git_dirty, e.config->>'role' AS role,
       count(r.*) AS questions, count(*) FILTER (WHERE r.ok) AS ok,
       count(*) FILTER (WHERE r.behavior = 'answer' AND NOT r.ok AND r.label IN ('answer', 'assume')) AS confidently_wrong,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY r.seconds) AS median_s
FROM t2sql_experiments e JOIN t2sql_results r ON r.experiment_id = e.id
WHERE e.finished_at IS NOT NULL
GROUP BY e.id ORDER BY e.id"""

T2SQL_CATEGORIES = """
SELECT experiment_id, category, count(*), count(*) FILTER (WHERE ok),
       count(*) FILTER (WHERE behavior = 'answer' AND NOT ok AND label IN ('answer', 'assume'))
FROM t2sql_results WHERE experiment_id = ANY(%s)
GROUP BY experiment_id, category ORDER BY category"""

T2SQL_RESULTS = """
SELECT experiment_id, question_id, category, behavior, label, ok, missing, seconds, queries, answer
FROM t2sql_results WHERE experiment_id = ANY(%s)"""


def t2sql_runs(conn):
    columns = ["id", "name", "split", "started_at", "git_commit", "git_dirty", "role", "questions", "ok",
               "confidently_wrong", "median_s"]
    return [dict(zip(columns, row)) for row in conn.execute(T2SQL_RUNS)]


def t2sql_categories(conn, run_ids):
    """Rows {category, <run>: 'ok/questions', <run> wrong: confidently wrong}, plus a total row."""
    table, totals = {}, {run: [0, 0, 0] for run in run_ids}
    for run, category, questions, ok, wrong in conn.execute(T2SQL_CATEGORIES, (list(run_ids),)):
        table.setdefault(category, {"category": category})
        table[category][run], table[category][f"{run} wrong"] = f"{ok}/{questions}", wrong
        for i, v in enumerate((ok, questions, wrong)):
            totals[run][i] += v
    total = {"category": "total"}
    for run, (ok, questions, wrong) in totals.items():
        total[run], total[f"{run} wrong"] = f"{ok}/{questions}" if questions else "–", wrong
    return [table[c] for c in sorted(table)] + [total]


def t2sql_results(conn, run_ids):
    """{run id: {question id: result dict}}."""
    out = {run: {} for run in run_ids}
    columns = ["category", "behavior", "label", "ok", "missing", "seconds", "queries", "answer"]
    for run, qid, *values in conn.execute(T2SQL_RESULTS, (list(run_ids),)):
        out[run][qid] = dict(zip(columns, values))
    return out


def t2sql_diffs(results):
    """The questions answered right by some runs and wrong by others."""
    rows = []
    for qid in sorted({q for per_run in results.values() for q in per_run}):
        oks = {run: per_run[qid]["ok"] for run, per_run in results.items() if qid in per_run}
        if len(set(oks.values())) > 1:
            category = next(per_run[qid]["category"] for per_run in results.values() if qid in per_run)
            rows.append({"question": qid, "category": category, **{run: "✓" if ok else "✗" for run, ok in oks.items()}})
    return rows


def t2sql_configs(conn, run_ids):
    return dict(conn.execute("SELECT id, config FROM t2sql_experiments WHERE id = ANY(%s)", (list(run_ids),)).fetchall())


# --- both -------------------------------------------------------------------------------------------------------------
def flatten(config, prefix=""):
    """{"search.top_k": 5, ...}: nested settings as dotted keys."""
    flat = {}
    for key, value in (config or {}).items():
        path = f"{prefix}{key}"
        if isinstance(value, dict):
            flat |= flatten(value, path + ".")
        else:
            flat[path] = value
    return flat


def shown(value):
    """A setting as the page shows it: long texts (stored prompts) by length and hash, the rest as JSON."""
    if isinstance(value, str) and len(value) > LONG_TEXT:
        return f"{len(value)} characters, sha {hashlib.sha256(value.encode()).hexdigest()[:8]}"
    return json.dumps(value, ensure_ascii=False)


def config_diff(configs):
    """[{setting, <run>: value}] for every setting whose value differs between the runs (the name aside)."""
    flat = {run: flatten(config) for run, config in configs.items()}
    keys = sorted({k for f in flat.values() for k in f} - {"name"})
    rows = []
    for key in keys:
        values = {run: shown(f[key]) if key in f else "(absent)" for run, f in flat.items()}
        if len(set(values.values())) > 1:
            rows.append({"setting": key, **values})
    return rows
