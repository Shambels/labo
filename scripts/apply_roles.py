"""Create or update one read-only database login per role of policy/roles.yaml (step 25, D74). Idempotent.

    uv run python scripts/apply_roles.py --dry-run   # what would be granted
    uv run python scripts/apply_roles.py

Uses the admin accounts of .env, the only code that does. A login never gets more than agent_ro has: "*" and column
grants are copied from agent_ro's own privileges, so the hidden payroll columns stay hidden. Logins of roles no longer
in the policy are removed. The course's files and agent_ro are not touched.
"""
import argparse

import psycopg
import pymssql
from dotenv import dotenv_values
from psycopg import sql

from text2sql_calorvia import access
from text2sql_calorvia.config import settings
from text2sql_calorvia.sources import SOURCES

AGENT_RO_TABLES = """
SELECT c.relname, has_table_privilege('agent_ro', c.oid, 'SELECT'),
       ARRAY(SELECT a.attname::text FROM pg_attribute a WHERE a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped
             AND has_column_privilege('agent_ro', c.oid, a.attnum, 'SELECT') ORDER BY a.attnum)
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p', 'v') ORDER BY 1
"""


def wanted(source):
    return {role: tables for role in access.roles() if (tables := access.tables_of(role, source))}


def apply_postgres(source, env, dry_run):
    target = SOURCES[source]
    with psycopg.connect(host=settings.sources_host, port=target.port, dbname=target.database, autocommit=True,
                         user=env["PG_ADMIN_USER"], password=env["PG_ADMIN_PASSWORD"]) as db:
        readable = {name: (whole, columns) for name, whole, columns in db.execute(AGENT_RO_TABLES).fetchall() if columns}
        roles = wanted(source)
        logins = {access.login(r) for r in roles}
        for (name,) in db.execute("SELECT rolname FROM pg_roles WHERE rolname LIKE %s",
                                  (access.LOGIN_PREFIX.replace("_", r"\_") + "%",)).fetchall():
            if name not in logins:
                print(f"{source}: remove {name}")
                if not dry_run:
                    db.execute(sql.SQL("DROP OWNED BY {0}").format(sql.Identifier(name)))
                    db.execute(sql.SQL("DROP ROLE {0}").format(sql.Identifier(name)))
        for role, tables in roles.items():
            names = sorted(readable) if tables == "*" else tables
            missing = [t for t in names if t not in readable]
            if missing:
                raise SystemExit(f"{role}: not readable by agent_ro in {source}: {missing}")
            print(f"{source}: {access.login(role)}: {len(names)} tables")
            if dry_run:
                continue
            user = sql.Identifier(access.login(role))
            exists = db.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (access.login(role),)).fetchone()
            verb = "ALTER" if exists else "CREATE"
            db.execute(sql.SQL(verb + " ROLE {0} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD {1}")
                       .format(user, sql.Literal(access.password(role))))
            db.execute(sql.SQL("ALTER ROLE {0} SET default_transaction_read_only = on").format(user))
            db.execute(sql.SQL("ALTER ROLE {0} SET statement_timeout = '30s'").format(user))
            db.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {0}").format(user))
            db.execute(sql.SQL("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {0}").format(user))
            for table in names:
                whole, columns = readable[table]
                what = sql.SQL("SELECT") if whole else sql.SQL("SELECT ({0})").format(
                    sql.SQL(", ").join(map(sql.Identifier, columns)))
                db.execute(sql.SQL("GRANT {0} ON {1} TO {2}").format(what, sql.Identifier("public", table), user))


def apply_sqlserver(source, env, dry_run):
    target = SOURCES[source]
    conn = pymssql.connect(server=settings.sources_host, port=target.port, database=target.database,
                           user="sa", password=env["MSSQL_SA_PASSWORD"], autocommit=True, charset="UTF-8")
    cur = conn.cursor()
    cur.execute("SELECT name FROM sys.tables WHERE schema_id = SCHEMA_ID('dbo')")
    existing = {row[0] for row in cur.fetchall()}
    roles = wanted(source)
    logins = {access.login(r) for r in roles}
    cur.execute(r"SELECT name FROM sys.server_principals WHERE name LIKE 'agent\_r\_%' ESCAPE '\'")
    for (name,) in cur.fetchall():
        if name not in logins:
            print(f"{source}: remove {name}")
            if not dry_run:
                cur.execute(f"DROP USER IF EXISTS [{name}]")
                cur.execute(f"DROP LOGIN [{name}]")
    for role, tables in roles.items():
        names = sorted(existing) if tables == "*" else tables
        if missing := [t for t in names if t not in existing]:
            raise SystemExit(f"{role}: unknown tables in {source}: {missing}")
        name = access.login(role)
        print(f"{source}: {name}: {len(names)} tables")
        if dry_run:
            continue
        cur.execute("SELECT 1 FROM sys.server_principals WHERE name = %s", (name,))
        verb = "ALTER" if cur.fetchone() else "CREATE"
        cur.execute(f"{verb} LOGIN [{name}] WITH PASSWORD = N'{access.password(role)}'"
                    + (", CHECK_POLICY = OFF" if verb == "CREATE" else ""))
        cur.execute(f"DROP USER IF EXISTS [{name}]")   # its permissions go with it: what follows is the whole truth
        cur.execute(f"CREATE USER [{name}] FOR LOGIN [{name}]")
        for table in names:
            cur.execute(f"GRANT SELECT ON [dbo].[{table}] TO [{name}]")
        cur.execute(f"DENY INSERT, UPDATE, DELETE, ALTER, EXECUTE ON SCHEMA::[dbo] TO [{name}]")
    conn.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    env = dotenv_values(".env")
    for source, target in SOURCES.items():
        (apply_sqlserver if target.engine == "sqlserver" else apply_postgres)(source, env, args.dry_run)


if __name__ == "__main__":
    main()
