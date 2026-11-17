"""The certified ontology (step 12) as knowledge for the agent (D49): terms per table, certified metrics.

Read from ontology/certification.yaml, the file we wrote and certified, rather than from auto-ontology's database:
it is versioned, holds no data values, and the agent then does not depend on auto-ontology running.
The certification names the ERP database `gespro` and its tables in lower case (the PostgreSQL copy, D47);
here they are mapped back to the source `erp` and matched without case.
"""
from functools import cache
from pathlib import Path

import yaml

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
