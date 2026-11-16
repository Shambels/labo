"""Chunk and index the corpus for one or more configurations (the inventory must have run first).

Needs the embedder. Usage: uv run python scripts/index.py experiments/baseline.toml [experiments/other.toml ...] [--force]
"""
import argparse
import tomllib

from rag_calorvia.etl.index import index_corpus
from rag_calorvia.logs import setup_logging

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("configs", nargs="+", help="experiment TOML files")
parser.add_argument("--force", action="store_true", help="rebuild the collections even if they are complete")
args = parser.parse_args()
setup_logging()

for path in args.configs:
    with open(path, "rb") as f:
        config = tomllib.load(f)
    stats = index_corpus(config, force=args.force)
    print(f"{path}: {stats['collection']} — {stats['chunks']} chunks, "
          f"{'indexed in %.1f s' % stats['seconds'] if stats['created'] else 'already indexed'}")
