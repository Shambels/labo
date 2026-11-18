"""Export the agent's evaluation runs from PostgreSQL to results/t2sql/ (CSV, committed): the trace RAPPORT_T2SQL.md
relies on (step 16). Only finished runs made from a clean tree.

    uv run python scripts/export_t2sql_results.py

results/t2sql/experiments.csv   one row per run: commits (agent, scorer), options, totals, times
results/t2sql/by_category.csv   the same totals per run and question category
results/t2sql/answers.csv       every answer with its label, verdict, missing values, timings; the executed queries
                                are in the answer (the code-built footer)

Unlike the RAG export (D39), the questions and expected values are in the repository already
(evaluation/t2sql_questions.yaml, D57): join them by question id.
"""
import csv
import json
from pathlib import Path

import psycopg

from text2sql_calorvia.charts import without_images
from text2sql_calorvia.config import settings
from text2sql_calorvia.sources import load_sql

OUT = Path("results/t2sql")
CATEGORY_COLUMNS = ["experiment_id", "name", "split", "commits", "category", "questions", "ok", "confidently_wrong",
                    "assumed", "queries", "refused", "exec_errors", "median_s", "max_s", "agent_errors"]


def cell(value):
    if isinstance(value, float):
        return round(value, 2)
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    if hasattr(value, "isoformat"):
        return value.isoformat(timespec="minutes")
    return value


def write(name, columns, rows):
    with (OUT / name).open("w", newline="") as f:
        out = csv.writer(f)
        out.writerow(columns)
        out.writerows([cell(v) for v in row] for row in rows)
    print(f"{OUT / name}: {len(rows)} rows")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    with psycopg.connect(settings.postgres_url) as db:
        runs = db.execute(load_sql("eval/export_runs"))
        run_columns = [c.name for c in runs.description]
        runs = runs.fetchall()
        ids = [r[0] for r in runs]
        by_category = db.execute(load_sql("eval/summary"), (False, ids)).fetchall()
        answers = db.execute(load_sql("eval/export_answers"))
        answer_columns = [c.name for c in answers.description]
        answer_at = answer_columns.index("answer")   # signed chart links stay out of a public repository (step 29)
        answers = [(*r[:answer_at], without_images(r[answer_at]), *r[answer_at + 1:]) for r in answers.fetchall()]
    write("experiments.csv", run_columns, runs)
    write("by_category.csv", CATEGORY_COLUMNS, by_category)
    write("answers.csv", answer_columns, answers)


if __name__ == "__main__":
    main()
