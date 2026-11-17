"""Copy the ERP (SQL Server) into PostgreSQL for auto-ontology: variant (a) of O6, step 12.

    docker compose -f ontology/docker-compose.yaml --env-file .env up -d erp-copy
    uv run python scripts/copy_erp.py
"""
import os
import time

from dotenv import dotenv_values

from text2sql_calorvia.erp_copy import copy


def main():
    env = {**dotenv_values(".env"), **os.environ}
    url = (f"postgresql://{env['ERP_COPY_ADMIN_USER']}:{env['ERP_COPY_ADMIN_PASSWORD']}"
           f"@localhost:5436/gespro")
    start = time.perf_counter()
    counts, fks = copy(url, env["ERP_COPY_RO_PASSWORD"])
    print(f"{len(counts)} tables, {sum(counts.values())} rows, {fks} foreign keys, "
          f"{time.perf_counter() - start:.1f} s")


if __name__ == "__main__":
    main()
