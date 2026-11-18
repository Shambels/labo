"""Who may read which document (Phase D, D77), from policy/roles.yaml and the registry.

Identical files are indexed once (D11). A role may read the kept document if the policy gives it **any** copy: `finance`
reads the CODIR annexes, and one of them is kept under `06_Achats`. Nothing matching means no role: denied by default.
"""
from functools import cache

from text2sql_calorvia.policy import may_read, roles

from rag_calorvia import db


def roles_for(paths):
    """The roles allowed to read at least one of these paths, sorted."""
    return sorted(role for role in roles() if any(may_read(role, path) for path in paths))


@cache
def copies_of():
    """{kept document: [its dropped copies]}."""
    with db.connect(read_only=True) as conn:
        pairs = db.load_duplicates(conn)
    copies = {}
    for path, kept in pairs:
        copies.setdefault(kept, []).append(path)
    return copies


def allowed_roles(path):
    return roles_for([path, *copies_of().get(path, [])])


def can_read(role, path):
    """role None: no limit (local mode, evaluation)."""
    return role is None or role in allowed_roles(path)


def identify(key):
    """(user, role) of an API key for the chat, or None. Without configured keys: (None, None), local mode."""
    from text2sql_calorvia import access, auth
    from text2sql_calorvia.config import settings

    keys = auth.parse_keys(settings.api_keys)
    if not keys:
        return None, None
    caller = auth.authenticate(f"Bearer {key}", keys, set())
    return (caller.name, access.role_of(caller.name)) if caller else None
