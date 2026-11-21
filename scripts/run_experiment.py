"""Run one or more experiments on the dev set: retrieval, generation, deterministic scores, results in PostgreSQL.

Needs the embedder, the reranker and (unless [generation] enabled = false) the generator.
Usage: uv run python scripts/run_experiment.py experiments/baseline.toml [experiments/other.toml ...]
       uv run python scripts/run_experiment.py experiments/baseline.toml --retrieval-only
       uv run python scripts/run_experiment.py experiments/status_filter.toml --test   # final evaluation, once
       uv run python scripts/run_experiment.py experiments/combined_complete_top10.toml --fresh  # step 40's held-out set
"""
import argparse
import tomllib

from rag_calorvia.evaluation.runner import run_experiment
from rag_calorvia.logs import setup_logging

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("configs", nargs="+", help="experiment TOML files")
parser.add_argument("--allow-dirty", action="store_true",
                    help="run on uncommitted code (a trial: such runs stay out of the report)")
parser.add_argument("--test", action="store_true",
                    help="the final evaluation on the 31 held-out questions (named <name>__test); once, at the end")
parser.add_argument("--fresh", action="store_true",
                    help="step 40's held-out questions on documents nobody cited (named <name>__fresh); once, at the end")
parser.add_argument("--retrieval-only", action="store_true",
                    help="no generation; the run is named <name>__retrieval so it never mixes with full runs")
args = parser.parse_args()
setup_logging()

for path in args.configs:
    with open(path, "rb") as f:
        config = tomllib.load(f)
    if args.retrieval_only:
        config["generation"]["enabled"] = False  # the model stays known: question translation uses it
        config["name"] += "__retrieval"
    if args.test:
        config["evaluation"] = {"split": "test"}
        config["name"] += "__test"
    if args.fresh:
        config["evaluation"] = {"split": "fresh"}
        config["name"] += "__fresh"
    print(f"{path}: experiment {run_experiment(config, allow_dirty=args.allow_dirty)}")
