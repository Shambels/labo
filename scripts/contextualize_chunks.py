"""Write the context sentence of every chunk of a configuration, once, into data/contexts/ (step 41).

Needs the generator (its served name is the config's [generation] model). Run it before indexing a configuration with
[chunking] contextual = true: the indexing only reads the cache. Chunks are done document by document, so the
server's prompt cache holds each document while its chunks are done.

    uv run python scripts/contextualize_chunks.py experiments/combined_contextual.toml
"""
import argparse
import copy
import time
import tomllib

from rag_calorvia.etl.chunk import chunk_corpus
from rag_calorvia.etl.contextual import MAX_DOCUMENT_CHARS, context
from rag_calorvia.etl.documents import body_of, by_document, document_text
from rag_calorvia.logs import setup_logging

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("config", help="experiment TOML file")
args = parser.parse_args()
setup_logging()

with open(args.config, "rb") as f:
    config = tomllib.load(f)
plain = copy.deepcopy(config)
plain["chunking"].pop("contextual", None)   # the chunks themselves, before their context
has_line, model = config["chunking"]["context_line"], config["generation"]["model"]
documents = by_document(chunk_corpus(plain))
total, done, start = sum(len(m) for m in documents.values()), 0, time.time()
for document, members in documents.items():
    whole = document_text(members, has_line, MAX_DOCUMENT_CHARS)
    for chunk in members:
        context(document, whole, body_of(chunk, has_line), model, compute=True)
        done += 1
        if done % 50 == 0 or done == total:
            print(f"{done}/{total} chunks ({time.time() - start:.0f} s)", flush=True)
