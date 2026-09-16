"""Durable result snapshots and signed, query/provider/session-bound continuation."""

from __future__ import annotations

import base64
import hmac
import json
import secrets
import sqlite3
import time
from pathlib import Path
from typing import Any

from .auth import ensure_private_directory
from .errors import XError
from .models import ProviderPage, Query, dumps
from .normalize import compact


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


class Store:
    def __init__(self, directory: Path, *, ttl: int = 3600, max_bytes: int = 12_288):
        ensure_private_directory(directory)
        self.db = sqlite3.connect(directory / "research.db", check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS results (id TEXT PRIMARY KEY, expires REAL NOT NULL, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, id TEXT NOT NULL, expires REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS health (provider TEXT, operation TEXT, value TEXT, PRIMARY KEY(provider, operation));
        """)
        self.db.execute(
            "INSERT OR IGNORE INTO settings VALUES ('cursor_key', ?)", (secrets.token_hex(32),)
        )
        self.db.commit()
        self.key = bytes.fromhex(
            self.db.execute("SELECT value FROM settings WHERE key='cursor_key'").fetchone()[0]
        )
        self.ttl, self.max_bytes = ttl, max_bytes
        self.purge()

    def close(self) -> None:
        self.db.close()

    def purge(self) -> None:
        now = time.time()
        with self.db:
            self.db.execute("DELETE FROM results WHERE expires<=?", (now,))
            self.db.execute("DELETE FROM cache WHERE expires<=?", (now,))

    def cached(self, key: str) -> dict[str, Any] | None:
        row = self.db.execute(
            "SELECT id FROM cache WHERE key=? AND expires>?", (key, time.time())
        ).fetchone()
        if row:
            try:
                return self.get(row[0])
            except XError:
                pass
        return None

    def cache(self, key: str, record: dict[str, Any], seconds: int) -> None:
        with self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO cache VALUES (?,?,?)",
                (key, record["id"], min(record["expires"], time.time() + seconds)),
            )

    def create(self, query: Query, page: ProviderPage, context: str) -> dict[str, Any]:
        self.purge()
        unique = {}
        for item in page.items:
            unique.setdefault((item.get("kind"), item.get("id")), item)
        record = {
            "id": secrets.token_urlsafe(18),
            "expires": time.time() + self.ttl,
            "query": query.model_dump(),
            "query_hash": query.fingerprint(),
            "provider": page.provider,
            "context": context,
            "items": [page.data] if page.data is not None else list(unique.values()),
            "entity": page.data is not None,
            "next": page.next_cursor,
            "retrieved_at": page.retrieved_at,
            "warnings": page.warnings,
            "completeness": page.completeness,
            "seen_cursors": [],
            "empty_pages": 0,
        }
        self.save(record)
        return record

    def save(self, record: dict[str, Any]) -> None:
        raw = dumps(record)
        if len(raw.encode()) > 16 * 1024 * 1024:
            raise XError("RESULT_CAPACITY", "This snapshot reached 16 MiB. Start a narrower query.")
        with self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO results VALUES (?,?,?)",
                (record["id"], record["expires"], raw),
            )

    def get(self, ident: str) -> dict[str, Any]:
        row = self.db.execute("SELECT value, expires FROM results WHERE id=?", (ident,)).fetchone()
        if row is None or row[1] <= time.time():
            raise XError(
                "RESULT_EXPIRED", "Saved result is missing or expired; repeat the original query."
            )
        return json.loads(row[0])

    def append(self, record: dict[str, Any], page: ProviderPage) -> dict[str, Any]:
        if page.provider != record["provider"] or page.data is not None:
            raise XError("PROVIDER_CHANGED", "Continuation provider or response type changed.")
        used = record["next"]
        known = {(x.get("kind"), x.get("id")) for x in record["items"]}
        additions = []
        for item in page.items:
            key = (item.get("kind"), item.get("id"))
            if key not in known:
                known.add(key)
                additions.append(item)
        record["items"].extend(additions)
        record["empty_pages"] = 0 if additions else record["empty_pages"] + 1
        if used:
            record["seen_cursors"].append(used)
        record["next"] = page.next_cursor
        record["warnings"] = list(dict.fromkeys([*record["warnings"], *page.warnings]))[:20]
        if (page.next_cursor and page.next_cursor in record["seen_cursors"]) or record[
            "empty_pages"
        ] >= 3:
            record["next"] = None
            record["completeness"] = "partial"
            record["warnings"].append(
                "Pagination stopped because the provider repeated a cursor or returned three pages without new items."
            )
        self.save(record)
        return record

    def token(
        self,
        record: dict[str, Any],
        offset: int,
        *,
        kind: str = "page",
        item: str = "",
        field: str = "text",
    ) -> str:
        value = {
            "v": 1,
            "r": record["id"],
            "o": offset,
            "k": kind,
            "e": int(record["expires"]),
            "q": record["query_hash"],
            "c": record["context"],
            "p": record["provider"],
        }
        if kind == "text":
            value.update(i=item, f=field)
        body = b64(dumps(value).encode())
        signature = b64(hmac.digest(self.key, body.encode(), "sha256"))
        return f"{body}.{signature}"

    def decode(self, token: str) -> tuple[dict[str, Any], dict[str, Any]]:
        try:
            if len(token) > 4096:
                raise ValueError
            body, signature = token.split(".")
            expected = b64(hmac.digest(self.key, body.encode(), "sha256"))
            if not hmac.compare_digest(signature, expected):
                raise ValueError
            value = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
            if (
                value["v"] != 1
                or not isinstance(value["o"], int)
                or value["o"] < 0
                or value["k"] not in {"page", "text"}
            ):
                raise ValueError
            if value["e"] <= time.time():
                raise XError("CURSOR_EXPIRED", "Continuation expired; repeat the original query.")
            record = self.get(value["r"])
            if any(
                value[k] != record[v]
                for k, v in {"q": "query_hash", "c": "context", "p": "provider"}.items()
            ):
                raise ValueError
            return record, value
        except XError:
            raise
        except (ValueError, TypeError, KeyError, UnicodeError) as exc:
            raise XError(
                "INVALID_CURSOR", "Continuation token is invalid or has been modified."
            ) from exc

    def envelope(self, record: dict[str, Any]) -> dict[str, Any]:
        return {
            "result_id": record["id"],
            "meta": {
                "provider": record["provider"],
                "operation": record["query"]["operation"],
                "retrieved_at": record["retrieved_at"],
                "completeness": record["completeness"],
                "warnings": record["warnings"],
                "content_trust": "untrusted_external_data",
            },
        }

    def size(self, value: Any) -> int:
        return len(dumps(value).encode())

    def render(
        self,
        record: dict[str, Any],
        *,
        offset: int = 0,
        limit: int = 10,
        detail: str = "compact",
        local_only: bool = False,
    ) -> dict[str, Any]:
        if not 0 <= offset <= len(record["items"]):
            raise XError("INVALID_CURSOR", "Continuation offset is outside the saved result.")
        payload = self.envelope(record)
        chosen = []
        end = offset

        def finish() -> dict[str, Any]:
            more_saved = end < len(record["items"])
            more_source = bool(record["next"])
            data = dict(payload)
            if record["entity"] and chosen:
                data["data"] = chosen[0]
            else:
                data["items"] = list(chosen)
            data["page"] = {
                "returned": len(chosen),
                "next_cursor": self.token(record, end)
                if more_saved or (more_source and not local_only)
                else None,
            }
            if local_only and more_source and not more_saved:
                data["page"]["source_cursor"] = self.token(record, end)
            return data

        for item in record["items"][offset : offset + limit]:
            candidate = compact(item, detail)
            chosen.append(candidate)
            end += 1
            if self.size(finish()) <= self.max_bytes:
                continue
            chosen.pop()
            end -= 1
            if chosen:
                break
            # Keep the full original in SQLite. Even a single very long post fits
            # as an explicit excerpt, retrievable using field=text or field=json.
            candidate = compact(item, "compact")
            candidate["fields_truncated"] = True
            for bound in (600, 300, 100, 32):
                shortened = self._shorten(candidate, bound)
                chosen[:] = [shortened]
                end = offset + 1
                if self.size(finish()) <= self.max_bytes:
                    break
            else:
                raise XError(
                    "RESULT_TOO_LARGE",
                    "Use x_result_get with item_id and field=json to read this object in chunks.",
                )
            break
        return finish()

    @staticmethod
    def _shorten(value: Any, bound: int, key: str = "") -> Any:
        if isinstance(value, str) and key not in {"id", "url", "created_at", "handle"}:
            return value[:bound]
        if isinstance(value, dict):
            return {k: Store._shorten(v, bound, k) for k, v in value.items()}
        if isinstance(value, list):
            return [Store._shorten(x, bound) for x in value[:3]]
        return value

    def text(
        self, record: dict[str, Any], item_id: str, *, field: str = "text", offset: int = 0
    ) -> dict[str, Any]:
        item = next((x for x in record["items"] if str(x.get("id")) == item_id), None)
        if item is None:
            raise XError("NOT_FOUND", "This item is not present in the saved result.")
        source = dumps(item) if field == "json" else item.get("text", "")
        if not isinstance(source, str) or not 0 <= offset <= len(source):
            raise XError("INVALID_CURSOR", "Text continuation is outside the saved content.")
        payload = self.envelope(record)

        def build(end: int):
            return {
                **payload,
                "data": {
                    "item_id": item_id,
                    "field": field,
                    "text": source[offset:end],
                    "offset": offset,
                    "next_offset": end,
                    "total_chars": len(source),
                },
                "page": {
                    "returned": 1,
                    "next_cursor": self.token(record, end, kind="text", item=item_id, field=field)
                    if end < len(source)
                    else None,
                },
            }

        low, high = offset, min(len(source), offset + 4000)
        while low < high:
            mid = (low + high + 1) // 2
            if self.size(build(mid)) <= self.max_bytes:
                low = mid
            else:
                high = mid - 1
        if low == offset and offset < len(source):
            raise XError(
                "RESULT_TOO_LARGE", "Response metadata exceeds the configured output limit."
            )
        return build(low)

    def record_health(self, provider: str, operation: str, value: dict[str, Any]) -> None:
        with self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO health VALUES (?,?,?)", (provider, operation, dumps(value))
            )

    def health(self) -> dict[str, dict[str, Any]]:
        return {
            f"{provider}:{operation}": json.loads(value)
            for provider, operation, value in self.db.execute(
                "SELECT provider, operation, value FROM health"
            )
        }
