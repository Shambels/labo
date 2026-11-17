"""Compare experiments of the agent (step 14): per category and in total.

    uv run python scripts/t2sql_report.py 3 4            # experiment ids
    uv run python scripts/t2sql_report.py 3 4 --dirty    # include runs made with uncommitted changes
"""
import argparse
from collections import defaultdict

import psycopg

from text2sql_calorvia.config import settings
from text2sql_calorvia.sources import load_sql

COLUMNS = ["questions", "ok", "confidently_wrong", "assumed", "queries", "refused", "exec_errors", "median_s", "max_s",
           "agent_errors"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("ids", type=int, nargs="+")
    parser.add_argument("--dirty", action="store_true")
    args = parser.parse_args()
    with psycopg.connect(settings.postgres_url) as db:
        rows = db.execute(load_sql("eval/summary"), (args.dirty, args.ids)).fetchall()
    by_experiment = defaultdict(list)
    for exp_id, name, split, commit, category, *values in rows:
        by_experiment[(exp_id, name, split, commit)].append((category, dict(zip(COLUMNS, values))))
    for (exp_id, name, split, commit), cats in by_experiment.items():
        print(f"\n## {exp_id} {name} ({split}, {commit})\n")
        print("| category | ok | confidently wrong | assumed | queries | refused | exec errors | median s | max s |")
        print("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
        total = defaultdict(float)
        for category, v in cats:
            print(f"| {category} | {v['ok']}/{v['questions']} | {v['confidently_wrong']} | {v['assumed']} | {v['queries']} | "
                  f"{v['refused']} | {v['exec_errors']} | {v['median_s']:.0f} | {v['max_s']:.0f} |")
            for k in ("questions", "ok", "confidently_wrong", "assumed", "queries", "refused", "exec_errors"):
                total[k] += v[k] or 0
        valid = 1 - total["refused"] / total["queries"] if total["queries"] else 0
        errors = total["exec_errors"] / (total["queries"] - total["refused"]) if total["queries"] - total["refused"] else 0
        print(f"| **total** | **{int(total['ok'])}/{int(total['questions'])}** ({total['ok'] / total['questions']:.0%}) | "
              f"{int(total['confidently_wrong'])} | {int(total['assumed'])} | {int(total['queries'])} | "
              f"{int(total['refused'])} | {int(total['exec_errors'])} | | |")
        print(f"\nvalid queries (passed validation): {valid:.0%} · execution errors among valid queries: {errors:.0%}")


if __name__ == "__main__":
    main()
