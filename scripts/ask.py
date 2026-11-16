"""Ask one question from the terminal: the answer, the chunks it used and their scores.

Usage:
  uv run python scripts/ask.py "Quand le nouvel ERP démarre-t-il ?"
  uv run python scripts/ask.py --id Q013 --full
"""
import argparse
import sys
import tomllib
import warnings

from rag_calorvia.evaluation.dataset import is_test, load_questions
from rag_calorvia.rag.pipeline import answer, retrieve

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("question", nargs="?", help="the question (or use --id)")
parser.add_argument("--id", help="a question of the eval set, e.g. Q013: also shows the expected answer")
parser.add_argument("--config", default="experiments/baseline.toml", help="experiment TOML (default: baseline)")
parser.add_argument("--full", action="store_true", help="show the whole text of each chunk")
parser.add_argument("--retrieve-only", action="store_true", help="chunks only, no generation")
args = parser.parse_args()

warnings.filterwarnings("ignore", message="Api key is used with an insecure connection")  # local Qdrant, plain http

expected = None
if args.id:
    if is_test(args.id):
        sys.exit(f"{args.id} is in the held-out test set: not before the final evaluation")
    item = next((q for q in load_questions("dev") if q["id"] == args.id), None)
    if item is None:
        sys.exit(f"unknown question id: {args.id}")
    question, expected = item["question"], f"[{item['type']}] {item['answer']}"
elif args.question:
    question = args.question
else:
    parser.error("give a question or --id")

with open(args.config, "rb") as f:
    config = tomllib.load(f)
result = retrieve(question, config) if args.retrieve_only else answer(question, config)

print(f"Question : {question}")
if expected:
    print(f"Expected : {expected}")
if not args.retrieve_only:
    print(f"Answer   : {result['answer']}")

print(f"\nChunks ({config['name']}):")
for rank, chunk in enumerate(result["chunks"], 1):
    rerank_score = f"{chunk['rerank_score']:.3f}" if "rerank_score" in chunk else "  –  "
    print(f"[{rank}] rerank {rerank_score} · search {chunk['search_score']:.3f} · {chunk['document']} #{chunk['chunk_index']}")
    lines = chunk["text"].splitlines()
    if not args.full:  # one line: headings and text, without the context line (the document name is shown above)
        body = lines[1:] if lines[0].startswith("[") else lines
        lines = [" / ".join(body)[:160]]
    print("\n".join(f"      {line}" for line in lines))

if not args.retrieve_only:
    from rag_calorvia.rag.images import answer_images
    for path, page in answer_images(result["answer"], result["context"]):
        print(f"\nimage to show: {path}" + (f", page {page + 1}" if page is not None else ""))

for call in result.get("tool_calls", []):
    print(f"\ntool {call['tool']}({call['arguments']})\n  -> {call['result'][:300]}")

timings = " · ".join(f"{name.removesuffix('_ms')} {ms:.0f} ms" for name, ms in result["timings"].items())
tokens = "" if args.retrieve_only else f" · {result['prompt_tokens']} + {result['completion_tokens']} tokens"
print(f"\n{timings}{tokens}")
