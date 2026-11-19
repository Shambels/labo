"""Translate the Dutch and English chunks of a configuration to French, once, into data/translations/ (step 30g).

Needs the generator (its served name is the config's [generation] model). Run it before indexing a configuration with
[chunking] translate_to = "fr": the indexing only reads the cache.

    uv run python scripts/translate_chunks.py experiments/french_chunks.toml
"""
import argparse
import copy
import time
import tomllib

from rag_calorvia.etl.chunk import chunk_corpus
from rag_calorvia.etl.translate import needs_translation, split_context, translation
from rag_calorvia.logs import setup_logging

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("config", help="experiment TOML file")
args = parser.parse_args()
setup_logging()

with open(args.config, "rb") as f:
    config = tomllib.load(f)
untranslated = copy.deepcopy(config)
untranslated["chunking"].pop("translate_to", None)   # the chunks themselves, before their French version
chunks = [c for c in chunk_corpus(untranslated) if needs_translation(c)]
start, model = time.time(), config["generation"]["model"]
for i, chunk in enumerate(chunks, 1):
    _, body = split_context(chunk, config["chunking"]["context_line"])
    translation(body, model, compute=True)
    if i % 20 == 0 or i == len(chunks):
        print(f"{i}/{len(chunks)} chunks translated ({time.time() - start:.0f} s)", flush=True)
