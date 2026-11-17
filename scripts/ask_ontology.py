"""Ask auto-ontology the 12 starter questions and check its answers: the certification loop of step 12.

    uv run python scripts/ask_ontology.py before           # every question, saved as data/ontology_runs/before.json
    uv run python scripts/ask_ontology.py after -q 5 6     # only some questions

Each run keeps the answer, the SQL auto-ontology wrote, its rows and the time taken; the check is the same as
for our hand-written SQL (every number and date of the expected answer among the returned values or the prose).
Questions and answers come from the course material at run time (D42); data/ is git-ignored.
"""
import argparse
import json
import re
import time
from datetime import date
from decimal import Decimal
from pathlib import Path

import requests
from dotenv import dotenv_values

from text2sql_calorvia.starter import expected_tokens, load_questions, matches, result_values

URL = "http://localhost:3000/api/chat/completions"
OUT = Path("data/ontology_runs")


def ask(question, token, timeout=1800):
    """One question through the chat API (server-sent events). Returns the final answer, or the error."""
    start = time.perf_counter()
    answer, error, steps = None, None, []
    with requests.post(URL, headers={"x-api-key": token}, json={"question": question},
                       stream=True, timeout=timeout) as response:
        response.raise_for_status()
        for line in response.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data:"):
                continue
            payload = line.removeprefix("data:").strip()
            if payload == "[DONE]":
                break
            event = json.loads(payload)
            if event["type"] == "step" and event.get("phase") == "end":
                steps.append(event.get("node"))
            elif event["type"] == "result":
                answer = event["answer"]
            elif event["type"] == "error":
                error = event.get("message")
    return {"answer": answer, "error": error, "steps": steps, "seconds": round(time.perf_counter() - start, 1)}


def prose_numbers(text):
    """Numbers and dates written in the prose answer, read like the expected answers (French: '1 278 366,78',
    '9,4 %', '13, 14 et 17' as three numbers), plus English decimals ('9.4') and ISO dates."""
    text = text or ""
    values = set(expected_tokens(text))
    values |= {Decimal(m) for m in re.findall(r"(?<![\d.,])\d+\.\d+(?![\d.,])", text)}
    values |= {date.fromisoformat(m) for m in re.findall(r"\b\d{4}-\d{2}-\d{2}\b", text)}
    return values


def _typed(value):
    if isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}(T.*| .*)?", value):
        return date.fromisoformat(value[:10])
    if isinstance(value, float):
        return Decimal(repr(value))
    if isinstance(value, str) and re.fullmatch(r"-?\d+(\.\d+)?", value):
        return Decimal(value)
    return value


def check(expected, result):
    """Missing tokens of the expected answer, looking in the rows and in the prose."""
    answer = result["answer"] or {}
    raw = answer.get("sql_response_from_db") or []
    # The API sends the result as a list holding one JSON string of records
    records = []
    for item in raw if isinstance(raw, list) else [raw]:
        if isinstance(item, str) and item.lstrip().startswith("["):
            records += json.loads(item)
        else:
            records.append(item)
    rows = [list(r.values()) if isinstance(r, dict) else (r if isinstance(r, list) else [r]) for r in records]
    # The API sends dates and numbers as JSON: ISO strings and floats. Back to date / Decimal for the check.
    rows = [[_typed(v) for v in row] for row in rows]
    values = result_values(rows) | prose_numbers(answer.get("response"))
    return [str(t) for t in expected_tokens(expected) if not matches(t, values)]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("label", help="name of this run, e.g. before or after_ebitda")
    parser.add_argument("-q", "--questions", type=int, nargs="*", help="question numbers (default: all 12)")
    parser.add_argument("--recheck", action="store_true", help="re-score a saved run without asking again")
    args = parser.parse_args()
    if args.recheck:
        path = OUT / f"{args.label}.json"
        runs, questions = json.loads(path.read_text()), load_questions()
        for number, result in sorted(runs.items(), key=lambda kv: int(kv[0])):
            result["missing"] = check(questions[int(number)][2], result)
            result["ok"] = not result["missing"] and not result["error"]
            print(f"Q{int(number):02d} {'OK  ' if result['ok'] else 'MISS'} missing={result['missing']}")
        path.write_text(json.dumps(runs, ensure_ascii=False, indent=1, default=str))
        print(f"{sum(r['ok'] for r in runs.values())}/{len(runs)} answered as expected")
        return
    token = dotenv_values(".env")["AUTO_ONTOLOGY_API_TOKEN"]
    questions = load_questions()
    OUT.mkdir(parents=True, exist_ok=True)
    out_path = OUT / f"{args.label}.json"
    runs = json.loads(out_path.read_text()) if out_path.exists() else {}
    for number in args.questions or sorted(questions):
        question, sources, expected = questions[number]
        result = ask(question, token)
        result["missing"] = check(expected, result)
        result["ok"] = not result["missing"] and not result["error"]
        runs[str(number)] = result
        out_path.write_text(json.dumps(runs, ensure_ascii=False, indent=1, default=str))
        answer = result["answer"] or {}
        print(f"Q{number:02d} {'OK  ' if result['ok'] else 'MISS'} {result['seconds']:6.1f} s  "
              f"missing={result['missing']} error={result['error']}")
        print(f"     answer: {(answer.get('response') or '')[:200]!r}")
        print(f"     sql: {(answer.get('sql_code') or '').strip()[:300]!r}")
    done = [r for r in runs.values() if r.get("ok")]
    print(f"\n{len(done)}/{len(runs)} answered as expected ({out_path})")


if __name__ == "__main__":
    main()
