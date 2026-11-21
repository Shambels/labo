"""Why a run's answers lost points: each question below full correctness, sorted into one cause (step 41).

A mean says how much was lost, not where. Each answer the judge scored below 1 falls in the first cause that fits:

  refusal      "Je ne sais pas." while the eval set has an answer
  not_found    no chunk of the first evidence document reached the context: a retrieval problem
  wrong        correctness <= 0.3 with the evidence in the context: the generator misread or picked the wrong extract
  incomplete   the evidence was there and the judge says facts are missing: the answer stopped at the core fact
  other        anything else (a contradiction, an extra claim)

For `incomplete`, `detail_in_context` counts how many of the expected answer's numbers the context holds: when they are
there, the generator had the details and left them out.

    uv run python scripts/analyse_misses.py 199
"""
import argparse
import re
from collections import Counter

from rag_calorvia import db
from rag_calorvia.evaluation.runner import eval_questions, split_of

REFUSAL = "Je ne sais pas"
MISSING = re.compile(r"\b(fails? to (include|mention|provide)|missing|omits?|lacks?)\b", re.I)
NUMBER = re.compile(r"\d[\d  ,.]*\d|\d")


def numbers(text):
    """The numbers of a text, spaces and thousands separators removed: '13 500 k€' -> '13500'."""
    return {re.sub(r"[  ]", "", n).rstrip(".,") for n in NUMBER.findall(text or "")}


def cause(question, answer, chunks, correctness, reason):
    evidence = question["evidence"][0]["document"] if question.get("evidence") else None
    if (answer or "").strip().startswith(REFUSAL) and question.get("answer"):
        return "refusal"
    if evidence and not any(chunk.get("document") == evidence for chunk in chunks):
        return "not_found"
    if correctness <= 0.3:
        return "wrong"
    if MISSING.search(reason or ""):
        return "incomplete"
    return "other"


def analyse(experiment_id):
    with db.connect(read_only=True) as conn:
        _, name, config, _ = db.load_experiment(conn, experiment_id)
        questions = {q["id"]: q for q in eval_questions(conn, split_of(config))}
        answers = db.load_answers(conn, experiment_id)
        rows = conn.execute("SELECT question_id, value, reason FROM scores WHERE experiment_id = %s "
                            "AND metric = 'correctness' AND value IS NOT NULL", (experiment_id,)).fetchall()
    misses = []
    for qid, value, reason in sorted(rows, key=lambda r: (r[1], r[0])):
        if value >= 1 or qid not in answers:
            continue
        chunks, answer = answers[qid]
        question = questions[qid]
        context = "\n".join(chunk.get("text") or "" for chunk in chunks)
        expected = numbers(question.get("answer")) - numbers(question["question"])
        missing = expected - numbers(answer)
        misses.append({"id": qid, "type": question["type"], "correctness": value,
                       "cause": cause(question, answer, chunks, value, reason),
                       "answer_words": len((answer or "").split()), "expected_words": len(question["answer"].split()),
                       "missing_numbers": len(missing), "detail_in_context": len(missing & numbers(context))})
    return name, len(rows), misses


parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("experiment", type=int)
args = parser.parse_args()

name, judged, misses = analyse(args.experiment)
print(f"run {args.experiment} ({name}): {len(misses)} of {judged} judged answers below 1")
print(f"{'id':6} {'type':16} {'corr':>5} {'cause':11} {'words':>9} {'numbers missing / in context':>29}")
for m in misses:
    print(f"{m['id']:6} {m['type']:16} {m['correctness']:5.1f} {m['cause']:11} "
          f"{m['answer_words']:>4}/{m['expected_words']:<4} {m['missing_numbers']:>14} / {m['detail_in_context']}")
causes = Counter(m["cause"] for m in misses)
lost = Counter()
for m in misses:
    lost[m["cause"]] += 1 - m["correctness"]
print("\ncauses: " + ", ".join(f"{c} {n} (-{lost[c]:.1f})" for c, n in causes.most_common()))
words = [m["answer_words"] / max(m["expected_words"], 1) for m in misses if m["cause"] == "incomplete"]
if words:
    print(f"incomplete answers are {sum(words) / len(words):.0%} of the expected answer's length on average")
