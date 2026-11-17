"""Run the hand-written SQL of the 12 starter questions and check it against the presentation's answers.

    uv run python scripts/run_starter.py          # summary
    uv run python scripts/run_starter.py -v       # with the rows each query returns
"""
import argparse

from text2sql_calorvia.starter import check, load_questions, starter_queries


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    questions, queries = load_questions(), starter_queries()
    passed = 0
    for number, (question, sources, expected) in sorted(questions.items()):
        results, missing, seconds = check(number, expected, queries[number])
        passed += not missing
        status = "OK  " if not missing else f"MISS {missing}"
        print(f"Q{number:02d} {status} {seconds * 1000:5.0f} ms  [{sources}] {question}")
        if args.verbose or missing:
            print(f"     expected: {expected}")
            for name, columns, rows in results:
                print(f"     {name}: {columns}")
                for row in rows[:10]:
                    print(f"       {row}")
    print(f"\n{passed}/{len(questions)} questions answered as expected")


if __name__ == "__main__":
    main()
