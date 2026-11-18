"""find_values: where does a name, a code or a number appear, and how exactly is it spelled?

The model never guesses spellings ("Distrinergie" vs "Distrinergie SA", "Aeris" vs "Aéris",
"BE0123456789" vs "BE 0123.456.789"). At first use, the distinct values of every readable text column of a
source are loaded in memory (a few tens of thousands); a search then compares them without case, accents
or punctuation, word by word, and with a tolerance for typos.
"""
import difflib
import re
import unicodedata
from functools import cache

from text2sql_calorvia import privacy
from text2sql_calorvia.catalog import describe, quote
from text2sql_calorvia.execution import run_unvalidated
from text2sql_calorvia.sources import SOURCES

TEXT_TYPES = ("char", "text")
MAX_VALUES_PER_COLUMN = 50_000


def normalize(text):
    """Lower case, no accents, single spaces: 'Aéris  12' -> 'aeris 12'."""
    text = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", text.lower()).strip()


def compact(text):
    """Letters and digits only: 'BE 0123.456.789' -> 'be0123456789'."""
    return re.sub(r"[^a-z0-9]", "", normalize(text))


@cache
def index(source):
    """[(table, column, value, normalized, compact)] for every distinct value of every readable text column."""
    engine = SOURCES[source].engine
    entries = []
    for t in describe(source):
        if not t["rows"]:
            continue
        skip = privacy.SENSITIVE.get(t["table_name"], set()) if source == "paie" else set()
        for c in t["columns"]:
            name = c["column_name"]
            if not c["readable"] or name in skip or not any(k in c["data_type"].lower() for k in TEXT_TYPES):
                continue
            col = f'"{name}"' if engine == "postgres" else f"[{name}]"
            sql = f"SELECT DISTINCT {col} FROM {quote(engine, t['table_schema'], t['table_name'])} WHERE {col} IS NOT NULL"
            _, rows, _ = run_unvalidated(source, sql, max_rows=MAX_VALUES_PER_COLUMN)
            entries += [(t["table_name"], name, r[0], normalize(r[0]), compact(r[0])) for r in rows]
    return entries


def find_values(source, value, table=None, column=None, limit=20, allowed_tables=None):
    """Matches of `value` in a source (optionally one table / column), best first.

    Exact > starts with > contains (also letters and digits only) > every word found > close spelling.
    allowed_tables: lower-case names the caller's role may read (None = all).
    """
    wanted, wanted_compact = normalize(value), compact(value)
    if not wanted:
        return {"matches": [], "note": "Valeur vide."}
    words = [w for w in re.split(r"[^a-z0-9]+", wanted) if len(w) >= 3]
    hits = []
    for tbl, col, raw, norm, comp in index(source):
        if (table and tbl.lower() != table.lower()) or (column and col.lower() != column.lower()) \
                or (allowed_tables is not None and tbl.lower() not in allowed_tables):
            continue
        if norm == wanted or (wanted_compact and comp == wanted_compact):
            rank = 0
        elif norm.startswith(wanted):
            rank = 1
        elif wanted in norm or (len(wanted_compact) >= 4 and wanted_compact in comp):
            rank = 2
        elif len(words) > 1 and all(w in norm for w in words):
            rank = 3
        else:
            continue
        hits.append((rank, len(norm), tbl, col, raw))
    match_type = ["exact", "starts_with", "contains", "all_words"]
    if not hits:
        # Typos: close values, then each word on its own (a first and a last name sit in two columns)
        candidates = {}
        for tbl, col, raw, norm, _ in index(source):
            if (table and tbl.lower() != table.lower()) or (column and col.lower() != column.lower()) \
                    or (allowed_tables is not None and tbl.lower() not in allowed_tables):
                continue
            candidates.setdefault(norm, []).append((tbl, col, raw))
        for norm in difflib.get_close_matches(wanted, list(candidates), n=limit, cutoff=0.75):
            hits += [(4, len(norm), tbl, col, raw) for tbl, col, raw in candidates[norm]]
        for word in words if len(words) > 1 else []:
            for norm in candidates:
                if norm == word or norm.startswith(word + " "):
                    hits += [(5, len(norm), tbl, col, raw) for tbl, col, raw in candidates[norm]]
        match_type += ["close_spelling", "one_word"]
    hits.sort()
    matches = [{"table": tbl, "column": col, "value": raw, "match": match_type[rank]}
               for rank, _, tbl, col, raw in hits[:limit]]
    return {"matches": matches, "truncated": len(hits) > limit}
