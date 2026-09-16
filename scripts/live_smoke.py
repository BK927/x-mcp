"""Explicit, bounded public-network smoke test. Never loads an owner session."""

import asyncio
import json
from pathlib import Path

from x_mcp.config import Settings
from x_mcp.errors import XError
from x_mcp.models import Query
from x_mcp.service import Service


async def main():
    root = Path("artifacts/live-state").resolve()
    settings = Settings(state_dir=root, session_file=root / "disabled-session.json")
    service = Service(settings)
    checks = [
        Query(operation="post.post", target="20"),
        Query(operation="user.profile", target="xdevelopers"),
        Query(operation="user.posts", target="xdevelopers", limit=3),
        Query(operation="post.thread", target="20", limit=3),
        Query(operation="post.replies", target="20", limit=3),
        Query(operation="search.posts", query="from:xdevelopers", limit=3),
        Query(operation="search.users", query="xdevelopers", limit=3),
        Query(operation="trends.trending", limit=3),
    ]
    results = []
    try:
        for query in checks:
            try:
                response = await service.query(query)
                results.append(
                    {
                        "operation": query.operation,
                        "ok": True,
                        "bytes": service.store.size(response),
                        "returned": response["page"]["returned"],
                        "has_more": bool(response["page"]["next_cursor"]),
                        "provider": response["meta"]["provider"],
                    }
                )
            except XError as exc:
                results.append({"operation": query.operation, "ok": False, "code": exc.code})
        print(json.dumps(results, indent=2))
        Path("artifacts/live-smoke.json").write_text(
            json.dumps(results, indent=2), encoding="utf-8"
        )
    finally:
        await service.close()


if __name__ == "__main__":
    asyncio.run(main())
