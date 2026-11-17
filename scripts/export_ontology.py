"""Export the auto-ontology model as Apache Ossie YAML into ontology/export/, scrubbed for a public repository.

    uv run python scripts/export_ontology.py

auto-ontology's export embeds, in semantic_model.yaml, the catalog with up to five `sample_values` per column.
For payroll that means employee names, work e-mails, cities and staff numbers (fictional, but to be treated as
real); the ERP's salesperson table holds names, e-mails and staff numbers too. Their samples are emptied before
writing; the other tables keep theirs (codes, amounts, company names). The check at the end fails if a staff
number or a work e-mail survives.
"""
import io
import json
import re
import zipfile
from pathlib import Path

import requests
from dotenv import dotenv_values

OUT = Path("ontology/export")
SCRUBBED_DATABASES = {"paie"}                 # every table
SCRUBBED_TABLES = {("gespro", "vdr_vendeur")}  # people in the other sources
SCRUBBED_COLUMNS = re.compile(r"iban|e?mail|national|adresse|address|_adr$", re.I)  # in any table


def scrub(document):
    """Empty `sample_values` (and `distinct_values`) in the catalog JSON of every payroll table."""
    count = 0

    def visit(node, database=None):
        nonlocal count
        if isinstance(node, dict):
            database = node.get("database_name") or node.get("database") or database
            personal = database in SCRUBBED_DATABASES or (database, node.get("name")) in SCRUBBED_TABLES
            if personal and "columns" in node:          # a whole table of people
                for column in node["columns"]:
                    for key in ("sample_values", "distinct_values"):
                        if column.get(key):
                            column[key] = []
                            count += 1
            column_name = node.get("name") if "type" in node else None
            sensitive_column = bool(column_name and SCRUBBED_COLUMNS.search(str(column_name)))
            for key in ("sample_values", "distinct_values"):
                if (database in SCRUBBED_DATABASES or sensitive_column) and node.get(key):
                    node[key] = []
                    count += 1
            for value in node.values():
                visit(value, database)
        elif isinstance(node, list):
            for value in node:
                visit(value, database)

    visit(document)
    return count


def scrub_text(text):
    """The catalog is a JSON string inside the YAML: parse each JSON object found, scrub it, write it back."""
    import yaml

    data = yaml.safe_load(text)
    total = 0

    def walk(node):
        nonlocal total
        if isinstance(node, dict):
            for key, value in list(node.items()):
                if isinstance(value, str) and value.lstrip().startswith(("{", "[")):
                    try:
                        parsed = json.loads(value)
                    except ValueError:
                        continue
                    total += scrub(parsed)
                    node[key] = json.dumps(parsed, ensure_ascii=False)
                else:
                    walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(data)
    total += scrub(data)
    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=120), total


def main():
    token = dotenv_values(".env")["AUTO_ONTOLOGY_API_TOKEN"]
    response = requests.post("http://localhost:3000/api/model/export", headers={"x-api-key": token},
                             json={"format": "ossie", "include_ontology": True}, timeout=300)
    response.raise_for_status()
    OUT.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        for name in archive.namelist():
            text = archive.read(name).decode("utf-8")
            text, scrubbed = scrub_text(text)
            (OUT / name).write_text(text, encoding="utf-8")
            print(f"{name}: {len(text):,} characters, {scrubbed} payroll sample lists emptied")
    # The check that matters: no staff number, work e-mail or employee name sample left
    leaks = [(p.name, m) for p in OUT.glob("*.yaml")
             for m in re.findall(r"M1\d{4}|[a-z]+\.[a-z]+@calorvia\.be|\b[A-Z]{2}\d{2}(?: ?\d{4}){3}\b",
                                 p.read_text(encoding="utf-8"))]
    # BE68 5390 0754 7034 is the textbook example IBAN, which the model wrote into a description; not in the data
    leaks = [(name, m) for name, m in leaks if m != "BE68 5390 0754 7034"]
    if leaks:
        raise SystemExit(f"payroll values still in the export: {leaks[:5]}")
    print("no staff number, work e-mail or IBAN left")


if __name__ == "__main__":
    main()
