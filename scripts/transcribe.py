"""Transcribe every image, scanned page and embedded chart of the indexed corpus with the VLM, once (cached).

Needs the VLM on VLM_URL. Usage: uv run python scripts/transcribe.py [--only images|scans|embedded] [--limit N] [--prompt v2]
"""
import argparse
import logging

from rag_calorvia import db
from rag_calorvia.etl.vision import PROMPTS, transcription, targets_of
from rag_calorvia.logs import setup_logging

KINDS = {"images": "image", "scans": "scan_page", "embedded": "embedded"}

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("--only", choices=KINDS, help="one kind of target")
parser.add_argument("--limit", type=int, help="at most N targets (to try the prompt on a few first)")
parser.add_argument("--prompt", choices=PROMPTS, default="v1", help="which prompt (step 35: v2 also copies the text on links)")
args = parser.parse_args()
setup_logging()
logger = logging.getLogger("transcribe")

with db.connect(read_only=True) as conn:
    documents = db.load_vision_documents(conn)
targets = [t for d in documents for t in targets_of(d) if not args.only or t.kind == KINDS[args.only]]
targets = targets[:args.limit] if args.limit else targets

total, computed = 0.0, 0
for i, target in enumerate(targets, 1):
    cached = transcription(target, prompt=PROMPTS[args.prompt], compute=False) is not None
    record = transcription(target, prompt=PROMPTS[args.prompt])
    if not cached:
        computed += 1
        total += record["seconds"]
    where = f" p.{target.page + 1}" if target.page is not None else ""
    logger.info("[%d/%d] %s%s %s %.1f s", i, len(targets), target.path, where, "cached" if cached else "new", record["seconds"])
print(f"{len(targets)} targets, {computed} transcribed now in {total:.0f} s "
      f"({total / computed:.1f} s each)" if computed else f"{len(targets)} targets, all cached")
