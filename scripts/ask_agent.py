"""Ask the agent the 12 starter questions and check its answers, as step 12 did for auto-ontology.

    uv run python scripts/ask_agent.py run1              # every question, saved as data/agent_runs/run1.json
    uv run python scripts/ask_agent.py run1 -q 5 6       # only some questions

Two scores: the step 12 check (every number and date of the expected answer among the rows the agent fetched or in
its prose), and a stricter one, in the prose only: the CFO reads the answer, not the rows. These are the questions the
ontology was certified from, so this is a training score; step 14 builds the evaluation set.
Questions and answers come from the course material at run time (D42); data/ is git-ignored.
"""
import argparse
import asyncio
import json
import time
from pathlib import Path

from text2sql_calorvia.agent import Agent
from text2sql_calorvia.evaluation import prose, prose_numbers
from text2sql_calorvia.starter import expected_tokens, load_questions, matches, result_values

from ask_ontology import _typed

OUT = Path("data/agent_runs")


def check(expected, result):
    """(missing from rows or prose, missing from the prose)."""
    prose_values = prose_numbers(prose(result["answer"]))
    rows = [[_typed(v) for v in row] for r in result["results"].values() for row in r["rows"]]
    tokens = expected_tokens(expected)
    return ([str(t) for t in tokens if not matches(t, result_values(rows) | prose_values)],
            [str(t) for t in tokens if not matches(t, prose_values)])


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("label")
    parser.add_argument("-q", "--questions", type=int, nargs="*")
    parser.add_argument("--recheck", action="store_true", help="re-score a saved run without asking again")
    args = parser.parse_args()
    if args.recheck:
        path, questions = OUT / f"{args.label}.json", load_questions()
        runs = json.loads(path.read_text())
        for number, result in runs.items():
            result["missing"], result["missing_in_prose"] = check(questions[int(number)][2], result)
            result["ok"] = not result["missing"] and not result["error"]
            result["ok_prose"] = not result["missing_in_prose"] and not result["error"]
        path.write_text(json.dumps(runs, ensure_ascii=False, indent=1, default=str))
        print(f"{sum(r['ok'] for r in runs.values())}/{len(runs)} as expected (rows or prose), "
              f"{sum(r['ok_prose'] for r in runs.values())}/{len(runs)} in the prose")
        return
    questions, agent = load_questions(), Agent()
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{args.label}.json"
    runs = json.loads(path.read_text()) if path.exists() else {}
    for number in args.questions or sorted(questions):
        question, _, expected = questions[number]
        start, error = time.perf_counter(), None
        try:
            result = await agent.ask([{"role": "user", "content": question}], f"starter-{args.label}-q{number}")
        except Exception as e:   # one failed question must not stop the run
            result, error = {"answer": "", "steps": [], "results": {}}, f"{type(e).__name__}: {e}"
        result.update(seconds=round(time.perf_counter() - start, 1), error=error)
        result["missing"], result["missing_in_prose"] = check(expected, result)
        result["ok"] = not result["missing"] and not error
        result["ok_prose"] = not result["missing_in_prose"] and not error
        runs[str(number)] = result
        path.write_text(json.dumps(runs, ensure_ascii=False, indent=1, default=str))
        queries = sum(1 for s in result["steps"] if s["tool"] == "execute_sql")
        failed = sum(1 for s in result["steps"] if s["tool"] in ("execute_sql", "validate_sql") and not s["ok"])
        print(f"Q{number:02d} {'OK  ' if result['ok'] else 'MISS'} prose={'OK  ' if result['ok_prose'] else 'MISS'} "
              f"{result['seconds']:6.1f} s  {len(result['steps'])} tools, {queries} queries, {failed} failed  "
              f"missing={result['missing']} in prose={result['missing_in_prose']} error={error}", flush=True)
    print(f"\n{sum(r['ok'] for r in runs.values())}/{len(runs)} as expected (rows or prose), "
          f"{sum(r['ok_prose'] for r in runs.values())}/{len(runs)} in the prose ({path})")


if __name__ == "__main__":
    asyncio.run(main())
