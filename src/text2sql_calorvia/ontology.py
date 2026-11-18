"""The certified ontology (step 12) as knowledge for the agent (D49): terms per table, certified metrics.

Read from ontology/certification.yaml, the file we wrote and certified, rather than from auto-ontology's database:
it is versioned, holds no data values, and the agent then does not depend on auto-ontology running.
The certification names the ERP database `gespro` and its tables in lower case (the PostgreSQL copy, D47);
here they are mapped back to the source `erp` and matched without case.
"""
import re
from functools import cache
from pathlib import Path

import yaml

from text2sql_calorvia.values import normalize

CERTIFICATION = Path(__file__).resolve().parents[2] / "ontology" / "certification.yaml"
SOURCE_OF_DATABASE = {"gespro": "erp", "compta": "compta", "paie": "paie"}


@cache
def load(path: Path = CERTIFICATION) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    for item in data.get("terms", []) + data.get("metrics", []):
        item["source"] = SOURCE_OF_DATABASE[item["database"]]
    return data


def terms_for(source: str, table: str) -> list[dict]:
    """The certified terms of one table: name and definition (what the table means, its traps)."""
    return [{"term": t["name"], "definition": " ".join(t["description"].split()), "certified": True}
            for t in load()["terms"] if t["source"] == source and t["table"].lower() == table.lower()]


def metrics() -> list[dict]:
    return load()["metrics"]


def glossary() -> str:
    """The certified metrics as a block for the system prompt: definition, source, table and reference SQL."""
    blocks = []
    for m in metrics():
        sql = m["expression"].strip()
        blocks.append(f"- **{m['name']}** ({m['source']}, {m['table']}) : {' '.join(m['description'].split())}\n"
                      f"  SQL de référence :\n" + "\n".join("    " + line for line in sql.splitlines()))
    return "\n".join(blocks)


def table_index() -> str:
    """One line per certified table: where each business notion lives, so the agent knows which card to read."""
    return "\n".join(f"- {t['source']}.{t['table'].upper() if t['source'] == 'erp' else t['table']} : {t['name']}"
                     for t in load()["terms"])


def _flat(text: str) -> str:
    return normalize(str(text).replace("’", "'"))


def _names_one(names: list[str], flat: str) -> bool:
    return any(re.search(r"\b" + re.escape(name), flat) for name in names)


def other_readings(question: str, answer: str) -> str:
    """A note naming the readings of the question's business words that the answer leaves out (D68), or "".

    In code because the model does not see a word as ambiguous when it has a metric for it. No note when the question
    settles the reading, or when the answer already names every reading.
    """
    asked, said, notes = _flat(question), _flat(answer), []
    for word in load().get("business_words", []):
        readings = word["readings"]
        if not any(re.search(p, asked) for p in word["patterns"]):
            continue
        if any(_names_one(r["names"], asked) for r in readings):
            continue
        left = [r["label"] for r in readings if not _names_one(r["names"], said)]
        if left:
            notes.append(f"**« {word['word']} » peut aussi se lire ainsi** : {' ; '.join(left)}. "
                         "Si vous voulez ce chiffre, dites-le-moi.")
    return "".join(f"\n\n{n}" for n in notes)
