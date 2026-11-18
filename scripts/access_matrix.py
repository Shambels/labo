"""The access matrix of the report (step 29): what each role may read, and what its evaluation run showed.

    uv run python scripts/access_matrix.py > results/t2sql/access_matrix.md
"""
from collections import Counter
from pathlib import Path

import psycopg
import yaml

from text2sql_calorvia import access, policy
from text2sql_calorvia.config import settings
from text2sql_calorvia.evaluation import load_questions
from text2sql_calorvia.role_evaluation import CLOSED, LIMITED, OPEN, reach, split_flags
from text2sql_calorvia.sources import load_sql


REVIEW = Path("results/t2sql/role_flags_review.yaml")


def tables(role, source):
    found = access.tables_of(role, source)
    return "all" if found == "*" else str(len(found)) if found else "–"


def main():
    questions = {q["id"]: q for q in load_questions(split="dev")}
    with psycopg.connect(settings.postgres_url) as db:
        runs = {role: (run, commit) for run, role, commit in db.execute(load_sql("eval/role_runs")).fetchall()}
        results = {role: db.execute(load_sql("eval/role_results"), (run,)).fetchall() for role, (run, _) in runs.items()}
    reviewed = {(r["role"], r["question"]) for r in yaml.safe_load(REVIEW.read_text())["reviewed"]}
    print("| Role | ERP | Compta | Paie | Rows | Document rules | Run | Open: right | Limited: safe | Closed: safe "
          "| Queries outside the role | Answers flagged, then reviewed | Unresolved |")
    print("|---|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for role in access.roles():
        rules = policy.document_rules(role)
        cells = [f"`{role}`", *(tables(role, s) for s in ("erp", "compta", "paie")), access.site_label(role) or "all",
                 "all" if "*" in rules else len(rules)]
        if role in runs:
            total, right, outside, flagged, unresolved = Counter(), Counter(), 0, 0, 0
            for qid, ok, leaked, _, error in results[role]:
                where, flags = reach(questions[qid], role), split_flags(leaked, (role, qid) in reviewed)
                total[where] += 1
                right[where] += bool(ok) if where == OPEN else not flags["unresolved"] and not error
                outside += len(flags["outside"])
                flagged += bool(flags["flagged"]) and (role, qid) in reviewed
                unresolved += len(flags["unresolved"])
            cells += [runs[role][0], *(f"{right[w]}/{total[w]}" for w in (OPEN, LIMITED, CLOSED)), outside, flagged, unresolved]
        else:
            cells += ["–"] * 7
        print("| " + " | ".join(map(str, cells)) + " |")


if __name__ == "__main__":
    main()
