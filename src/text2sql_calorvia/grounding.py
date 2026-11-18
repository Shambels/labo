"""Small figures of an answer, checked against query results (step 22, D71).

The check of agent.py covers numbers from 1 000 up, anywhere in the tool results. Below that, a number alone means
little (years, days, account numbers), and table cards and the prompt hold many small numbers, so being "somewhere" in
them proves nothing. Two kinds of small figure do say what they are, and are checked against results only:

- a count, a whole number followed by what it counts ("47 lignes", "12 écritures");
- a percentage, found in the results or computed from two of their numbers.

What this can't see: a number that is in the results but answers something else.
"""
import json
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Iterable

COUNTED = ("personnes?|employés?|salariés?|travailleurs?|clients?|fournisseurs?|commerciaux|commercial|factures?|"
           "avoirs?|commandes?|écritures?|lignes?|articles?|produits?|unités?|pièces?|expéditions?|livraisons?|"
           "réceptions?|contrats?|fiches?|départs?|embauches?|immobilisations?|mouvements?|ordres?|jours?|heures?")
COUNT = re.compile(rf"(?<![\d.,])(?<!\d[   ])(\d{{1,3}})(?![\d]|[.,]\d)\*{{0,2}}[   ]+\*{{0,2}}"
                   rf"(?:{COUNTED})\b", re.I)
PERCENT = re.compile(r"(?<![\d.,])(\d{1,3}(?:[.,]\d+)?)[   ]*%")
CODE = re.compile(r"```.*?```|`[^`]*`", re.S)
ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
MAX_FOR_COMBINATIONS = 40   # with more numbers than this, almost any value is some pair's sum or ratio
MAX_DATES = 10              # dates of one result compared with each other ("7 jours" between two deliveries)


def numeric_leaves(value) -> Iterable[float]:
    """Every number inside a result: cells, nested JSON, numeric text."""
    if isinstance(value, bool) or value is None:
        return
    if isinstance(value, (int, float, Decimal)):
        yield abs(float(value))
    elif isinstance(value, dict):
        for item in value.values():
            yield from numeric_leaves(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from numeric_leaves(item)
    elif isinstance(value, str):
        try:
            yield abs(float(Decimal(value.strip())))
        except (InvalidOperation, ValueError):
            pass


def tool_numbers(content: str) -> set[float]:
    try:
        return set(numeric_leaves(json.loads(content)))
    except ValueError:
        return set()


def result_numbers(result: dict) -> set[float]:
    """What a query result supports: its cells, its row count, each numeric column's total (a count split by site adds
    up to the count of the answer), and the days between its dates."""
    rows = result.get("rows") or []
    known = set(numeric_leaves(rows)) | {float(len(rows)), float(result.get("row_count") or 0)}
    for column in zip(*rows):
        values = [list(numeric_leaves(cell)) for cell in column]
        if all(len(v) == 1 for v in values if v) and any(values):
            known.add(round(sum(v[0] for v in values if v), 2))
    dates = sorted({str(cell)[:10] for row in rows for cell in row if ISO_DATE.match(str(cell))})
    if 2 <= len(dates) <= MAX_DATES:
        days = [date.fromisoformat(d) for d in dates]
        known |= {float(abs((a - b).days)) for a in days for b in days if a != b}
    return known


def _is_count(value: int, known: set[float]) -> bool:
    if value in known:
        return True
    return len(known) <= MAX_FOR_COMBINATIONS and any(a + b == value or abs(a - b) == value for a in known for b in known)


def _is_percent(text: str, known: set[float]) -> bool:
    value = float(text.replace(",", "."))
    decimals = len(text.replace(",", ".").partition(".")[2])
    margin = 0.5 * 10 ** -decimals + 1e-9
    close = lambda x: abs(abs(x) - value) <= margin  # noqa: E731
    if any(close(k) or close(k * 100) for k in known):
        return True
    if len(known) > MAX_FOR_COMBINATIONS:
        return True                                   # can't be told apart from chance: not flagged
    return any(close(a / b * 100) or close((a - b) / b * 100) for a in known for b in known if b)


def unsupported(answer: str, known: set[float], allowed: Iterable[int] = ()) -> list[str]:
    """The counts and percentages of the answer that the query results don't support, as written."""
    text = CODE.sub(" ", answer)
    known = {k for k in known if k}
    missing = [m.group(0).replace("*", "") for m in COUNT.finditer(text)
               if int(m.group(1)) >= 2 and int(m.group(1)) not in set(allowed)
               and not _is_count(int(m.group(1)), known)]
    missing += [m.group(0) for m in PERCENT.finditer(text) if not _is_percent(m.group(1), known)]
    return list(dict.fromkeys(missing))
