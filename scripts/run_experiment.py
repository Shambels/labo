"""Run one or more experiments on the dev set: retrieval, generation, deterministic scores, results in PostgreSQL.

Needs the embedder, the reranker and (unless [generation] enabled = false) the generator.
Usage: uv run python scripts/run_experiment.py experiments/baseline.toml [experiments/other.toml ...]
       uv run python scripts/run_experiment.py experiments/baseline.toml --retrieval-only
"""
import argparse
import tomllib

from rag_calorvia.evaluation.runner import run_experiment
from rag_calorvia.logs import setup_logging

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("configs", nargs="+", help="experiment TOML files")
parser.add_argument("--allow-dirty", action="store_true",
                    help="run on uncommitted code (a trial: such runs stay out of the report)")
parser.add_argument("--retrieval-only", action="store_true",
                    help="no generation; the run is named <name>__retrieval so it never mixes with full runs")
args = parser.parse_args()
setup_logging()

for path in args.configs:
    with open(path, "rb") as f:
        config = tomllib.load(f)
    if args.retrieval_only:
        config["generation"] = {"enabled": False}
        config["name"] += "__retrieval"
    print(f"{path}: experiment {run_experiment(config, allow_dirty=args.allow_dirty)}")
