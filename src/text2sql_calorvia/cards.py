"""What the model reads before writing a query: the sources, their tables, and a card per table.

A card: description, readable columns with type and comment, keys, row count, a few example values, the
distinct values of code columns (with their label from PAR_CODE in the ERP), the rows of small code tables, the hidden
columns and why, and the ontology terms linked to the table (step 12). Built once per table, then cached.
"""
from functools import cache

from text2sql_calorvia import ontology, privacy
from text2sql_calorvia.catalog import quote
from text2sql_calorvia.execution import run_unvalidated
from text2sql_calorvia.sources import SOURCES
from text2sql_calorvia.validation import schema
from text2sql_calorvia.catalog import describe

# What each source is, in a sentence the model can use to pick one
DESCRIPTIONS = {
    "erp": "ERP GesPro 7 (SQL Server, dialecte T-SQL : TOP, GETDATE, DATEADD). Ventes (commandes, factures, avoirs), "
           "achats, réceptions, stock, production, logistique, articles, clients, fournisseurs, commerciaux. "
           "Janvier 2025 au 29 mai 2026.",
    "compta": "Comptabilité (PostgreSQL). Écritures et lignes (débit/crédit) par journal, plan comptable PCMN, tiers, "
              "budget 2026, immobilisations et amortissements, banque. Janvier 2025 à mai 2026.",
    "paie": "Paie (PostgreSQL). Travailleurs, contrats, prestations journalières (absences, télétravail), calculs et "
            "fiches de paie. Juin 2025 à mai 2026. Salaires : seulement agrégés sur au moins 5 personnes.",
}
CODE_MAX_DISTINCT = 25     # a text column with at most this many distinct values is listed as a code column
MAPPING_MAX_ROWS = 30      # a table this small, with several code columns, is shown row by row (step 21, D70)
TEXT_TYPES = ("char", "text")


@cache
def _tables(source):
    return {t["table_name"]: t for t in describe(source)}


def list_sources():
    return [{"source": s.name, "label": s.label, "engine": s.engine, "dialect": s.dialect,
             "tables": len(_tables(s.name)), "description": DESCRIPTIONS[s.name]} for s in SOURCES.values()]


def list_tables(source):
    return [{"table": name, "rows": t["rows"], "columns": len(t["columns"]), "description": t["comment"]}
            for name, t in _tables(source).items()]


@cache
def _par_code():
    """ERP code lists: {code type: {value: label}}."""
    _, rows, _ = run_unvalidated("erp", "SELECT COD_TYPE, COD_VAL, COD_LIB FROM PAR_CODE", max_rows=1000)
    lists = {}
    for code_type, value, label in rows:
        lists.setdefault(code_type, {})[value] = label
    return lists


def _labels(source, values):
    """The ERP code list whose values include all of these, if one does."""
    if source != "erp" or not values:
        return None, {}
    for code_type, labels in _par_code().items():
        if set(values) <= set(labels):
            return code_type, labels
    return None, {}


def _resolve(source, table):
    by_lower = {name.lower(): name for name in _tables(source)}
    return by_lower.get(table.lower())


@cache
def get_table_card(source, table):
    name = _resolve(source, table)
    if name is None:
        return {"error": f"Table inconnue dans {source} : {table}. Voir list_tables."}
    t = _tables(source)[name]
    engine = SOURCES[source].engine
    qname = quote(engine, t["table_schema"], name)
    readable = [c for c in t["columns"] if c["readable"]]
    no_sample = privacy.SENSITIVE.get(name, set()) | privacy.PERSONAL.get(name, set())
    if source != "paie":
        no_sample = set()

    # One query for the distinct counts of the text columns, then one per code column
    text_cols = [c["column_name"] for c in readable
                 if any(k in c["data_type"].lower() for k in TEXT_TYPES) and c["column_name"] not in no_sample]
    distinct = {}
    if text_cols and t["rows"]:
        q = lambda c: f'"{c}"' if engine == "postgres" else f"[{c}]"  # noqa: E731
        sql = "SELECT " + ", ".join(f"COUNT(DISTINCT {q(c)})" for c in text_cols) + f" FROM {qname}"
        _, rows, _ = run_unvalidated(source, sql, max_rows=1)
        distinct = dict(zip(text_cols, rows[0]))
    codes = {}
    for col, n in distinct.items():
        if 0 < n <= CODE_MAX_DISTINCT and not col.lower().endswith("_id"):  # few managers aren't codes
            c = f'"{col}"' if engine == "postgres" else f"[{col}]"
            _, rows, _ = run_unvalidated(source, f"SELECT {c}, COUNT(*) FROM {qname} GROUP BY {c} ORDER BY 2 DESC",
                                         max_rows=CODE_MAX_DISTINCT + 1)
            code_type, labels = _labels(source, [r[0] for r in rows if r[0] is not None])
            codes[col] = {"code_list": code_type,
                          "values": [{"value": v, "rows": k, **({"label": labels[v]} if v in labels else {})}
                                     for v, k in rows]}

    # A small table keyed by a code is a mapping: which value goes with which is in its rows, not in the value lists
    # above (X05 paired an element and an account by reading the two lists). Only values the card already shows. Tables
    # keyed by a number (salespeople, suppliers) are records, not mappings: linking their columns would add identities
    mapping = None
    primary = [c.strip(' "') for k in t["keys"] if k["kind"] == "primary"
               for c in k["definition"].split("(", 1)[1].rstrip(")").split(",")]
    if len(codes) >= 2 and 0 < t["rows"] <= MAPPING_MAX_ROWS and primary and set(primary) <= set(codes):
        q = lambda c: f'"{c}"' if engine == "postgres" else f"[{c}]"  # noqa: E731
        cols = list(codes)
        columns, rows, _ = run_unvalidated(source, f"SELECT {', '.join(q(c) for c in cols)} FROM {qname} "
                                                   f"ORDER BY {q(cols[0])}", max_rows=MAPPING_MAX_ROWS)
        mapping = {"columns": columns, "rows": rows,
                   "note": "Lignes de la table : les valeurs d'une même ligne vont ensemble."}

    # A few example values per column, from the first rows (none for salaries or identities)
    samples = {}
    sample_cols = [c["column_name"] for c in readable if c["column_name"] not in no_sample and c["column_name"] not in codes]
    if sample_cols and t["rows"]:
        q = lambda c: f'"{c}"' if engine == "postgres" else f"[{c}]"  # noqa: E731
        top, limit = ("TOP 5 ", "") if engine == "sqlserver" else ("", " LIMIT 5")
        columns, rows, _ = run_unvalidated(source, f"SELECT {top}{', '.join(q(c) for c in sample_cols)} FROM {qname}{limit}",
                                           max_rows=5)
        for i, col in enumerate(columns):
            seen = []
            for row in rows:
                if row[i] is not None and row[i] not in seen:
                    seen.append(row[i])
            samples[col] = seen[:3]

    hidden = [c["column_name"] for c in t["columns"] if not c["readable"]]
    return {
        "source": source, "table": name, "dialect": SOURCES[source].dialect,
        "description": t["comment"], "rows": t["rows"],
        "columns": [{"name": c["column_name"], "type": c["data_type"], "nullable": c["nullable"],
                     **({"comment": c["comment"]} if c["comment"] else {}),
                     **({"examples": samples[c["column_name"]]} if samples.get(c["column_name"]) else {}),
                     **({"privacy": "montant individuel : agrégé seulement (SUM, AVG, COUNT ; 5 personnes min.)"}
                        if source == "paie" and c["column_name"] in privacy.SENSITIVE.get(name, set()) else {})}
                    for c in readable],
        "keys": [k["definition"] for k in t["keys"]],
        "code_columns": codes,
        **({"mapping_rows": mapping} if mapping else {}),
        "hidden_columns": ({"columns": hidden, "why": "données personnelles, non lisibles par le compte de l'agent : "
                                                      "nommez les colonnes, pas de SELECT *"} if hidden else None),
        "ontology_terms": ontology.terms_for(source, name),   # the certified ontology (step 12, D49)
    }
