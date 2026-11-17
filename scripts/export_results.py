"""Export the results from PostgreSQL to results/ (CSV files, committed): the trace the report relies on.

    uv run python scripts/export_results.py --final status_filter

results/experiments.csv      every run: id, name, commit, dirty, status, duration, the options that matter
results/summary_by_type.csv  the mean of every metric per run and question type, with n
results/final_answers.csv    the final configuration on dev and test: question id and type, answer, scores

The question and expected-answer texts are left out on purpose: they are the course's eval set, and this repository
is public. Join them back locally from data/calorvia_eval.json by question id.
"""
import argparse
import csv
from pathlib import Path

from rag_calorvia import db
from rag_calorvia.evaluation.dataset import load_questions

RESULTS = Path("results")
KEY_OPTIONS = ["chunking.max_tokens", "chunking.context_line", "chunking.excel", "chunking.vision",
               "chunking.vision_max_tokens", "sparse.language", "search.translate", "search.exclude_status",
               "search.reference_date", "generation.enabled", "generation.model", "generation.system_prompt",
               "generation.order", "tools.tables", "evaluation.split"]
FINAL_METRICS = ["recall@5", "hit@5", "mrr@5", "trap_hit@5", "refusal", "correctness", "faithfulness"]


def option(config, dotted):
    value = config
    for key in dotted.split("."):
        value = value.get(key) if isinstance(value, dict) else None
    return value


def write(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)
    print(f"{path}: {len(rows)} rows")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--final", required=True, help="name of the final configuration (its dev and __test runs)")
    args = parser.parse_args()
    RESULTS.mkdir(exist_ok=True)

    with db.connect(read_only=True) as conn:
        experiments = db.list_experiments(conn)
        write(RESULTS / "experiments.csv",
              ["id", "name", "git_commit", "git_dirty", "status", "started_at", "duration_s", *KEY_OPTIONS],
              [[i, name, commit, dirty, status, started.isoformat(timespec="minutes"),
                round(duration or 0), *[option(config, k) for k in KEY_OPTIONS]]
               for i, name, config, started, duration, status, commit, dirty in experiments])
        summary = conn.execute(db.load_sql("export_summary")).fetchall()
        write(RESULTS / "summary_by_type.csv", ["experiment_id", "name", "question_type", "metric", "mean", "n"], summary)

        rows = []
        for split, name in [("dev", args.final), ("test", f"{args.final}__test")]:
            experiment_id = db.find_experiment(conn, name)
            if experiment_id is None:
                print(f"no finished run named {name!r}: skipped")
                continue
            answers, scores = db.load_answers(conn, experiment_id), db.experiment_scores(conn, experiment_id)
            for q in load_questions(split, allow_test=split == "test"):
                answer = (answers.get(q["id"]) or (None, None))[1]
                rows.append([split, experiment_id, q["id"], q["type"], answer,
                             *[scores.get(q["id"], {}).get(m) for m in FINAL_METRICS]])
        write(RESULTS / "final_answers.csv",
              ["split", "experiment_id", "question_id", "type", "answer", *FINAL_METRICS], rows)


if __name__ == "__main__":
    main()
