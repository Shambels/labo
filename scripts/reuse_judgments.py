"""Copy the judge's verdicts from one run to another for the questions whose answer and extracts are identical.

Step 40: generation is deterministic (temperature 0), so a change that touches a few questions leaves the others
word for word as they were: run 191 (combined_complete_top10 again) differs from run 187 on Q017 only. Judging the
127 again takes 40 minutes per run and only adds the judge's own noise to the comparison. The verdicts of identical
(answer, extracts) pairs are copied, and only the questions printed at the end need the judge.

Usage:
  uv run python scripts/reuse_judgments.py 192 --from 191
  uv run python scripts/judge_experiment.py 192 --questions $(uv run python scripts/reuse_judgments.py 192 --from 191 -q)
"""
import argparse
import sys

from rag_calorvia import db
from rag_calorvia.evaluation.judge import METRIC_NAMES

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("target", type=int, help="the run that gets the verdicts")
parser.add_argument("--from", dest="source", type=int, required=True, help="the judged run they come from")
parser.add_argument("-q", "--quiet", action="store_true", help="print only the ids of the questions left to judge")
args = parser.parse_args()


def same_extracts(a, b):
    """The same chunks, in the same order (the citations [n] refer to it), with the same text."""
    return [(c["document"], c["chunk_index"], c["text"]) for c in a] == [(c["document"], c["chunk_index"], c["text"]) for c in b]


with db.connect() as conn:
    target, source = db.load_answers(conn, args.target), db.load_answers(conn, args.source)
    if not target or not source:
        sys.exit("both runs must have stored answers")
    rows = conn.execute("SELECT question_id, question_type, metric, value, reason FROM scores "
                        "WHERE experiment_id = %s AND metric = ANY(%s)", (args.source, METRIC_NAMES)).fetchall()
    judged = {}
    for qid, qtype, metric, value, reason in rows:
        judged.setdefault(qid, []).append({"question_id": qid, "question_type": qtype, "metric": metric,
                                           "value": value, "reason": reason})
    copied, left = [], []
    for qid, (chunks, answer) in sorted(target.items()):
        if qid in source and answer == source[qid][1] and same_extracts(chunks, source[qid][0]) and qid in judged:
            db.insert_scores(conn, args.target, judged[qid])
            copied.append(qid)
        else:
            left.append(qid)
if args.quiet:
    print(" ".join(left))
else:
    print(f"run {args.target}: verdicts of {len(copied)} questions copied from run {args.source}; "
          f"{len(left)} to judge: {' '.join(left)}")
