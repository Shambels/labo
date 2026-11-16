"""Build the registry of the corpus: convert the text documents (once), describe every file, save to PostgreSQL.

    uv run python scripts/inventory.py             # convert what is missing, then inventory
    uv run python scripts/inventory.py --force     # convert everything again
"""
import argparse
import logging

from rag_calorvia import db
from rag_calorvia.etl.convert import DOCLING_FORMATS, convert_documents, file_format
from rag_calorvia.etl.inventory import as_rows, build_inventory, corpus_files
from rag_calorvia.logs import setup_logging

logger = logging.getLogger("inventory")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--force", action="store_true", help="convert every document again")
    args = parser.parse_args()
    setup_logging()

    to_convert = [p for p in corpus_files() if file_format(p) in DOCLING_FORMATS]
    failures = convert_documents(to_convert, force=args.force)
    if failures:
        raise SystemExit(f"{len(failures)} conversions failed: {failures}")

    documents = build_inventory()
    with db.connect() as conn:
        db.create_tables(conn)
        db.save_documents(conn, as_rows(documents))
        summary = db.inventory_summary(conn)

    print(f"{'format':8} {'files':>6} {'indexed':>8} {'dup':>5} {'other':>6} {'scans':>6}")
    for fmt, files, indexed, duplicate, other, scans in summary:
        print(f"{fmt:8} {files:6} {indexed:8} {duplicate:5} {other:6} {scans:6}")
    print("\nExcluded:")
    for document in documents:
        if document.excluded_reason:
            target = f" -> {document.duplicate_of}" if document.duplicate_of else ""
            print(f"  {document.excluded_reason:14} {document.path}{target}")


if __name__ == "__main__":
    main()
