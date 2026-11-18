"""The access matrix of the report (step 29): what each role may read, and what its evaluation run showed.

    uv run python scripts/access_matrix.py > results/t2sql/access_matrix.md
"""
from collections import Counter

import psycopg

from text2sql_calorvia import access, policy
from text2sql_calorvia.config import settings
from text2sql_calorvia.evaluation import load_questions
from text2sql_calorvia.role_evaluation import CLOSED, LIMITED, OPEN, reach
from text2sql_calorvia.sources import load_sql


def tables(role, source):
    found = access.tables_of(role, source)
    return "all" if found == "*" else str(len(found)) if found else "–"


def main():
    questions = {q["id"]: q for q in load_questions(split="dev")}
    with psycopg.connect(settings.postgres_url) as db:
        runs = {role: (run, commit) for run, role, commit in db.execute(load_sql("eval/role_runs")).fetchall()}
        results = {role: db.execute(load_sql("eval/role_results"), (run,)).fetchall() for role, (run, _) in runs.items()}
    print("| Role | ERP | Compta | Paie | Rows | Document folders | Run | Open questions right | Limited, nothing revealed "
          "| Closed, nothing revealed | Leaks |")
    print("|---|---:|---:|---:|---|---|---:|---:|---:|---:|---:|")
    for role in access.roles():
        site = access.site_label(role)
        rules = policy.document_rules(role)
        folders = "all" if "*" in rules else str(len(rules))
        cells = [role, *(tables(role, s) for s in ("erp", "compta", "paie")), site or "all", folders]
        if role in runs:
            total, right, leaks = Counter(), Counter(), 0
            for qid, ok, leaked, _, _ in results[role]:
                where = reach(questions[qid], role)
                total[where] += 1
                right[where] += bool(ok)
                leaks += len(leaked)
            cells += [runs[role][0], *(f"{right[w]}/{total[w]}" for w in (OPEN, LIMITED, CLOSED)), leaks]
        else:
            cells += ["–"] * 5
        print("| " + " | ".join(f"`{c}`" if c == role else str(c) for c in cells) + " |")


if __name__ == "__main__":
    main()
