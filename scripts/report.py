"""Compare experiments on the dev set: the mean of each metric per question type and per evidence format.

    uv run python scripts/report.py baseline__retrieval no_context_line__retrieval
    uv run python scripts/report.py baseline --metrics recall@5 refusal --by format

Each name means its most recent finished run. Means are over the questions that have the metric: (n) is their number.
"""
import argparse

from rag_calorvia import db
from rag_calorvia.evaluation.dataset import align_with_registry, load_questions
from rag_calorvia.evaluation.report import format_table, summarize

DEFAULT_METRICS = ["hit@5", "recall@5", "mrr@5", "ndcg@5", "trap_hit@5"]

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("experiments", nargs="+", help="experiment names")
parser.add_argument("--metrics", nargs="+", default=DEFAULT_METRICS)
parser.add_argument("--by", choices=["type", "format", "both"], default="both")
args = parser.parse_args()

with db.connect(read_only=True) as conn:
    registry = db.load_registry(conn)
    scores = {}
    for name in args.experiments:
        experiment_id = db.find_experiment(conn, name)
        if experiment_id is None:
            raise SystemExit(f"no finished run named {name!r}")
        scores[name] = db.experiment_scores(conn, experiment_id)
questions = align_with_registry(load_questions("dev"), registry)

for by in (["type", "format"] if args.by == "both" else [args.by]):
    for metric in args.metrics:
        print(format_table(summarize(scores, questions, registry, metric, by), args.experiments, metric, by), "\n")
