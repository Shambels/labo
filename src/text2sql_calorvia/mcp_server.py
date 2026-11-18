"""The MCP server "calorvia-sources": the only component that holds connections to the three databases.

    uv run python -m text2sql_calorvia.mcp_server            # streamable HTTP on 127.0.0.1:9001/mcp
    uv run python -m text2sql_calorvia.mcp_server --stdio    # for a client that starts it (Claude Desktop, tests)

Every tool is read-only; execute_sql validates, applies the payroll rule, runs in a read-only rolled-back
transaction with a timeout and a row limit, and logs to the course PostgreSQL.
"""
import argparse
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from text2sql_calorvia import access, cards, commission, execution, validation, values
from text2sql_calorvia.config import settings

INSTRUCTIONS = """Accès en lecture seule aux trois bases de Calorvia SA : erp (SQL Server, T-SQL), compta et paie
(PostgreSQL). Pas de jointure entre sources : interrogez chacune puis rapprochez les résultats.
Avant d'écrire une requête : list_tables, puis get_table_card des tables utiles ; find_values pour l'orthographe
exacte d'un nom ou d'un code. validate_sql vérifie une requête, execute_sql l'exécute (au plus {max_rows} lignes).
Paie : les montants de salaire ne sont lisibles qu'agrégés (SUM, AVG, COUNT) sur au moins {k} personnes ; pour la
commission d'un commercial, get_sales_commission.""".format(max_rows=settings.max_rows, k=settings.min_group_size)

UNAVAILABLE = "Cette information n'est pas disponible pour votre rôle."
READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)

server = MCPServer("calorvia-sources", instructions=INSTRUCTIONS, version="0.2")


def _scope(access_token, source):
    """(tables the caller may see or None for all, None), or (None, a refusal). Cards and value lists hold real data."""
    role, refused = _caller(access_token)
    if refused:
        return None, refused
    try:
        return access.allowed_tables(role, source), None
    except access.AccessDenied:
        return None, {"ok": False, "error": UNAVAILABLE}


def _caller(access_token):
    """(role, None), or (None, a refusal). The token comes from the agent, never from the model (access.py)."""
    try:
        return access.caller_role(access_token), None
    except access.AccessDenied as error:
        return None, {"ok": False, "error": str(error)}


@server.tool(annotations=READ_ONLY)
def list_sources(access_token: str | None = None) -> list[dict[str, Any]]:
    """Les trois sources : moteur, dialecte SQL, nombre de tables, contenu et période couverte."""
    role, refused = _caller(access_token)
    if refused:
        return [refused]
    return [s for s in cards.list_sources() if role is None or access.tables_of(role, s["source"])]


@server.tool(annotations=READ_ONLY)
def list_tables(source: str, access_token: str | None = None) -> list[dict[str, Any]]:
    """Les tables d'une source (erp, compta ou paie) avec leur nombre de lignes et leur description."""
    if source not in cards.SOURCES:
        return [{"error": f"Source inconnue : {source}. Sources : erp, compta, paie."}]
    allowed, refused = _scope(access_token, source)
    if refused:
        return [refused]
    return [t for t in cards.list_tables(source) if allowed is None or t["table"].lower() in allowed]


@server.tool(annotations=READ_ONLY)
def get_table_card(source: str, table: str, access_token: str | None = None) -> dict[str, Any]:
    """La fiche d'une table : description, colonnes et types, clés, nombre de lignes, exemples de valeurs,
    valeurs des colonnes de codes avec leur libellé, colonnes non lisibles. À lire avant d'écrire une requête."""
    if source not in cards.SOURCES:
        return {"error": f"Source inconnue : {source}. Sources : erp, compta, paie."}
    allowed, refused = _scope(access_token, source)
    if refused:
        return refused
    if allowed is not None and table.lower() not in allowed:
        return {"ok": False, "error": UNAVAILABLE}
    return cards.get_table_card(source, table)


@server.tool(annotations=READ_ONLY)
def find_values(source: str, value: str, table: str | None = None, column: str | None = None,
                limit: int = 20, access_token: str | None = None) -> dict[str, Any]:
    """Où apparaît une valeur (nom de client, fournisseur, article, numéro de facture, de lot, de TVA...) et
    comment elle s'écrit exactement. Insensible à la casse, aux accents et à la ponctuation ; tolère les fautes."""
    if source not in cards.SOURCES:
        return {"error": f"Source inconnue : {source}. Sources : erp, compta, paie."}
    allowed, refused = _scope(access_token, source)
    if refused:
        return refused
    return values.find_values(source, value, table, column, min(max(limit, 1), 100), allowed)


@server.tool(annotations=READ_ONLY)
def validate_sql(source: str, sql: str, access_token: str | None = None) -> dict[str, Any]:
    """Vérifie une requête sans l'exécuter : une seule lecture (SELECT), dans le dialecte de la source, tables et
    colonnes existantes, règle de confidentialité de la paie. Renvoie les erreurs à corriger, ou la requête qui
    sera exécutée (avec sa limite de lignes)."""
    _, refused = _caller(access_token)
    if refused:
        return refused
    return validation.validate(source, sql).as_dict()


@server.tool(annotations=READ_ONLY)
def execute_sql(source: str, sql: str, question: str | None = None, session_id: str | None = None,
                max_rows: int | None = None, access_token: str | None = None) -> dict[str, Any]:
    """Exécute une requête de lecture sur une source (validée d'abord). Renvoie les colonnes, les lignes (200 par
    défaut, `max_rows` pour plus, jusqu'à la limite du serveur) et un indicateur de troncature, ou les erreurs.
    `question` : la question de l'utilisateur, pour le journal."""
    role, refused = _caller(access_token)
    if refused:
        return refused
    limit = min(max(max_rows or settings.max_rows, 1), settings.max_rows_limit)
    return execution.execute(source, sql, question=question, session_id=session_id, max_rows=limit, role=role)


@server.tool(annotations=READ_ONLY)
def get_sales_commission(staff_number: str, month: str, question: str | None = None,
                         session_id: str | None = None, access_token: str | None = None) -> dict[str, Any]:
    """La commission sur ventes d'un commercial pour un mois de paie (AAAA-MM), avec la base (ventes facturées du
    mois précédent) et le taux. Seul montant individuel de la paie que l'agent peut montrer. staff_number : le
    matricule de l'ERP (10405) ou de la paie (M10405)."""
    role, refused = _caller(access_token)
    if refused:
        return refused
    try:
        return commission.get_sales_commission(staff_number, month, question, session_id, role)
    except (access.AccessDenied, *execution.DB_ERRORS):
        return {"ok": False, "errors": ["Cette information n'est pas disponible pour votre rôle."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--stdio", action="store_true", help="stdio transport instead of streamable HTTP")
    args = parser.parse_args()
    execution.create_log_table()
    if args.stdio:
        server.run("stdio")
    else:
        server.run("streamable-http", host=settings.mcp_host, port=settings.mcp_port)


if __name__ == "__main__":
    main()
