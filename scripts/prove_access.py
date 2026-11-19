"""Prove the role boundaries with planted values (Phase D, step 29).

    uv run python scripts/prove_access.py             # everything, with the agent and the RAG answering (about 30 min)
    uv run python scripts/prove_access.py --no-llm    # databases, MCP tools and retrieval only
    uv run python scripts/prove_access.py --cleanup   # remove what an interrupted run left

Plants one new row per marker with the admin accounts of .env, and a throw-away Qdrant collection, then asks as every
role. A role must get what the policy gives it and nothing else. Whatever happens, the rows and the collection are
removed and the row counts compared with those taken before. Nothing else may use the databases meanwhile: the markers
are real rows. Writes results/access_proof.json: names and verdicts, not the values.
"""
import argparse
import asyncio
import json
import signal
import sys
import tomllib
from pathlib import Path

import psycopg
import pymssql
from dotenv import dotenv_values
from mcp.client import Client
from qdrant_client import models

from rag_calorvia.config import settings as rag_settings
from rag_calorvia.etl import index as rag_index
from rag_calorvia.rag import pipeline, search as rag_search
from rag_calorvia.rag.permissions import roles_for
from text2sql_calorvia import access
from text2sql_calorvia import access_proof as proof
from text2sql_calorvia.agent import Agent, structured
from text2sql_calorvia.config import settings
from text2sql_calorvia.execution import run_unvalidated
from text2sql_calorvia.mcp_server import server
from text2sql_calorvia.policy import may_read
from text2sql_calorvia.sources import SOURCES

OUT = Path("results/access_proof.json")
RAG_CONFIG = rag_settings.final_config
TABLES = sorted({(m.source, m.table, m.column) for m in proof.markers()})


# --- the planted rows -------------------------------------------------------------------------------------------------
class Admin:
    """One admin connection per source, used for nothing but the markers."""

    def __init__(self):
        env = dotenv_values(".env")
        self.connections = {}
        for name, source in SOURCES.items():
            if source.engine == "sqlserver":
                self.connections[name] = pymssql.connect(
                    server=settings.sources_host, port=source.port, database=source.database, user="sa",
                    password=env["MSSQL_SA_PASSWORD"], autocommit=True, charset="UTF-8")
            else:
                self.connections[name] = psycopg.connect(
                    host=settings.sources_host, port=source.port, dbname=source.database, autocommit=True,
                    user=env["PG_ADMIN_USER"], password=env["PG_ADMIN_PASSWORD"])

    def run(self, source, sql, params=()):
        cursor = self.connections[source].cursor()
        cursor.execute(sql, params or None)
        return cursor.fetchall() if cursor.description else []

    def close(self):
        for connection in self.connections.values():
            connection.close()


def qualified(source, table):
    return f"dbo.{table}" if SOURCES[source].engine == "sqlserver" else f"public.{table}"


def counts(admin):
    return {f"{s}.{t}": admin.run(s, f"SELECT COUNT(*) FROM {qualified(s, t)}")[0][0] for s, t in {x[:2] for x in TABLES}}


def remove_markers(admin):
    for source, table, column in TABLES:
        admin.run(source, f"DELETE FROM {qualified(source, table)} WHERE {column} LIKE %s", (proof.PREFIX + "%",))


def is_generated(admin, marker):
    return bool(admin.run("erp", "SELECT 1 FROM sys.identity_columns WHERE object_id = OBJECT_ID(%s) AND name = %s",
                          (f"dbo.{marker.table}", marker.key)))


def plant(admin, marker, number):
    values = {marker.column: marker.secret}
    if marker.code:
        values[marker.code] = f"{proof.CODE_PREFIX}{number:02d}"
    if marker.key and not is_generated(admin, marker):
        table = qualified(marker.source, marker.table)
        values[marker.key] = admin.run(marker.source, f"SELECT MAX({marker.key}) + 1 FROM {table}")[0][0]
    for column, value in marker.values.items():
        values[column] = admin.run(marker.source, value["sql"])[0][0] if isinstance(value, dict) else value
    columns = ", ".join(values)
    holes = ", ".join(["%s"] * len(values))
    admin.run(marker.source, f"INSERT INTO {qualified(marker.source, marker.table)} ({columns}) VALUES ({holes})",
              tuple(values.values()))


# --- the throw-away collection ----------------------------------------------------------------------------------------
def plant_documents(config, planted):
    qdrant = rag_index.get_qdrant()
    template = qdrant.scroll(rag_index.collection_name(config), limit=1, with_payload=True)[0][0].payload
    texts = [f"Note interne {proof.PREFIX} du dossier {path.rsplit('/', 1)[0]}, code {secret}."
             for path, secret in planted.items()]
    vectors = rag_index.embed(texts, config["embedder"]["model"])
    remove_documents()
    qdrant.create_collection(
        proof.COLLECTION,
        vectors_config={"dense": models.VectorParams(size=len(vectors[0]), distance=models.Distance.COSINE)},
        sparse_vectors_config={"sparse": models.SparseVectorParams(modifier=models.Modifier.IDF)})
    for field, schema in rag_index.PAYLOAD_INDEXES.items():
        qdrant.create_payload_index(proof.COLLECTION, field, schema)
    points = []
    for i, ((path, _), text) in enumerate(zip(planted.items(), texts)):
        payload = {**template, "document": path, "department": path.split("/")[0], "text": text, "language": "fr",
                   "doc_language": "fr", "status": None, "chunk_index": 0, "allowed_roles": roles_for([path])}
        points.append(models.PointStruct(id=i, payload=payload, vector={
            "dense": vectors[i], "sparse": rag_index.bm25(text, rag_index.sparse_language(payload, config))}))
    qdrant.upsert(proof.COLLECTION, points=points, wait=True)
    rag_search.collection_name = lambda _config: proof.COLLECTION   # the real search code, on the planted points only


def remove_documents():
    qdrant = rag_index.get_qdrant()
    if qdrant.collection_exists(proof.COLLECTION):
        qdrant.delete_collection(proof.COLLECTION)


# --- the checks -------------------------------------------------------------------------------------------------------
class Findings:
    def __init__(self):
        self.failures, self.passed = [], 0

    def check(self, right, *where):
        if right:
            self.passed += 1
        else:
            self.failures.append(" / ".join(map(str, where)))
            print("FAIL", *where, flush=True)


def read_directly(role, marker):
    """The role's own login, past validation. None: the database refused or the role has no login there."""
    sql = f"SELECT {marker.column} FROM {qualified(marker.source, marker.table)} WHERE {marker.column} = '{marker.secret}'"
    try:
        return run_unvalidated(marker.source, sql, role=role)[1]
    except Exception:     # noqa: BLE001 - every refusal looks the same here: no rows came back
        return None


async def call(client, tool, **arguments):
    return json.dumps(structured(await client.call_tool(tool, arguments)), ensure_ascii=False, default=str)


async def check_tools(findings, planted, matrix):
    async with Client(server) as client:
        for role in access.roles():
            token = access.issue_token(role, "access-proof")
            for marker in planted:
                expected = proof.may_see(role, marker)
                rows = read_directly(role, marker)
                findings.check(bool(rows) == expected, "database", role, marker.name, f"expected={expected}")
                sql = f"SELECT {marker.column} FROM {marker.table} WHERE {marker.column} = '{marker.secret}'"
                reply = await call(client, "execute_sql", source=marker.source, sql=sql, access_token=token,
                                   session_id="access-proof")
                got = marker.secret in reply.replace(sql, "")
                findings.check(got == expected, "execute_sql", role, marker.name, f"expected={expected}")
                matrix.setdefault(role, {})[marker.name] = got
            for source in SOURCES:
                values = await call(client, "find_values", source=source, value=proof.PREFIX, limit=100, access_token=token)
                findings.check(not proof.forbidden_in(values, role, planted), "find_values", role, source)
                for marker in (m for m in planted if m.source == source and proof.may_see(role, m)):
                    findings.check(marker.secret in values, "find_values misses", role, marker.name)
                listing = await call(client, "list_tables", source=source, access_token=token)
                findings.check(not proof.forbidden_in(listing, role, planted), "list_tables", role, source)
                tables = access.tables_of(role, source)
                names = [] if not tables else sorted({m.table for m in planted if m.source == source}) if tables == "*" else tables
                for table in names:
                    card = await call(client, "get_table_card", source=source, table=table, access_token=token)
                    findings.check(not proof.forbidden_in(card, role, planted), "get_table_card", role, table)


async def check_agent(findings, planted):
    agent, shown = Agent(mcp_target=server, use_memory=False), {}
    for role in access.roles():
        for label, request in (("search", proof.SEARCH_REQUEST), ("pressure", proof.PRESSURE_REQUEST)):
            result = await agent.ask([{"role": "user", "content": request}], f"access-proof-{role}-{label}", "access-proof",
                                     access_token=access.issue_token(role, "access-proof"))
            text = json.dumps(result, ensure_ascii=False, default=str)
            findings.check(not proof.forbidden_in(text, role, planted), "agent", role, label,
                           proof.forbidden_in(text, role, planted))
            shown.setdefault(role, set()).update(proof.seen_in(result["answer"], planted))
            print(f"agent {role} {label}: {len(proof.seen_in(result['answer'], planted))} markers in the answer", flush=True)
    return {role: sorted(names) for role, names in shown.items()}


def check_documents(findings, planted, config, with_llm):
    answers = {}
    for role in access.roles():
        for path, secret in planted.items():
            chunks = pipeline.retrieve(f"Note interne {proof.PREFIX}, code {secret}", config, role)["chunks"]
            text = json.dumps(chunks, ensure_ascii=False, default=str)
            findings.check(not proof.forbidden_documents(text, role, planted), "retrieval", role, path)
            if may_read(role, path):
                findings.check(secret in text, "retrieval misses", role, path)
        if with_llm:
            reply = pipeline.answer(proof.DOCUMENT_REQUEST, config, role)
            text = json.dumps(reply, ensure_ascii=False, default=str)
            findings.check(not proof.forbidden_documents(text, role, planted), "RAG answer", role)
            answers[role] = sum(secret in reply["answer"] for secret in planted.values())
            print(f"rag {role}: {answers[role]} documents quoted", flush=True)
    return answers


def clean(admin, before=None):
    remove_markers(admin)
    remove_documents()
    left = sum(admin.run(s, f"SELECT COUNT(*) FROM {qualified(s, t)} WHERE {c} LIKE %s", (proof.PREFIX + "%",))[0][0]
               for s, t, c in TABLES)
    if left or (before is not None and counts(admin) != before):
        raise SystemExit(f"cleanup incomplete: {left} markers left, or row counts changed. Run --cleanup and check.")
    print("cleanup verified: no marker left, row counts as before", flush=True)


async def prove(with_llm):
    findings, matrix = Findings(), {}
    planted, documents = proof.markers(), proof.documents()
    config = tomllib.loads(RAG_CONFIG.read_text())
    admin = Admin()
    remove_markers(admin)
    before = counts(admin)
    try:
        for number, marker in enumerate(planted, 1):
            plant(admin, marker, number)
        plant_documents(config, documents)
        print(f"planted {len(planted)} rows and {len(documents)} documents", flush=True)
        await check_tools(findings, planted, matrix)
        print(f"tools done: {findings.passed} checks passed, {len(findings.failures)} failed", flush=True)
        quoted = check_documents(findings, documents, config, with_llm)
        print(f"documents done: {findings.passed} checks passed, {len(findings.failures)} failed", flush=True)
        shown = await check_agent(findings, planted) if with_llm else {}
    finally:
        clean(admin, before)
        admin.close()
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps({"checks_passed": findings.passed, "failures": findings.failures, "matrix": matrix,
                               "markers_in_agent_answers": shown, "documents_quoted_by_rag": quoted},
                              ensure_ascii=False, indent=1, sort_keys=True) + "\n")
    print(f"{findings.passed} checks passed, {len(findings.failures)} failed", flush=True)
    return not findings.failures


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--no-llm", action="store_true")
    parser.add_argument("--cleanup", action="store_true")
    args = parser.parse_args()
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))   # a stopped run still cleans up
    if args.cleanup:
        admin = Admin()
        clean(admin)
        admin.close()
        return
    if not asyncio.run(prove(not args.no_llm)):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
