"""Cross-source reconciliation in Python: there is no join between SQL Server and PostgreSQL.

The agent runs one query per source; each result is kept under an id (q1, q2...). `reconcile` then matches the
rows of two results on a key, after normalizing it the same way on both sides (a VAT number or a staff number is
not written the same in every database), and compares numeric columns. The model only names the results and the
columns: the rows never pass through it, so it cannot mistype a number while copying them.
"""
import re
from collections import defaultdict

from text2sql_calorvia.values import compact, normalize

MAX_LISTED = 30   # rows listed per category; counts and totals always cover everything


def key_vat(value):
    """'BE 0236.099.757', 'be0236099757' -> 'BE0236099757'."""
    return compact(value).upper()


def key_staff_number(value):
    """'M10405', '10405', 10405, 'm010405' -> '10405' (the ERP drops payroll's M prefix)."""
    digits = re.sub(r"\D", "", str(value))
    return str(int(digits)) if digits else ""


def key_text(value):
    """Case, accents and punctuation ignored: 'Distrinergie S.A.' -> 'distrinergie sa'."""
    return re.sub(r"[^a-z0-9 ]", "", normalize(value)).strip()


def key_exact(value):
    return str(value).strip()


KEY_TYPES = {"vat": key_vat, "staff_number": key_staff_number, "text": key_text, "exact": key_exact}


def _number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _column(result, name, side):
    lowered = [c.lower() for c in result["columns"]]
    if name.lower() not in lowered:
        raise ValueError(f"Colonne {name} absente du résultat {side} (colonnes : {', '.join(result['columns'])}).")
    return lowered.index(name.lower())


def reconcile(left: dict, right: dict, left_key: str, right_key: str, key_type: str = "exact",
              compare: list[list[str]] | None = None, tolerance: float = 0.01) -> dict:
    """Match two query results ({columns, rows}) on a normalized key and compare numeric columns.

    compare: pairs [left column, right column]; a matched row whose values differ by more than `tolerance`
    is reported. Rows sharing a key on one side are summed first (an amount per invoice line becomes one per key).
    """
    if key_type not in KEY_TYPES:
        raise ValueError(f"key_type inconnu : {key_type}. Types : {', '.join(KEY_TYPES)}.")
    normalize_key = KEY_TYPES[key_type]
    compare = compare or []
    lk, rk = _column(left, left_key, "gauche"), _column(right, right_key, "droit")
    pairs = [(_column(left, a, "gauche"), _column(right, b, "droit")) for a, b in compare]

    def group(result, key_index, value_indexes):
        groups = defaultdict(lambda: {"raw": None, "rows": 0, "sums": [0.0] * len(value_indexes)})
        for row in result["rows"]:
            key = normalize_key(row[key_index]) if row[key_index] is not None else ""
            g = groups[key]
            g["raw"] = g["raw"] if g["raw"] is not None else row[key_index]
            g["rows"] += 1
            for i, vi in enumerate(value_indexes):
                g["sums"][i] += _number(row[vi]) or 0.0
        return groups

    lg = group(left, lk, [a for a, _ in pairs])
    rg = group(right, rk, [b for _, b in pairs])
    matched = sorted(set(lg) & set(rg) - {""})
    only_left = sorted(set(lg) - set(rg))
    only_right = sorted(set(rg) - set(lg))

    differences = []
    for key in matched:
        diffs = {}
        for i, (a, b) in enumerate(compare):
            lv, rv = lg[key]["sums"][i], rg[key]["sums"][i]
            if abs(lv - rv) > tolerance:
                diffs[f"{a} - {b}"] = round(lv - rv, 2)
        if diffs:
            differences.append({"key": key, "left_key": lg[key]["raw"], "right_key": rg[key]["raw"], **diffs})

    totals = {}
    for i, (a, b) in enumerate(compare):
        lt, rt = sum(g["sums"][i] for g in lg.values()), sum(g["sums"][i] for g in rg.values())
        totals[f"{a} / {b}"] = {"left": round(lt, 2), "right": round(rt, 2), "difference": round(lt - rt, 2),
                                "left_matched": round(sum(lg[k]["sums"][i] for k in matched), 2),
                                "right_matched": round(sum(rg[k]["sums"][i] for k in matched), 2)}

    def listed(keys, groups, names):
        return [{"key": k, "value": groups[k]["raw"], "rows": groups[k]["rows"],
                 **{name: round(groups[k]["sums"][i], 2) for i, name in enumerate(names)}}
                for k in keys[:MAX_LISTED]]

    return {
        "key_type": key_type,
        "matched": len(matched), "only_left": len(only_left), "only_right": len(only_right),
        "differences": len(differences),
        "totals": totals,
        "difference_rows": differences[:MAX_LISTED],
        "only_left_rows": listed(only_left, lg, [a for a, _ in compare]),
        "only_right_rows": listed(only_right, rg, [b for _, b in compare]),
        "listed_up_to": MAX_LISTED,
    }
