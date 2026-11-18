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
from typing import NamedTuple

from text2sql_calorvia.config import settings
from text2sql_calorvia.policy import policy, roles

LOGIN_PREFIX = "agent_r_"
DEFAULT_ROLE = "employe"
TOKEN_SECONDS = 900              # one question, including a long cross-source one


class Identity(NamedTuple):
    role: str
    user: str


class AccessDenied(ValueError):
    """The message is safe to show: it says nothing about what exists."""


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
    if not tables_of(role, source):
        raise AccessDenied(f"La source {source} n'est pas disponible pour votre rôle.")


def allowed_tables(role: str | None, source: str) -> set[str] | None:
    """The tables (lower case) a role may see described in a source; None = no limit (agent_ro, or "*")."""
    if role is None:
        return None
    check_usable(role, source)
    tables = tables_of(role, source)
    return None if tables == "*" else {t.lower() for t in tables}


def row_limited(role: str | None) -> str | None:
    """The role, if the database shows it only some rows: what is built for it can't be shared with other roles."""
    return role if role is not None and roles()[role]["site"] else None


def site_label(role: str | None) -> str | None:
    site = roles()[role]["site"] if role is not None else None
    return site["label"] if site else None


def readable_sources(role: str | None) -> list[str]:
    """The sources a role can read, in the order of the policy's databases (None = every source)."""
    names = ["erp", "compta", "paie"]
    return names if role is None else [s for s in names if tables_of(role, s)]


def scope_of(role: str | None) -> dict[str, set[str] | None] | None:
    """{source: lower-case tables, or None for all of them} for a role; None = no limit (local mode)."""
    if role is None:
        return None
    return {s: None if tables_of(role, s) == "*" else {t.lower() for t in tables_of(role, s)}
            for s in readable_sources(role)}


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


def read_identity(token: str, now: float | None = None) -> Identity:
    """Who a token speaks for. Raises AccessDenied if it is forged, altered or expired."""
    body, _, signature = str(token).partition(".")
    if not hmac.compare_digest(signature, _derived("role-token:" + body)):
        raise AccessDenied("Accès refusé.")
    data = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    if data["exp"] < (now or time.time()) or data["role"] not in roles():
        raise AccessDenied("Accès refusé.")
    return Identity(data["role"], data["user"])


def read_token(token: str, now: float | None = None) -> str:
    return read_identity(token, now).role


def sign_chart(chart_id: str, expires: int) -> str:
    return _derived(f"chart-link:{chart_id}:{expires}")


def chart_link_valid(chart_id: str, expires: str, signature: str, now: float | None = None) -> bool:
    """An image tag can't send a key, so the link itself proves that the agent gave it out, until it expires."""
    if not expires.isascii() or not expires.isdigit() or int(expires) < (now or time.time()):
        return False
    return hmac.compare_digest(signature.encode(), sign_chart(chart_id, int(expires)).encode())


def caller(token: str | None) -> Identity | None:
    """Who an MCP call runs as. None = agent_ro, only while no API keys are set (local mode)."""
    if token:
        return read_identity(token)
    if settings.api_keys:
        raise AccessDenied("Accès refusé.")
    return None


def caller_role(token: str | None) -> str | None:
    identity = caller(token)
    return identity.role if identity else None
