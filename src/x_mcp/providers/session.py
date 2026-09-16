"""Pinned twscrape raw transport; no automatic login, telemetry, model dumps, or writes."""

from __future__ import annotations

import asyncio
import importlib.util
import os
import time
from contextlib import aclosing
from pathlib import Path
from typing import Any

from ..auth import fingerprint, read_cookies
from ..errors import XError
from ..models import ProviderPage, Query, dumps
from ..normalize import post, trend, user

OPERATIONS = {
    "search.posts",
    "search.users",
    "post.post",
    "post.thread",
    "post.replies",
    "post.quotes",
    "post.reposters",
    "user.profile",
    "user.posts",
    "user.replies",
    "user.media",
    "user.followers",
    "user.following",
    "list.posts",
    "list.members",
    "community.info",
    "community.posts",
    "community.members",
    "trends.trending",
    "trends.news",
    "trends.sport",
    "trends.entertainment",
}


def typed_nodes(value: Any, typename: str):
    if isinstance(value, dict):
        if value.get("__typename") == typename:
            yield value
            return
        for child in value.values():
            yield from typed_nodes(child, typename)
    elif isinstance(value, list):
        for child in value:
            yield from typed_nodes(child, typename)


def explicit_public(value: dict[str, Any]) -> bool:
    if value.get("is_public") is False or str(
        value.get("mode", value.get("access", ""))
    ).lower() in {"private", "protected", "restricted"}:
        return False
    return (
        value.get("is_public") is True
        or str(value.get("mode", value.get("access", ""))).lower() == "public"
    )


def source_value(node: dict[str, Any], name: str, group: str = "", member: str = ""):
    """Do not use twscrape's synthesized zero counts as observed data."""
    if name in node:
        return node[name]
    legacy = node.get("legacy") or {}
    if name in legacy:
        return legacy[name]
    return (node.get(group) or {}).get(member) if group else None


def normalize_raw(body: dict[str, Any], operation: str, target: str = "") -> list[dict[str, Any]]:
    # Use the dependency's current field mapping, not parsers that write raw dumps
    # or replace unavailable numeric values with zeros.
    from twscrape.utils import to_old_obj

    users = {}
    for node in typed_nodes(body, "User"):
        flat = to_old_obj(node)
        users[str(flat.get("id_str", node.get("rest_id", "")))] = {
            "id": str(flat.get("id_str", node.get("rest_id", ""))),
            "screen_name": flat.get("screen_name"),
            "name": flat.get("name"),
            "description": flat.get("description"),
            "joined": flat.get("created_at"),
            "protected": flat.get("protected"),
            "location": flat.get("location"),
            "followers": source_value(node, "followers_count", "relationship_counts", "followers"),
            "following": source_value(node, "friends_count", "relationship_counts", "following"),
            "statuses": source_value(node, "statuses_count", "tweet_counts", "tweets"),
            "avatar_url": flat.get("profile_image_url_https"),
        }
    if operation in {
        "search.users",
        "user.profile",
        "user.followers",
        "user.following",
        "post.reposters",
        "list.members",
        "community.members",
    }:
        result = []
        for raw in users.values():
            if (
                operation == "user.profile"
                and str(raw.get("screen_name", "")).lower() != target.lower()
            ):
                continue
            try:
                result.append(user(raw, session=True))
            except XError as exc:
                if exc.code != "PUBLIC_ONLY":
                    raise
        return result
    if operation.startswith("trends."):
        return [trend(node) for node in typed_nodes(body, "TimelineTrend")]
    result = []
    seen = set()
    for node in typed_nodes(body, "Tweet"):
        flat = to_old_obj(node)
        ident = str(node.get("rest_id") or flat.get("id_str", ""))
        if ident in seen:
            continue
        if operation == "post.post" and ident != target:
            continue
        if operation == "post.replies" and str(flat.get("in_reply_to_status_id_str", "")) != target:
            continue
        author = users.get(str(flat.get("user_id_str")))
        if not author:
            continue
        note = ((node.get("note_tweet") or {}).get("note_tweet_results") or {}).get("result") or {}
        raw = {
            "id": ident,
            "author": author,
            "text": note.get("text") or flat.get("full_text") or flat.get("text") or "",
            "created_at": flat.get("created_at"),
            "lang": flat.get("lang"),
            "likes": source_value(node, "favorite_count"),
            "reposts": source_value(node, "retweet_count"),
            "replies": source_value(node, "reply_count"),
            "quotes": source_value(node, "quote_count"),
            "views": (node.get("views") or {}).get("count"),
            "inReplyToTweetId": flat.get("in_reply_to_status_id_str"),
            "conversationId": source_value(node, "conversation_id_str"),
            "hashtags": [
                x["text"]
                for x in (flat.get("entities") or {}).get("hashtags", [])
                if isinstance(x, dict) and "text" in x
            ],
            "links": [
                x.get("expanded_url")
                for x in (flat.get("entities") or {}).get("urls", [])
                if isinstance(x, dict)
            ],
        }
        entities = flat.get("extended_entities") or flat.get("entities") or {}
        raw["media"] = {
            "all": [
                {
                    "type": m.get("type"),
                    "url": m.get("media_url_https"),
                    "thumbnail_url": m.get("media_url_https"),
                    "alt_text": m.get("ext_alt_text"),
                    "width": (m.get("original_info") or {}).get("width"),
                    "height": (m.get("original_info") or {}).get("height"),
                }
                for m in entities.get("media", [])
                if isinstance(m, dict)
            ]
        }
        try:
            result.append(post(raw, session=True))
            seen.add(ident)
        except XError as exc:
            if exc.code != "PUBLIC_ONLY":
                raise
    if operation == "post.thread":
        focal = next((p for p in result if p["id"] == target), None)
        if not focal:
            raise XError("NOT_FOUND", "Public focal post was not present in the thread.")
        result = [p for p in result if p["author"]["id"] == focal["author"]["id"]]
    return result


class SessionProvider:
    name = "twscrape"

    def __init__(self, state_dir: Path, session_file: Path):
        self.state_dir, self.session_file = state_dir, session_file
        self._api = None
        self._fingerprint = ""
        self._lock = asyncio.Lock()
        self._last_request = 0.0

    @property
    def installed(self) -> bool:
        return importlib.util.find_spec("twscrape") is not None

    @property
    def configured(self) -> bool:
        return self.session_file.is_file() and self.installed

    def context(self) -> str:
        return fingerprint(read_cookies(self.session_file))

    def supports(self, operation: str) -> bool:
        return operation in OPERATIONS

    async def close(self) -> None:
        # Raw generators own their clients and are explicitly closed per page.
        self._api = None

    async def _client(self):
        if not self.installed:
            raise XError("AUTH_REQUIRED", "Install the session extra and configure an X session.")
        cookies = read_cookies(self.session_file)
        context = fingerprint(cookies)
        if self._api is not None and self._fingerprint == context:
            return self._api
        os.environ["TWS_TELEMETRY"] = "0"
        from twscrape import API
        from twscrape.logger import logger

        logger.disable("twscrape")
        api = API(str(self.state_dir / "account.db"), raise_when_no_account=True, wait_timeout=0)
        # The database is private to this adapter. Never rotate into another account.
        accounts = await api.pool.get_all()
        if any(account.username != "owner" for account in accounts):
            raise XError("INVALID_SESSION", "Session database must contain only the owner account.")
        owner = next(iter(accounts), None)
        # Preserve an expired account's state across restarts until cookies change.
        if owner is None or any(owner.cookies.get(k) != v for k, v in cookies.items()):
            await api.pool.add_account_cookies("owner", dumps(cookies))
        self._api, self._fingerprint = api, context
        return api

    async def fetch(self, query: Query, cursor: str | None = None) -> ProviderPage:
        if not self.supports(query.operation):
            raise XError("UNSUPPORTED", "This public operation has no session adapter.")
        async with self._lock:
            await asyncio.sleep(max(0, 2 - (time.monotonic() - self._last_request)))
            self._last_request = time.monotonic()
            try:
                async with asyncio.timeout(25):
                    api = await self._client()
                    return await self._fetch(api, query, cursor)
            except XError:
                raise
            except TimeoutError as exc:
                raise XError(
                    "TIMEOUT", "Session request exceeded its bounded wait.", retryable=True
                ) from exc
            except Exception as exc:
                name = type(exc).__name__
                if name == "NoAccountError":
                    return await self._unavailable()
                if name in {"GqlFeaturesOutdatedError", "XClIdParseError"}:
                    raise XError(
                        "PROVIDER_CHANGED",
                        "X web compatibility changed; update the pinned session adapter.",
                    ) from exc
                raise XError(
                    "PROVIDER_UNAVAILABLE",
                    "Session provider failed; run x-mcp doctor for sanitized state.",
                    retryable=True,
                ) from exc

    async def _unavailable(self):
        import json
        import sqlite3
        from datetime import UTC, datetime

        with sqlite3.connect(self.state_dir / "account.db") as db:
            row = db.execute("SELECT active, locks FROM accounts WHERE username='owner'").fetchone()
        if row and not row[0]:
            raise XError(
                "SESSION_EXPIRED", "X session is expired or denied. Reconnect the account."
            )
        retry = 60
        if row:
            for value in json.loads(row[1] or "{}").values():
                try:
                    when = datetime.fromisoformat(value).replace(tzinfo=UTC).timestamp()
                    retry = max(retry, int(when - time.time()) + 1)
                except (TypeError, ValueError):
                    pass
        raise XError(
            "RATE_LIMITED",
            "Session is cooling down; no account rotation is used.",
            retryable=True,
            retry_after=retry,
        )

    async def _fetch(self, api, query: Query, cursor: str | None) -> ProviderPage:
        op, target = query.operation, query.target
        kv = {"count": query.limit}
        if cursor:
            kv["cursor"] = cursor
        raw = None
        generator = None
        if op.startswith("search.") or op == "post.quotes":
            product = (
                "People"
                if op == "search.users"
                else {"latest": "Latest", "top": "Top", "media": "Media"}[query.sort]
            )
            text = f"quoted_tweet_id:{target}" if op == "post.quotes" else query.query
            generator = api.search_raw(text, limit=1, kv={**kv, "product": product})
        elif op == "post.post":
            raw = await api.tweet_details_raw(int(target))
        elif op in {"post.thread", "post.replies", "post.reposters"}:
            method = {
                "post.thread": "tweet_thread_raw",
                "post.replies": "tweet_replies_raw",
                "post.reposters": "retweeters_raw",
            }[op]
            generator = getattr(api, method)(int(target), limit=1, kv=kv)
        elif op.startswith("user."):
            profile = await api.user_by_login_raw(target)
            if profile is None:
                raise XError(
                    "PROVIDER_UNAVAILABLE", "Session profile lookup failed.", retryable=True
                )
            profiles = normalize_raw(profile.json(), "user.profile", target)
            if not profiles:
                raise XError(
                    "PUBLIC_ONLY",
                    "Account is unavailable, protected, or its public status cannot be verified.",
                )
            if op == "user.profile":
                return ProviderPage(self.name, data=profiles[0], completeness="entity")
            method = {
                "user.posts": "user_tweets_raw",
                "user.replies": "user_tweets_and_replies_raw",
                "user.media": "user_media_raw",
                "user.followers": "followers_raw",
                "user.following": "following_raw",
            }[op]
            generator = getattr(api, method)(int(profiles[0]["id"]), limit=1, kv=kv)
        elif op.startswith("community."):
            info = await api.community_info_raw(int(target))
            body = info.json() if info is not None else {}
            community = ((body.get("data") or {}).get("communityResults") or {}).get("result") or {}
            if not explicit_public(community):
                raise XError(
                    "PUBLIC_UNVERIFIED",
                    "Community visibility was not explicitly public; no collection data is returned.",
                )
            if op == "community.info":
                return ProviderPage(
                    self.name,
                    data={
                        "kind": "community",
                        "id": target,
                        "url": f"https://x.com/i/communities/{target}",
                        "name": community.get("name"),
                        "text": community.get("description", ""),
                        "member_count": community.get("member_count"),
                    },
                    completeness="entity",
                )
            method = "community_tweets_raw" if op == "community.posts" else "community_members_raw"
            generator = getattr(api, method)(int(target), limit=1, kv=kv)
        elif op.startswith("list."):
            method = "list_timeline_raw" if op == "list.posts" else "list_members_raw"
            generator = getattr(api, method)(int(target), limit=1, kv=kv)
        elif op.startswith("trends."):
            generator = api.trends_raw(op.split(".")[1], limit=1, kv=kv)
        if generator is not None:
            async with aclosing(generator):
                raw = await anext(generator, None)
        if raw is None:
            # The raw dependency can swallow upstream errors; never turn that into [].
            raise XError(
                "PROVIDER_UNAVAILABLE",
                "Session provider returned no verifiable page.",
                retryable=True,
            )
        body = raw.json()
        if not isinstance(body, dict) or not isinstance(body.get("data"), dict):
            raise XError("PROVIDER_CHANGED", "Session response format is not recognized.")
        if op.startswith("list."):
            info = body["data"].get("list") or {}
            if not explicit_public(info):
                raise XError(
                    "PUBLIC_UNVERIFIED",
                    "List visibility was not explicitly public; no collection data is returned.",
                )
        items = normalize_raw(body, op, target)
        if op == "post.post":
            if not items:
                raise XError("NOT_FOUND", "Public post is unavailable.")
            return ProviderPage(self.name, data=items[0], completeness="entity")
        cursor_type = "ShowMoreThreads" if op == "post.replies" else "Bottom"
        next_cursor = api._get_cursor(body, cursor_type)
        warnings = [
            "Session results include only explicitly public authors; unavailable/unknown authors are omitted."
        ]
        if op == "post.replies":
            warnings.append("Direct replies only; ranked source results are not exhaustive.")
            warnings.append(
                "Session replies use the source's default ranking; requested sort is not guaranteed."
            )
        if op.startswith("trends."):
            warnings.append(
                "Trend geography/personalization comes from the session source; locale is not a geographic filter."
            )
        return ProviderPage(self.name, items=items, next_cursor=next_cursor, warnings=warnings)
