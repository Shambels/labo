"""Who may read what (Phase D, D74): the roles of policy/roles.yaml, their database logins, and the role token.

A role reads the databases through its own login, so the database enforces its tables, whatever SQL the model writes.
The endpoint knows the user; it gives the agent a signed, short-lived token naming the role, and the agent passes it to
the MCP server beside the tool's arguments. The model never sees it and can't choose it.

Passwords and the signing key are derived from AGENT_RO_PASSWORD: the MCP server already holds that secret, must be able
to open every role's connection anyway, and there is no second secret to store.
"""
import base64
import hashlib
import hmac
import json
import time
from functools import cache
from pathlib import Path

import yaml

from text2sql_calorvia.config import settings

POLICY = Path(__file__).resolve().parents[2] / "policy" / "roles.yaml"
LOGIN_PREFIX = "agent_r_"
DEFAULT_ROLE = "employe"
TOKEN_SECONDS = 900              # one question, including a long cross-source one
ROW_SECURITY_READY = False       # step 27: until then the roles limited to a site are refused


class AccessDenied(ValueError):
    """The message is safe to show: it says nothing about what exists."""


@cache
def policy(path: Path = POLICY) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


@cache
def roles() -> dict[str, dict]:
    """Every role by name; a role with `sites` becomes one role per site (responsable_site_gent...)."""
    expanded = {}
    data = policy()
    for name, role in data["roles"].items():
        sites = role.get("sites")
        if not sites:
            expanded[name] = {**role, "site": None}
            continue
        for key, code in sites.items():
            documents = role.get("documents", []) + role.get("site_documents", {}).get(key, [])
            expanded[f"{name}_{key}"] = {**role, "site": code, "documents": documents}
    return expanded


def tables_of(role: str, source: str) -> list[str] | str:
    """The tables a role may read in a source: names, "*" for all those agent_ro reads, or [] for none."""
    listed = roles()[role]["sources"].get(source, [])
    if listed == "*":
        return "*"
    if not listed:
        return []
    groups = policy()["table_groups"][source]
    return sorted({table for group in listed for table in groups[group]})


def login(role: str) -> str:
    return LOGIN_PREFIX + role


def _derived(purpose: str) -> str:
    return hmac.new(settings.agent_ro_password.encode(), purpose.encode(), hashlib.sha256).hexdigest()


def password(role: str) -> str:
    return "Rr1!" + _derived(f"role-login:{role}")   # the prefix meets SQL Server's character classes


def check_usable(role: str, source: str) -> None:
    if role not in roles():
        raise AccessDenied("Rôle inconnu.")
    if roles()[role]["site"] and not ROW_SECURITY_READY:
        raise AccessDenied("Ce rôle n'est pas encore activé.")
    if not tables_of(role, source):
        raise AccessDenied(f"La source {source} n'est pas disponible pour votre rôle.")


def role_of(user: str) -> str:
    """USER_ROLES=alice:finance,webui/bob:rh. Nobody listed gets the default role, which reads no database."""
    assigned = dict(item.strip().split(":", 1) for item in settings.user_roles.split(",") if item.strip())
    role = assigned.get(user, DEFAULT_ROLE).strip()
    return role if role in roles() else DEFAULT_ROLE


def _encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def issue_token(role: str, user: str, now: float | None = None) -> str:
    body = _encode(json.dumps({"role": role, "user": user,
                               "exp": int((now or time.time()) + TOKEN_SECONDS)}).encode())
    return f"{body}.{_derived('role-token:' + body)}"


def read_token(token: str, now: float | None = None) -> str:
    """The role a token names. Raises AccessDenied if it is forged, altered or expired."""
    body, _, signature = str(token).partition(".")
    if not hmac.compare_digest(signature, _derived("role-token:" + body)):
        raise AccessDenied("Accès refusé.")
    data = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    if data["exp"] < (now or time.time()) or data["role"] not in roles():
        raise AccessDenied("Accès refusé.")
    return data["role"]


def caller_role(token: str | None) -> str | None:
    """What an MCP call runs as. None = agent_ro, only while no API keys are set (local mode)."""
    if token:
        return read_token(token)
    if settings.api_keys:
        raise AccessDenied("Accès refusé.")
    return None
