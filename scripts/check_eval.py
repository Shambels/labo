"""The ceiling of the dev set: which questions can be answered from the text documents, before any search.

    uv run python scripts/check_eval.py            # per question type
    uv run python scripts/check_eval.py --details  # plus every evidence item that is not found
"""
import argparse
from collections import Counter, defaultdict
from functools import cache

from rag_calorvia import db
from rag_calorvia.etl.convert import load_conversion
from rag_calorvia.evaluation.coverage import evidence_status, question_coverage
from rag_calorvia.evaluation.dataset import align_with_registry, load_questions


@cache
def document_text(path):
    """The whole converted text of a document: Markdown keeps the tables, the plain export the rest."""
    converted = load_conversion(path)
    return "" if converted is None else converted.export_to_markdown() + "\n" + converted.export_to_text()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--details", action="store_true", help="list the evidence items that are not found")
    args = parser.parse_args()

    with db.connect(read_only=True) as conn:
        registry = db.load_registry(conn)
    questions = align_with_registry(load_questions("dev"), registry)

    per_type = defaultdict(lambda: [0, 0, Counter()])  # reachable, total, statuses
    for question in questions:
        if not question["evidence"]:
            continue
        reachable, statuses = question_coverage(question, registry, document_text)
        row = per_type[question["type"]]
        row[0] += reachable
        row[1] += 1
        row[2] += statuses
        if args.details and not reachable:
            for e in question["evidence"]:
                status = evidence_status(e, registry, document_text)
                if e["grade"] == 2 and status != "found":
                    print(f"{question['id']} {status:12} {e['document']}  {e['snippets']}")

    statuses = ["found", "needs_vision", "not_in_text", "excluded", "missing"]
    print(f"\n{'type':20} {'reachable':>10}   " + " ".join(f"{s:>12}" for s in statuses))
    totals = [0, 0, Counter()]
    for kind in sorted(per_type):
        reachable, total, counts = per_type[kind]
        totals[0] += reachable
        totals[1] += total
        totals[2] += counts
        print(f"{kind:20} {reachable:>4} / {total:<4}   " + " ".join(f"{counts[s]:>12}" for s in statuses))
    print(f"{'all':20} {totals[0]:>4} / {totals[1]:<4}   " + " ".join(f"{totals[2][s]:>12}" for s in statuses))


if __name__ == "__main__":
    main()
