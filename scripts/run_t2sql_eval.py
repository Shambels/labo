"""Run the agent on the evaluation set and store every answer, with the git commit, in PostgreSQL (step 14).

    uv run python scripts/run_t2sql_eval.py experiments/t2sql/with_ontology.toml            # dev questions
    uv run python scripts/run_t2sql_eval.py experiments/t2sql/with_ontology.toml -q A01 M05 # some questions
    uv run python scripts/run_t2sql_eval.py experiments/t2sql/final.toml --test             # once, at the end

Needs the MCP server (9001) and the LLM (8000). A run made with uncommitted changes is stored with git_dirty = true
and left out of the report.
"""
import argparse
import asyncio
import json
import time
import tomllib
from pathlib import Path

import psycopg
from openai import OpenAI

from rag_calorvia.git_state import git_state
from text2sql_calorvia.agent import Agent
from text2sql_calorvia.config import settings
from text2sql_calorvia.evaluation import judge, load_questions, score, sql_counts, verdict
from text2sql_calorvia.sources import load_sql


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("config", type=Path)
    parser.add_argument("-q", "--questions", nargs="*", help="question ids (default: the whole split)")
    parser.add_argument("--test", action="store_true", help="the held-out test questions (run once, step 16)")
    args = parser.parse_args()
    config = tomllib.loads(args.config.read_text())
    split = "test" if args.test else "dev"
    questions = [q for q in load_questions(split=split) if not args.questions or q["id"] in args.questions]
    commit, dirty = git_state()
    agent, judge_client = Agent(**config.get("agent", {})), OpenAI(base_url=settings.llm_url, api_key="local")

    with psycopg.connect(settings.postgres_url, autocommit=True) as db:
        db.execute(load_sql("eval/schema"))
        experiment = db.execute(load_sql("eval/start"), (config["name"], json.dumps(config), split, commit, dirty)).fetchone()[0]
        print(f"experiment {experiment}: {config['name']}, {len(questions)} {split} questions, commit {commit[:7]}"
              f"{' (dirty: not for the report)' if dirty else ''}", flush=True)
        for q in questions:
            start, error = time.perf_counter(), None
            try:
                result = await agent.ask([{"role": "user", "content": q["question"]}], f"eval-{experiment}-{q['id']}")
            except Exception as e:   # one failure must not stop the run; it is stored and counted
                result, error = {"answer": "", "steps": []}, f"{type(e).__name__}: {e}"
            seconds = time.perf_counter() - start
            scored = score(q, result["answer"])
            judged = judge(q["question"], result["answer"], judge_client) if result["answer"] else {"label": "error", "why": error}
            ok = verdict(q, scored, judged["label"]) and not error
            counts = sql_counts(result["steps"])
            db.execute(load_sql("eval/result"), (
                experiment, q["id"], q["category"], q["behavior"], judged["label"], judged.get("why"), ok,
                json.dumps(scored["missing"]), json.dumps(scored["leaked"]), seconds, counts["tool_calls"],
                counts["queries"], counts["refused"], counts["exec_errors"], error, result["answer"],
                json.dumps(result["steps"], ensure_ascii=False, default=str)))
            print(f"{q['id']} {'OK  ' if ok else 'MISS'} {q['behavior']:7} → {judged['label']:7} {seconds:6.1f} s  "
                  f"{counts['queries']} queries ({counts['refused']} refused, {counts['exec_errors']} errors)  "
                  f"missing={scored['missing']} leaked={scored['leaked']}{' ERROR ' + error if error else ''}", flush=True)
        db.execute(load_sql("eval/finish"), (experiment,))
    print(f"done: experiment {experiment}")


if __name__ == "__main__":
    asyncio.run(main())
