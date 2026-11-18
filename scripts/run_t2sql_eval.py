"""Run the agent on the evaluation set and store every answer, with the git commit, in PostgreSQL (step 14).

    uv run python scripts/run_t2sql_eval.py experiments/t2sql/with_ontology.toml            # dev questions
    uv run python scripts/run_t2sql_eval.py experiments/t2sql/with_ontology.toml -q A01 M05 # some questions
    uv run python scripts/run_t2sql_eval.py experiments/t2sql/final.toml --test             # once, at the end
    uv run python scripts/run_t2sql_eval.py final.toml --final                # the sealed set, once (step 23)
    uv run python scripts/run_t2sql_eval.py experiments/t2sql/roles.toml --role all   # the dev set per role (step 29)
    uv run python scripts/run_t2sql_eval.py --rescore 2 3     # re-score stored answers with the current scoring code

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
from text2sql_calorvia import access
from text2sql_calorvia.agent import Agent
from text2sql_calorvia.config import settings
from text2sql_calorvia.evaluation import judge, load_final_questions, load_questions, score, sql_counts, verdict
from text2sql_calorvia.role_evaluation import score_for_role
from text2sql_calorvia.sources import load_sql


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("config", type=Path, nargs="?")
    parser.add_argument("--rescore", type=int, nargs="*", help="experiment ids: re-score their stored answers")
    parser.add_argument("-q", "--questions", nargs="*", help="question ids (default: the whole split)")
    parser.add_argument("--test", action="store_true", help="the held-out test questions (run once, step 16)")
    parser.add_argument("--final", action="store_true", help="the sealed final test set (run once, step 23)")
    parser.add_argument("--role", nargs="+", help="run under these roles, or `all` (step 29); one experiment each")
    args = parser.parse_args()
    if args.rescore:
        return rescore(args.rescore)
    config = tomllib.loads(args.config.read_text())
    split = "final" if args.final else "test" if args.test else "dev"
    pool = load_final_questions() if args.final else load_questions(split=split)
    questions = [q for q in pool if not args.questions or q["id"] in args.questions]
    commit, dirty = git_state()
    if args.final:
        check_final_run_allowed(args.questions, args.test, dirty)
    # Memory off: an evaluation must not depend on what someone asked the agent to remember (step 15)
    agent = Agent(**{"use_memory": False, **config.get("agent", {})})
    judge_client = OpenAI(base_url=settings.llm_url, api_key="local")

    if args.final and args.role:
        raise SystemExit("--final runs without a role: the sealed set is not run again")
    roles = list(access.roles()) if args.role == ["all"] else args.role or [None]
    if unknown := set(roles) - set(access.roles()) - {None}:
        raise SystemExit(f"unknown roles: {sorted(unknown)}")
    with psycopg.connect(settings.postgres_url, autocommit=True) as db:
        db.execute(load_sql("eval/schema"))
        for role in roles:
            await run(db, agent, judge_client, config, split, questions, commit, dirty, role)


async def run(db, agent, judge_client, config, split, questions, commit, dirty, role):
    """One experiment: every question, under one role or (role None) with no limit."""
    name = f"{config['name']}:{role}" if role else config["name"]
    stored = {**config, "name": name, **({"role": role} if role else {})}
    experiment = db.execute(load_sql("eval/start"), (name, json.dumps(stored), split, commit, dirty, commit)).fetchone()[0]
    print(f"experiment {experiment}: {name}, {len(questions)} {split} questions, commit {commit[:7]}"
          f"{' (dirty: not for the report)' if dirty else ''}", flush=True)
    for q in questions:
        start, error = time.perf_counter(), None
        # A new token per question: one lasts 15 minutes, a whole run much longer
        identity = {"access_token": access.issue_token(role, "evaluation")} if role else {}
        try:
            result = await agent.ask([{"role": "user", "content": q["question"]}], f"eval-{experiment}-{q['id']}", **identity)
        except Exception as e:   # one failure must not stop the run; it is stored and counted
            result, error = {"answer": "", "steps": []}, f"{type(e).__name__}: {e}"
        seconds = time.perf_counter() - start
        judged = judge(q["question"], result["answer"], judge_client) if result["answer"] else {"label": "error", "why": error}
        if role:
            scored = score_for_role(q, role, result["answer"], judged["label"], result["steps"])
            ok, where = scored["ok"] and not error, f"{scored['reach']:7} "
        else:
            scored = score(q, result["answer"])
            ok, where = verdict(q, scored, judged["label"], result["answer"]) and not error, ""
        counts = sql_counts(result["steps"])
        db.execute(load_sql("eval/result"), (
            experiment, q["id"], q["category"], q["behavior"], judged["label"], judged.get("why"), ok,
            json.dumps(scored["missing"]), json.dumps(scored["leaked"]), seconds, counts["tool_calls"],
            counts["queries"], counts["refused"], counts["exec_errors"], error, result["answer"],
            json.dumps(result["steps"], ensure_ascii=False, default=str)))
        print(f"{q['id']} {'OK  ' if ok else 'MISS'} {where}{q['behavior']:7} → {judged['label']:7} {seconds:6.1f} s  "
              f"{counts['queries']} queries ({counts['refused']} refused, {counts['exec_errors']} errors)  "
              f"missing={scored['missing']} leaked={scored['leaked']}{' ERROR ' + error if error else ''}", flush=True)
    db.execute(load_sql("eval/finish"), (experiment,))
    print(f"done: experiment {experiment}", flush=True)


def check_final_run_allowed(selected, test, dirty):
    """The sealed set is run whole, from a clean commit, and only once."""
    if selected or test or dirty:
        raise SystemExit("--final runs the whole set from a clean tree, without -q or --test")
    with psycopg.connect(settings.postgres_url, autocommit=True) as db:
        db.execute(load_sql("eval/schema"))
        runs = [row[0] for row in db.execute(load_sql("eval/final_runs")).fetchall()]
    if runs:
        raise SystemExit(f"the sealed set has already been run (experiment {runs[0]})")


def rescore(experiments):
    """Score stored answers again (scores and judge), without asking the agent again."""
    commit, dirty = git_state()
    if dirty:
        raise SystemExit("commit the scoring code first: the experiment keeps the scorer's commit")
    questions = {q["id"]: q for q in load_questions(split="all") + load_final_questions()}
    judge_client = OpenAI(base_url=settings.llm_url, api_key="local")
    with psycopg.connect(settings.postgres_url, autocommit=True) as db:
        db.execute(load_sql("eval/schema"))
        for experiment in experiments:
            if db.execute(load_sql("eval/experiment_role"), (experiment,)).fetchone()[0]:
                raise SystemExit(f"experiment {experiment} ran under a role: its scoring depends on the steps")
            for qid, answer, error in db.execute(load_sql("eval/answers"), (experiment,)).fetchall():
                q = questions[qid]
                scored = score(q, answer)
                judged = judge(q["question"], answer, judge_client) if answer else {"label": "error", "why": error}
                ok = verdict(q, scored, judged["label"], answer) and not error
                db.execute(load_sql("eval/rescore"), (judged["label"], judged.get("why"), ok, json.dumps(scored["missing"]),
                                                      json.dumps(scored["leaked"]), experiment, qid))
                print(f"{experiment} {qid} {'OK  ' if ok else 'MISS'} {q['behavior']:7} → {judged['label']:7} "
                      f"missing={scored['missing']}", flush=True)
            db.execute(load_sql("eval/rescored"), (commit, experiment))


if __name__ == "__main__":
    asyncio.run(main())
