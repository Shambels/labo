"""The access policy, policy/roles.yaml, as data: no settings and no connection, so both chatbots can read it."""
from functools import cache
from pathlib import Path

import yaml

POLICY = Path(__file__).resolve().parents[2] / "policy" / "roles.yaml"
EVERYTHING = "*"


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
        for key, site in sites.items():
            documents = role.get("documents", []) + role.get("site_documents", {}).get(key, [])
            expanded[f"{name}_{key}"] = {**role, "site": site, "documents": documents}
    return expanded


def document_rules(role: str) -> list[str]:
    """The folders and files a role may read: its own, and what every role may read."""
    return roles()[role].get("documents", []) + policy()["everyone_documents"]


def matches(rule: str, path: str) -> bool:
    """A rule is "*", a file, or a folder: `02_RH` covers `02_RH/x.pdf`, not `02_RH_old/x.pdf`."""
    return rule == EVERYTHING or path == rule or path.startswith(rule.rstrip("/") + "/")


def may_read(role: str, path: str) -> bool:
    return any(matches(rule, path) for rule in document_rules(role))
