"""Who is calling the endpoint (step 24, D72).

With API keys configured, every /v1 request needs `Authorization: Bearer <key>`, and the user is the key's name: the
`user` field of the request is no longer believed, so nobody can read or write another person's memory. A key listed
as a trusted gateway (Open WebUI, which holds one key for all its users) may name its end user in a header; that user
is namespaced under the gateway. Without keys the endpoint is in local mode, and refuses to listen beyond loopback.
"""
import hmac
import ipaddress
from dataclasses import dataclass


@dataclass(frozen=True)
class Caller:
    name: str | None       # the key's name; None in local mode
    gateway: bool = False


def parse_keys(text: str) -> dict[str, str]:
    """"alice:k1, webui:k2" -> {"alice": "k1", "webui": "k2"}."""
    keys = {}
    for item in filter(None, (part.strip() for part in text.split(","))):
        name, separator, key = item.partition(":")
        if not (separator and name.strip() and key.strip()):
            raise ValueError("API_KEYS: each entry is name:key")
        keys[name.strip()] = key.strip()
    return keys


def names(text: str) -> set[str]:
    return {part.strip() for part in text.split(",") if part.strip()}


def authenticate(header: str | None, keys: dict[str, str], gateways: set[str]) -> Caller | None:
    """The caller of a request, or None if its key is missing or wrong. Every key is compared, in constant time."""
    if not keys:
        return Caller(None)
    scheme, _, given = (header or "").partition(" ")
    found = None
    for name, key in keys.items():
        if hmac.compare_digest(given.strip().encode(), key.encode()):
            found = name
    if scheme.lower() != "bearer" or found is None:
        return None
    return Caller(found, found in gateways)


def user_of(caller: Caller, requested: str | None, end_user: str | None) -> str:
    """Whose memory and conversations these are."""
    if caller.name is None:                 # local mode: what the client says, as before
        return requested or end_user or "default"
    if caller.gateway and end_user:
        return f"{caller.name}/{end_user}"
    return caller.name


def is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False
