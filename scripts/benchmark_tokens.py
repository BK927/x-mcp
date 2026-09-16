"""Reproducible synthetic EN/KO/JA fixture benchmark; no X or model API calls."""

import argparse
import asyncio
import json
import statistics
import tempfile
from pathlib import Path

import tiktoken

from x_mcp.config import Settings
from x_mcp.models import ProviderPage, Query, dumps
from x_mcp.normalize import post
from x_mcp.server import create_server, result
from x_mcp.service import Service


def fixture(language: str) -> dict:
    text = {
        "en": "Public research should preserve evidence, dates and source links. Try a small page before loading more. #MCP #Research",
        "ko": "공개 자료를 조사할 때에는 원문과 작성 시각, 출처 링크를 함께 확인합니다. 먼저 작은 페이지로 읽고 필요한 내용만 더 가져옵니다. #MCP #연구",
        "ja": "公開情報を調べるときは原文と日時、出典のリンクを確認します。小さなページから読み、必要な情報だけを追加で取得します。 #MCP #調査",
    }[language]
    author = {
        "id": "10",
        "screen_name": "example",
        "name": "Example Research",
        "description": text,
        "raw_description": {"text": text, "facets": []},
        "followers": 1200,
        "following": 80,
        "statuses": 3000,
        "likes": 1000,
        "media_count": 150,
        "url": "https://x.com/example",
        "protected": False,
        "joined": "Tue Mar 21 20:50:14 +0000 2006",
        "location": "Online",
        "avatar_url": "https://pbs.twimg.com/profile_images/123456789/avatar_normal.jpg",
        "banner_url": "https://pbs.twimg.com/profile_banners/123456789/1700000000",
        "website": {"url": "https://example.com/research", "display_url": "example.com/research"},
        "verification": {"verified": False, "verified_at": None, "type": None},
    }
    items = []
    for n in range(20):
        items.append(
            {
                "type": "status",
                "id": str(1000 + n),
                "url": f"https://x.com/example/status/{1000 + n}",
                "text": text,
                "raw_text": {"text": text, "display_text_range": [0, len(text)], "facets": []},
                "author": author,
                "likes": n,
                "reposts": 2,
                "replies": 1,
                "quotes": 0,
                "bookmarks": 1,
                "views": None,
                "created_at": "Tue Nov 14 22:13:20 +0000 2023",
                "created_timestamp": 1700000000,
                "is_note_tweet": False,
                "community_note": None,
                "lang": language,
                "replying_to": None,
                "media": {},
                "source": "Twitter Web App",
                "provider": "twitter",
                "reposted_by": None,
                "embed_card": "tweet",
            }
        )
    return {
        "code": 200,
        "results": items,
        "cursor": {"top": "synthetic-top", "bottom": "synthetic-bottom"},
    }


async def benchmark():
    encoding = tiktoken.get_encoding("o200k_base")

    def tokens(value):
        return len(encoding.encode(dumps(value), disallowed_special=()))

    with tempfile.TemporaryDirectory(prefix="x-mcp-bench-") as temporary:
        service = Service(Settings(state_dir=Path(temporary) / "state"))
        service.store.key = b"deterministic-benchmark-only-key!"
        try:
            tools = await create_server(service).list_tools()
            full_schema = {"tools": [t.model_dump(by_alias=True, exclude_none=True) for t in tools]}
            rows = []
            for language in ("en", "ko", "ja"):
                raw = fixture(language)
                page = ProviderPage(
                    "fxtwitter",
                    items=[post(p) for p in raw["results"]],
                    next_cursor="synthetic-bottom",
                    retrieved_at="2026-09-16T00:00:00Z",
                )
                record = service.store.create(
                    Query(operation="user.posts", target="example"), page, "public"
                )
                record.update(id=f"benchmark-{language}", expires=4102444800)
                for limit in (10, 20):
                    compact = service.store.render(record, limit=limit)
                    # Equal-item projection comparison separates pagination savings.
                    baseline = {**raw, "results": raw["results"][: compact["page"]["returned"]]}
                    compact_wire = result(compact).model_dump(by_alias=True, exclude_none=True)
                    baseline_wire = result(baseline).model_dump(by_alias=True, exclude_none=True)
                    rows.append(
                        {
                            "language": language,
                            "requested_items": limit,
                            "returned_items": compact["page"]["returned"],
                            "raw_equal_item_tokens": tokens(baseline),
                            "compact_payload_tokens": tokens(compact),
                            "payload_reduction_percent": round(
                                100 * (1 - tokens(compact) / tokens(baseline)), 2
                            ),
                            "raw_compat_wire_tokens": tokens(baseline_wire),
                            "compact_compat_wire_tokens": tokens(compact_wire),
                        }
                    )
            report = {
                "tokenizer": "o200k_base",
                "fixture": "deterministic synthetic API-shaped EN/KO/JA lists; not a live workload",
                "tools": len(tools),
                "tool_list_tokens": tokens(full_schema),
                "median_payload_reduction_percent": round(
                    statistics.median(row["payload_reduction_percent"] for row in rows), 2
                ),
                "cases": rows,
            }
            report["targets_pass"] = (
                report["tool_list_tokens"] <= 6000
                and report["median_payload_reduction_percent"] >= 50
            )
            return report
        finally:
            await service.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = asyncio.run(benchmark())
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.output:
        args.output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    if not report["targets_pass"]:
        raise SystemExit(1)
