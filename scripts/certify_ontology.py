"""Apply ontology/certification.yaml to auto-ontology: rename, re-describe and certify terms, add certified metrics.

    uv run python scripts/certify_ontology.py            # apply (idempotent)
    uv run python scripts/certify_ontology.py --dry-run  # show what would change

Terms are found by their table (one term per table after compilation), read in auto-ontology's PostgreSQL;
every change goes through its API, so it is re-embedded and attributed like an edit made in the UI.
"""
import argparse
import os
from pathlib import Path

import psycopg
import requests
import yaml
from dotenv import dotenv_values

API = "http://localhost:3000/api"
TERM_BY_TABLE = """
SELECT d.name, t.name, tm.id, tm.name, tm.name_certified AND tm.description_certified
FROM table__term tt
JOIN catalog_table t ON t.id = tt.table_id
JOIN catalog_schema s ON s.id = t.schema_id
JOIN catalog_database d ON d.id = s.database_id
JOIN term tm ON tm.id = tt.term_id
"""


def terms_by_table():
    ao = dotenv_values(os.path.expanduser("~/src/auto-ontology/.env"))
    url = f"postgresql://{ao['POSTGRES_USER']}:{ao['POSTGRES_PASSWORD']}@localhost:{ao['POSTGRES_PORT']}/{ao['POSTGRES_DATABASE']}"
    with psycopg.connect(url) as conn:
        return {(db, table): (term_id, name, certified)
                for db, table, term_id, name, certified in conn.execute(TERM_BY_TABLE)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    plan = yaml.safe_load(Path("ontology/certification.yaml").read_text(encoding="utf-8"))
    session = requests.Session()
    session.headers["x-api-key"] = dotenv_values(".env")["AUTO_ONTOLOGY_API_TOKEN"]
    terms = terms_by_table()

    for entry in plan["terms"]:
        key = (entry["database"], entry["table"])
        if key not in terms:
            print(f"!! no term for {key}")
            continue
        term_id, current, _ = terms[key]
        print(f"term {key[0]}.{key[1]}: {current!r} -> {entry['name']!r}")
        if not args.dry_run:
            r = session.patch(f"{API}/terms/{term_id}", json={
                "name": entry["name"], "description": " ".join(entry["description"].split()),
                "name_certified": True, "description_certified": True})
            r.raise_for_status()

    for metric in plan["metrics"]:
        term_id = terms[(metric["database"], metric["table"])][0]
        # The gateway lists SQL attributes per term only
        listed = session.get(f"{API}/terms/{term_id}/sql-attributes").json()["data"]
        existing = {attr["name"]: attr["id"] for attr in listed}
        body = {"name": metric["name"], "description": " ".join(metric["description"].split()),
                "expression": metric["expression"].strip(), "term_id": term_id, "source": "manual"}
        check = session.post(f"{API}/sql-attributes/validate",
                             json={"expression": body["expression"], "term_id": term_id}).json()
        action = "update" if metric["name"] in existing else "create"
        print(f"metric {metric['name']!r} ({action}): validation {check}")
        if args.dry_run:
            continue
        if action == "update":
            r = session.put(f"{API}/sql-attributes/{existing[metric['name']]}", json=body)
            attr_id = existing[metric["name"]]
        else:
            r = session.post(f"{API}/sql-attributes", json=body)
            attr_id = r.json().get("data", {}).get("id") if r.ok else None
        if not r.ok:
            print(f"   !! {r.status_code} {r.text[:300]}")
            continue
        session.patch(f"{API}/sql-attributes/{attr_id}", json={"certified": True}).raise_for_status()


if __name__ == "__main__":
    main()
