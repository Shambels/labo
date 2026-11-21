"""Build the documents' semantic layer, knowledge/entities.json (step 41): extract, merge, review.

Extraction needs the generator and is cached in data/entities/ (one LLM call per document, about 2 h the first
time); merging and the review (knowledge/entities_review.yaml) run in a second, so the review can be edited and the
script re-run.

    uv run python scripts/build_entities.py experiments/combined_entities.toml
"""
import argparse
import json
import time
import tomllib
from pathlib import Path

import yaml

from rag_calorvia import db
from rag_calorvia.etl.chunk import chunk_corpus
from rag_calorvia.etl.documents import by_document, document_text
from rag_calorvia.etl.entities import MAX_DOCUMENT_CHARS, apply_review, document_entities, merge_entities
from rag_calorvia.logs import setup_logging

OUTPUT, REVIEW = Path("knowledge/entities.json"), Path("knowledge/entities_review.yaml")

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("config", help="experiment TOML file: its chunks are the documents' text")
parser.add_argument("--no-compute", action="store_true", help="merge what is cached; never call the LLM")
args = parser.parse_args()
setup_logging()

with open(args.config, "rb") as f:
    config = tomllib.load(f)
config["chunking"].pop("contextual", None)   # the documents as written, without the context sentences
documents = by_document(chunk_corpus(config))
found, start = {}, time.time()
for i, (document, members) in enumerate(documents.items(), 1):
    entities = document_entities(document, document_text(members, config["chunking"]["context_line"], MAX_DOCUMENT_CHARS),
                                 config["generation"]["model"], compute=not args.no_compute)
    if entities is not None:
        found[document] = entities
    if i % 20 == 0 or i == len(documents):
        print(f"{i}/{len(documents)} documents ({time.time() - start:.0f} s)", flush=True)

with db.connect(read_only=True) as conn:
    dates = {d["path"]: d["doc_date"].isoformat() if d["doc_date"] else None
             for d in db.load_indexable_documents(conn) + db.load_vision_documents(conn)}
merged = merge_entities(found, dates)
review = yaml.safe_load(REVIEW.read_text(encoding="utf-8")) if REVIEW.exists() else {}
entities = apply_review(merged, review)
OUTPUT.write_text(json.dumps(entities, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
print(f"{sum(map(len, found.values()))} mentions in {len(found)} documents -> {len(merged)} entities, "
      f"{len(entities)} after the review -> {OUTPUT}")
