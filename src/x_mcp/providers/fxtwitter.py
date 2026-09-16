from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

from .. import __version__
from ..errors import XError
from ..models import ProviderPage, Query
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
    "user.articles",
    "user.followers",
    "user.following",
    "trends.trending",
}


class FxTwitterProvider:
    name = "fxtwitter"

    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None):
        # Independent client: no X session, environment proxy credentials, or redirects.
        self.client = httpx.AsyncClient(
            base_url="https://api.fxtwitter.com",
            timeout=15,
            follow_redirects=False,
            trust_env=False,
            transport=transport,
            headers={
                "User-Agent": f"bk927-x-mcp/{__version__} (+https://github.com/BK927/x-mcp)",
                "Accept": "application/json",
            },
        )
        self._lock = asyncio.Lock()
        self._last_request = 0.0
        self._blocked_until = 0.0

    def supports(self, operation: str) -> bool:
        return operation in OPERATIONS

    async def close(self) -> None:
        await self.client.aclose()

    async def fetch(self, query: Query, cursor: str | None = None) -> ProviderPage:
        op, target = query.operation, query.target
        if not self.supports(op):
            raise XError("UNSUPPORTED", "This operation is not provided by FxTwitter.")
        params: dict[str, Any] = {"count": query.limit}
        if cursor:
            params["cursor"] = cursor
        if op.startswith("search."):
            path = "/2/typeahead" if op == "search.users" else "/2/search"
            params.update(q=query.query)
            if op == "search.posts":
                params["feed"] = query.sort
            else:
                params = {"q": query.query, "result_type": "users"}
        elif op.startswith("post."):
            view = op.split(".")[1]
            if view == "thread":
                path = f"/2/thread/{target}"
            elif view == "replies":
                path = f"/2/conversation/{target}"
                params["ranking_mode"] = "recency" if query.sort == "latest" else "likes"
            else:
                suffix = {"quotes": "/quotes", "reposters": "/reposts"}.get(view, "")
                path = f"/2/status/{target}{suffix}"
        elif op.startswith("user."):
            view = op.split(".")[1]
            suffix = {"profile": "", "posts": "/statuses", "replies": "/statuses"}.get(
                view, f"/{view}"
            )
            path = f"/2/profile/{target}{suffix}"
            if view == "replies":
                params["with_replies"] = "true"
            if view in {"posts", "replies"}:
                params["groupthreads"] = "false"
        else:
            path = "/2/trends"
            params["type"] = "trending"
        async with self._lock:
            wait = self._blocked_until - time.monotonic()
            if wait > 0:
                raise XError(
                    "RATE_LIMITED",
                    "Free API is cooling down.",
                    retryable=True,
                    retry_after=int(wait) + 1,
                )
            await asyncio.sleep(max(0, 0.25 - (time.monotonic() - self._last_request)))
            self._last_request = time.monotonic()
            try:
                # Bound incoming bytes too; downstream projection is not a memory limit.
                async with self.client.stream("GET", path, params=params) as response:
                    chunks = []
                    size = 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > 4 * 1024 * 1024:
                            raise XError(
                                "PROVIDER_CHANGED",
                                "Provider response exceeded the input size limit.",
                            )
                        chunks.append(chunk)
                    import json

                    try:
                        body = json.loads(b"".join(chunks)) if size else {}
                    except (ValueError, UnicodeError) as exc:
                        if response.status_code >= 400:
                            # Gateways may return HTML for 429/5xx. Preserve the
                            # HTTP failure classification without exposing it.
                            body = {}
                        else:
                            raise XError(
                                "PROVIDER_CHANGED",
                                "Free API did not return recognized JSON.",
                                retryable=True,
                            ) from exc
                    code = response.status_code
                    if isinstance(body, dict) and isinstance(body.get("code"), int):
                        code = max(code, body["code"])
                    if code == 429:
                        retry = response.headers.get("retry-after", "60")
                        retry_after = min(3600, max(1, int(retry))) if retry.isdigit() else 60
                        self._blocked_until = time.monotonic() + retry_after
                        raise XError(
                            "RATE_LIMITED",
                            "Free API rate limit reached.",
                            retryable=True,
                            retry_after=retry_after,
                        )
                    if code == 404 and op.startswith("search."):
                        raise XError(
                            "PROVIDER_UNAVAILABLE",
                            "Free search returned an ambiguous 404; this does not establish that no results exist.",
                            retryable=True,
                        )
                    if code == 404:
                        raise XError("NOT_FOUND", "Requested public content was not found.")
                    if code in {401, 403}:
                        raise XError(
                            "PROVIDER_UNAVAILABLE", "The free API denied access.", retryable=True
                        )
                    if code >= 500:
                        raise XError(
                            "PROVIDER_UNAVAILABLE",
                            "The free API is temporarily unavailable.",
                            retryable=True,
                        )
                    if code not in {200, 204} or not isinstance(body, dict):
                        raise XError(
                            "PROVIDER_CHANGED", "Free API returned an unsupported response."
                        )
            except httpx.TimeoutException as exc:
                raise XError("TIMEOUT", "Free API request timed out.", retryable=True) from exc
            except httpx.HTTPError as exc:
                raise XError(
                    "PROVIDER_UNAVAILABLE", "Free API connection failed.", retryable=True
                ) from exc
        try:
            return self._page(query, body)
        except (KeyError, TypeError, ValueError) as exc:
            raise XError("PROVIDER_CHANGED", "Free API response shape changed.") from exc

    def _page(self, query: Query, body: dict[str, Any]) -> ProviderPage:
        op = query.operation
        page = ProviderPage(provider=self.name)
        cursor = body.get("cursor") or {}
        page.next_cursor = cursor.get("bottom") if isinstance(cursor, dict) else None
        if op == "post.post":
            raw = body.get("status")
            if not isinstance(raw, dict):
                raise XError("NOT_FOUND", "Post is unavailable.")
            page.data = post(raw)
            page.completeness = "entity"
            return page
        if op == "user.profile":
            page.data = user(body["user"])
            page.completeness = "entity"
            return page
        if op == "post.thread":
            raw_items = [body.get("status"), *(body.get("thread") or [])]
            normalizer = post
            page.warnings.append("Thread contains only the chain returned by the source.")
        elif op == "search.users":
            raw_items, normalizer = body.get("users"), user
            page.next_cursor = None
            page.warnings.append(
                "Free user search provides typeahead suggestions, without upstream pagination."
            )
        elif op == "post.replies":
            # The focal post/thread are separate from replies; do not count them as replies.
            raw_items = body.get("replies")
            if isinstance(raw_items, dict):
                page.next_cursor = (raw_items.get("cursor") or {}).get("bottom") or page.next_cursor
                raw_items = raw_items.get("results")
            if raw_items is None:
                raw_items = body.get("results")
            if raw_items is None:
                raise XError("PROVIDER_CHANGED", "Conversation reply format is not recognized.")
            normalizer = post
            page.warnings.append("Replies are a ranked sample; no completeness guarantee.")
        elif op.startswith("trends."):
            raw_items, normalizer = body.get("trends"), trend
            page.warnings.append(
                "Trend geography/personalization is controlled by the provider, not inferred from your locale."
            )
        else:
            raw_items = body.get("results")
            normalizer = (
                user
                if op in {"search.users", "post.reposters", "user.followers", "user.following"}
                else post
            )
        if not isinstance(raw_items, list):
            raise XError("PROVIDER_CHANGED", "Provider list format is not recognized.")
        seen = set()
        expanded = []
        for raw in raw_items:
            if isinstance(raw, dict) and raw.get("type") == "thread":
                expanded.extend(raw.get("statuses") or [])
                if raw.get("truncated"):
                    page.completeness = "partial"
                    page.warnings.append("A source thread snippet was truncated upstream.")
            else:
                expanded.append(raw)
        for raw in expanded:
            if not isinstance(raw, dict):
                continue
            try:
                item = normalizer(raw)
            except XError as exc:
                if exc.code in {"NOT_FOUND", "PUBLIC_ONLY"}:
                    page.warnings.append("Unavailable or non-public items were omitted.")
                    continue
                raise
            if item["id"] not in seen:
                seen.add(item["id"])
                page.items.append(item)
        if op == "post.thread":
            focal = next((p for p in page.items if p["id"] == query.target), None)
            if not focal:
                raise XError("NOT_FOUND", "Public focal post is unavailable.")
            page.items = [p for p in page.items if p["author"]["id"] == focal["author"]["id"]]
        if op.startswith("search."):
            page.warnings.append("Search is a source sample, not an exhaustive archive.")
        return page
