import re
from urllib.parse import urlsplit

from .errors import invalid

HOSTS = {"x.com", "www.x.com", "twitter.com", "www.twitter.com", "mobile.twitter.com"}
ID = re.compile(r"[0-9]{1,20}\Z")
HANDLE = re.compile(r"[A-Za-z0-9_]{1,15}\Z")


def _parts(value: str) -> list[str]:
    try:
        url = urlsplit(value)
        port = url.port
    except ValueError as exc:
        raise invalid("Malformed X reference URL.") from exc
    if url.scheme != "https" or url.hostname not in HOSTS or url.username or url.password or port:
        raise invalid(
            "Use an https://x.com or https://twitter.com reference, or a plain ID/handle."
        )
    return [p for p in url.path.split("/") if p]


def post_id(value: str) -> str:
    value = value.strip()
    if ID.fullmatch(value):
        return value
    parts = _parts(value)
    if len(parts) >= 3 and parts[-2] == "status" and ID.fullmatch(parts[-1]):
        return parts[-1]
    raise invalid("Expected a post ID or post URL.")


def user_ref(value: str) -> str:
    value = value.strip().lstrip("@")
    if "://" in value:
        parts = _parts(value)
        if len(parts) != 1:
            raise invalid("Expected a profile URL.")
        value = parts[0]
    if not HANDLE.fullmatch(value) or value.lower() in {
        "home",
        "search",
        "explore",
        "i",
        "settings",
        "messages",
    }:
        raise invalid("Expected an X handle (1 to 15 letters, digits, or underscores).")
    return value.lower()


def collection_id(value: str, kind: str) -> str:
    value = value.strip()
    if ID.fullmatch(value):
        return value
    parts = _parts(value)
    expected = "lists" if kind == "list" else "communities"
    if len(parts) == 3 and parts[:2] == ["i", expected] and ID.fullmatch(parts[-1]):
        return parts[-1]
    raise invalid(f"Expected a {kind} ID or its /i/{expected}/ID URL.")
