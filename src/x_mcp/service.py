from __future__ import annotations

import asyncio
import hashlib
import re
from collections import Counter
from typing import Any
from urllib.parse import urlsplit

from .config import Settings
from .errors import XError, invalid
from .models import ProviderPage, Query, utc_now
from .providers.fxtwitter import OPERATIONS as FX_OPERATIONS
from .providers.fxtwitter import FxTwitterProvider
from .providers.session import OPERATIONS as SESSION_OPERATIONS
from .providers.session import SessionProvider
from .store import Store

ALL_OPERATIONS = sorted(FX_OPERATIONS | SESSION_OPERATIONS)


class Service:
    def __init__(self, settings: Settings, *, fx=None, session=None, store: Store | None = None):
        self.settings = settings
        self.store = store or Store(
            settings.state_dir, ttl=settings.result_ttl, max_bytes=settings.max_result_bytes
        )
        self.fx = fx or FxTwitterProvider()
        self.session = session or SessionProvider(settings.state_dir, settings.cookies_path)
        self.providers = {self.fx.name: self.fx, self.session.name: self.session}
        self._lock = asyncio.Lock()

    async def close(self):
        await self.fx.close()
        await self.session.close()
        self.store.close()

    def context(self, provider: str) -> str:
        return self.session.context() if provider == self.session.name else "public"

    def check_context(self, record: dict[str, Any]):
        if record["context"] != "public" and self.session.context() != record["context"]:
            raise XError(
                "SESSION_CHANGED", "Result belongs to a different X session; repeat the query."
            )

    def route(self, query: Query):
        available = [p for p in (self.fx, self.session) if p.supports(query.operation)]
        if not self.session.configured:
            available = [p for p in available if p is not self.session]
        if query.operation.startswith("search.") and self.session.configured:
            available.sort(key=lambda p: p is not self.session)
        if not available:
            if self.session.supports(query.operation):
                raise XError(
                    "AUTH_REQUIRED",
                    "This public operation requires the session extra and an owner-configured session.",
                )
            raise XError("UNSUPPORTED", "This operation is not supported.")
        return available

    async def fetch(self, provider, query: Query, cursor: str | None = None) -> ProviderPage:
        try:
            context = self.context(provider.name)
        except XError:
            context = "unconfigured"
        try:
            page = await provider.fetch(query, cursor)
        except XError as exc:
            self.store.record_health(
                provider.name,
                query.operation,
                {"checked_at": utc_now(), "ok": False, "code": exc.code, "context": context},
            )
            raise
        self.store.record_health(
            provider.name,
            query.operation,
            {"checked_at": utc_now(), "ok": True, "context": context},
        )
        return page

    async def query(
        self, query: Query, *, cursor: str | None = None, detail: str = "compact"
    ) -> dict[str, Any]:
        if query.operation not in ALL_OPERATIONS:
            raise invalid("Unsupported public operation.")
        if detail not in {"compact", "full"}:
            raise invalid("detail must be compact or full.")
        async with asyncio.timeout(self.settings.timeout), self._lock:
            if cursor:
                record, value = self.store.decode(cursor)
                if value["k"] != "page" or record["query_hash"] != query.fingerprint():
                    raise XError(
                        "CURSOR_MISMATCH",
                        "Use the same operation, target, query, and sorting with a continuation token.",
                    )
                self.check_context(record)
                offset = value["o"]
                if offset > len(record["items"]):
                    raise XError("INVALID_CURSOR", "Page offset is invalid.")
                if offset == len(record["items"]) and record["next"]:
                    # Never change provider during pagination, including on failure.
                    provider = self.providers[record["provider"]]
                    page = await self.fetch(provider, query, record["next"])
                    record = self.store.append(record, page)
                return self.store.render(record, offset=offset, limit=query.limit, detail=detail)
            routes = self.route(query)
            contexts = ":".join(self.context(p.name) for p in routes)
            cache_key = hashlib.sha256(f"{query.fingerprint()}:{contexts}".encode()).hexdigest()
            cached = self.store.cached(cache_key)
            if cached:
                self.check_context(cached)
                result = self.store.render(cached, limit=query.limit, detail=detail)
                return result
            previous = None
            for index, provider in enumerate(routes[:2]):
                try:
                    page = await self.fetch(provider, query)
                    if previous:
                        page.warnings.append(
                            f"Initial provider {previous} failed; this result uses {provider.name}."
                        )
                    record = self.store.create(query, page, self.context(provider.name))
                    ttl = 600 if page.data is not None else 120
                    self.store.cache(cache_key, record, ttl)
                    return self.store.render(record, limit=query.limit, detail=detail)
                except XError as exc:
                    if (
                        index == 0
                        and len(routes) > 1
                        and exc.retryable
                        and exc.code in {"PROVIDER_UNAVAILABLE", "TIMEOUT"}
                    ):
                        previous = provider.name
                        continue
                    raise
            raise XError("PROVIDER_UNAVAILABLE", "No provider completed this public query.")

    def result_get(
        self,
        result_id: str,
        *,
        cursor: str | None = None,
        item_id: str | None = None,
        field: str = "text",
        limit: int = 10,
        detail: str = "compact",
    ) -> dict[str, Any]:
        if (
            field not in {"text", "json"}
            or detail not in {"compact", "full"}
            or not 1 <= limit <= 50
        ):
            raise invalid("Invalid result selection.")
        if cursor:
            record, value = self.store.decode(cursor)
            if record["id"] != result_id:
                raise XError("CURSOR_MISMATCH", "Cursor belongs to another result.")
            self.check_context(record)
            if value["k"] == "text":
                if (item_id and item_id != value["i"]) or field != value["f"]:
                    raise XError(
                        "CURSOR_MISMATCH", "Keep the same item_id and field for text continuation."
                    )
                return self.store.text(record, value["i"], field=value["f"], offset=value["o"])
            if item_id:
                raise XError("CURSOR_MISMATCH", "An item text request cannot use a page cursor.")
            return self.store.render(
                record, offset=value["o"], limit=limit, detail=detail, local_only=True
            )
        record = self.store.get(result_id)
        self.check_context(record)
        if item_id:
            return self.store.text(record, item_id, field=field)
        return self.store.render(record, limit=limit, detail=detail, local_only=True)

    def analyze(self, result_ids: list[str], mode: str = "summary") -> dict[str, Any]:
        if not 1 <= len(result_ids) <= 10 or mode not in {
            "summary",
            "activity",
            "engagement",
            "links",
            "hashtags",
        }:
            raise invalid("Use 1 to 10 result IDs and a supported analysis mode.")
        records = [self.store.get(ident) for ident in dict.fromkeys(result_ids)]
        for record in records:
            self.check_context(record)
        unique = {}
        for record in records:
            for item in record["items"]:
                if item.get("kind") == "post":
                    unique[item["id"]] = item
        posts = list(unique.values())
        dates = sorted(p["created_at"] for p in posts if p.get("created_at"))
        data: dict[str, Any] = {
            "kind": "analysis",
            "id": "analysis",
            "mode": mode,
            "sample_size": len(posts),
            "period": {"start": dates[0] if dates else None, "end": dates[-1] if dates else None},
            "result_ids": [r["id"] for r in records],
            "source_has_more": any(r["next"] for r in records),
        }
        if mode in {"summary", "activity"}:
            days = Counter(p["created_at"][:10] for p in posts if p.get("created_at"))
            data["activity"] = [{"date": day, "posts": n} for day, n in sorted(days.items())[:100]]
            data["omitted_days"] = max(0, len(days) - 100)
            data["authors"] = len({p["author"]["id"] for p in posts})
        if mode in {"summary", "engagement"}:
            metrics = {}
            for key in ("likes", "reposts", "replies", "quotes", "views"):
                values = [p.get("metrics", {}).get(key) for p in posts]
                known = [v for v in values if isinstance(v, int) and not isinstance(v, bool)]
                metrics[key] = {
                    "sum": sum(known) if known else None,
                    "known_posts": len(known),
                    "missing_posts": len(values) - len(known),
                }
            data["engagement"] = metrics
        if mode in {"summary", "links"}:
            domains: Counter[str] = Counter()
            for p in posts:
                urls = [*p.get("links", []), *re.findall(r"https?://[^\s<>]+", p.get("text", ""))]
                for url in set(urls):
                    try:
                        host = urlsplit(url).hostname
                        if host:
                            domains[host.lower()[:253]] += 1
                    except ValueError:
                        pass
            data["link_domains"] = [
                {"domain": domain, "occurrences": n} for domain, n in domains.most_common(20)
            ]
        if mode in {"summary", "hashtags"}:
            tags: Counter[str] = Counter()
            for p in posts:
                found = {str(t).casefold() for t in p.get("hashtags", []) if isinstance(t, str)}
                found.update(
                    t.casefold() for t in re.findall(r"#([^\W#]+)", p.get("text", ""), re.UNICODE)
                )
                tags.update(t[:100] for t in found)
            data["hashtags"] = [{"tag": tag, "posts": n} for tag, n in tags.most_common(20)]
        page = ProviderPage(
            "local",
            data=data,
            completeness="sample_only",
            warnings=[
                "Computed only from saved public posts. No network fetch or LLM inference was performed; this is not a population estimate."
            ],
        )
        context = next((r["context"] for r in records if r["context"] != "public"), "public")
        record = self.store.create(Query(operation=f"analysis.{mode}"), page, context)
        return self.store.render(record, detail="full")

    def status(self, view: str = "capabilities") -> dict[str, Any]:
        auth_state = "not_configured"
        context = "unconfigured"
        if self.session.configured:
            try:
                context = self.session.context()
                auth_state = "configured_not_live_verified"
            except XError:
                auth_state = "invalid_session_file"
        health = {}
        for key, observed in self.store.health().items():
            expected = context if key.startswith(f"{self.session.name}:") else "public"
            if observed.get("context") == expected:
                health[key] = {k: v for k, v in observed.items() if k != "context"}
        session_checks = [v for k, v in health.items() if k.startswith(f"{self.session.name}:")]
        if any(v["ok"] for v in session_checks) and context != "unconfigured":
            auth_state = "live_verified_at_recorded_time"
        if any(v.get("code") == "SESSION_EXPIRED" for v in session_checks):
            auth_state = "session_expired_observed"
        data: dict[str, Any] = {
            "session": auth_state,
            "session_dependency": self.session.installed,
            "scope": "public_research_only",
            "paid_api": False,
            "max_result_bytes": self.settings.max_result_bytes,
        }
        if view == "health":
            data["observations"] = health
        elif view == "capabilities":
            capabilities = {}
            for operation in ALL_OPERATIONS:
                providers = {}
                for provider in (self.fx, self.session):
                    observed = health.get(f"{provider.name}:{operation}")
                    state = "available"
                    if not provider.supports(operation):
                        state = "unsupported"
                    elif provider is self.session and not provider.configured:
                        state = "requires_session"
                    elif (
                        observed
                        and not observed["ok"]
                        and observed["code"] not in {"NOT_FOUND", "PUBLIC_ONLY"}
                    ):
                        state = "degraded"
                    providers[provider.name] = {
                        "state": state,
                        "validation": "live_success"
                        if observed and observed["ok"]
                        else "not_verified",
                    }
                capabilities[operation] = providers
            data["capabilities"] = capabilities
            data["notes"] = [
                "Available means configured capability, not a current live success guarantee.",
                "Lists/communities require an explicit public visibility signal; otherwise PUBLIC_UNVERIFIED.",
                "Home feeds, notifications, bookmarks, DMs, protected content, and writes are unsupported.",
            ]
        else:
            raise invalid("Unknown status view.")
        return {"data": data}
