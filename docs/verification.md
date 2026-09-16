# Verification record — 2026-09-16

## Automated contract checks

The local Python 3.12.12 / Windows run passed **72 tests**. The CI workflow runs
the same suite on Linux, Windows and macOS and builds the Docker image with a
real HTTP handshake. See [current CI results](https://github.com/BK927/x-mcp/actions/workflows/ci.yml).
The locked environment uses the official Python MCP SDK 2.2.0 and twscrape 0.20.1.

Coverage includes:

- Normal, missing, deleted and protected data; unavailable counts stay null;
  Unicode, article blocks and grouped source threads are retained.
- First-page fallback, session-first search, no fallback on empty/404 entity/429,
  and no provider change during continuation.
- Overfetch buffering, duplicate IDs, repeated source cursors, altered/expired/
  mismatched tokens, session changes, cache expiry and SQLite restart recovery.
- Output-byte limits and exact reconstruction of long multilingual text and
  normalized JSON; original IDs, URLs, authors and dates remain available.
- Saved-only analysis and session binding of derived statistics.
- No cookie headers sent to FxTwitter; cookie-domain/format filtering, safe local
  files, manual-browser lifecycle through mocks, and sanitized errors.
- Pinned session raw-page bounds/generator closure, public collection gates,
  single-account enforcement, expiry surviving restart, telemetry disabled.
- Actual stdio subprocess initialize/tools/list/call; HTTP initialize/list/call,
  bearer rejection, minimal health endpoint and hostile-origin rejection.
- Mandatory authentication on every HTTP listener, including loopback behind
  a public reverse proxy; forwarded headers and cleared runtime token fail closed.

One upstream Starlette/AnyIO deprecation warning appears in the local test runner;
it is not a failing check. Tests never use real X sessions. Docker was not
available on the implementation workstation; its build/runtime checks run in CI.
The first published revision passed all three OS jobs and the Docker HTTP
smoke test in [this CI run](https://github.com/BK927/x-mcp/actions/runs/35083430136).

## Token benchmark

[Machine-readable report](token-benchmark.json) · [reproducible script](../scripts/benchmark_tokens.py)

```sh
uv run --frozen --extra session --extra browser python scripts/benchmark_tokens.py
```

Tokenizer: `o200k_base`. The full serialized MCP `tools/list` payload includes
all eight input schemas, output schemas, descriptions and annotations. It is
**3,230 tokens**, within the 6,000-token target. Server instructions and host
prompt wrappers are separate and are not included in this tools/list metric.

The six fixed cases are synthetic API-shaped lists: English, Korean and Japanese,
each at 10 and 20 posts. Both baseline and compact result contain the **same
number of posts**. This separates field-projection savings from simply returning
fewer items. Each source post includes a realistic repeated profile, raw text
metadata and the provider's extra fields. These are fixtures, not sampled live
traffic or a universal savings claim. Result IDs, timestamps and benchmark-only
cursor signing inputs are fixed so the report is reproducible.

| Language | Items | Raw tokens | Compact payload tokens | Reduction | Compact MCP wire tokens |
|---|---:|---:|---:|---:|---:|
| English | 10 | 4,073 | 1,217 | 70.12% | 2,483 |
| English | 20 | 8,123 | 2,196 | 72.97% | 4,461 |
| Korean | 10 | 4,833 | 1,407 | 70.89% | 2,863 |
| Korean | 20 | 9,643 | 2,576 | 73.29% | 5,221 |
| Japanese | 10 | 4,913 | 1,426 | 70.97% | 2,901 |
| Japanese | 20 | 9,803 | 2,621 | 73.26% | 5,311 |

Median normalized-payload reduction: **71.97%**, above the 50% target. The wire
column measures serialized `CallToolResult` containing both JSON text and
`structuredContent`; the JSON report also includes the corresponding raw wire
baseline. It is a conservative transport measurement, not a guarantee of how
every client constructs model context. Actual savings vary by post length,
selected detail, metadata, language, page size, cursor and client behavior.

## Public network checks

These explicitly opted-in probes use no owner cookies. They check reachability
at a point in time, not ongoing availability. Provider data is not committed.

| Operation / input | Result | Returned | Normalized bytes |
|---|---|---:|---:|
| post `20` | Success | 1 | 513 |
| profile `xdevelopers` | Success | 1 | 594 |
| user posts `xdevelopers`, limit 3 | Success; remainder retained | 3 | 1,795 |
| author thread `20` | Success | 1 | 579 |
| replies `20`, limit 3 | Success; ranked sample | 3 | 1,570 |
| post search `from:xdevelopers` | `PROVIDER_UNAVAILABLE` (ambiguous 404) | — | — |
| user suggestions `xdevelopers`, limit 3 | Success; saved suggestions remain | 3 | 1,282 |
| trending, limit 3 | Success; provider context | 3 | 990 |

An earlier direct user-post probe requested three entries but received twenty,
approximately 87 KB. The service therefore enforces its own page/byte limits.
User suggestions have no upstream continuation; extra saved suggestions can
still be paged locally. No normal empty search success is inferred from a 404.

## Limits of this verification

Actual manual browser login, imported live-session queries, and all session
views are **not live-account verified**. Their tests use synthetic transport
responses and synthetic local cookies. Public relationship, quote, reposter,
media and article routes have schema/fixture coverage but no recorded live
success in this table. List/community access may remain unavailable if the
upstream library does not provide an explicit public visibility marker.

No paid API, write action, protected-content query, web ChatGPT OAuth, multi-user
deployment or autonomous collector is implemented or tested. A source change can
break a route after these checks; inspect `x_status(view="health")` for your own
instance's dated observations. Configuration and recorded success are separate.
