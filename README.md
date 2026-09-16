# X Research MCP

[한국어](README.ko.md) · [Design and API contract](docs/design.md) · [Verification](docs/verification.md)

A read-only, self-hosted MCP server for **public X research**. Eight task-oriented
tools provide posts, threads, replies, profiles, search, relationships, public
collections, trends, and analysis of saved results. It uses the free FxTwitter
API first and an optional owner-supplied X session through twscrape where needed.
There are no paid API calls or server-side LLM calls.

**0.1.0 status:** source installation is supported; this is not a claim of PyPI
publication. Public post/profile/timeline/thread/reply/trend probes succeeded on
2026-09-16. Free post search returned ambiguous 404s and is reported as unavailable;
free user suggestions succeeded through the typeahead route.
The session adapter is covered with synthetic tests but has **not** been tested
against an owner's live account. Collections require an explicit public-visibility
signal and fail closed when the provider does not supply it. See the
[capability table](docs/providers.md) before relying on a particular view.

## Install and run

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```sh
git clone https://github.com/BK927/x-mcp.git
cd x-mcp
uv sync --frozen --no-dev
uv run --frozen --no-dev x-mcp serve
```

No X login is needed for the public API. Generic local MCP configuration:

```json
{
  "mcpServers": {
    "x-research": {
      "command": "uv",
      "args": ["run", "--frozen", "--no-dev", "--directory", "/absolute/path/x-mcp", "x-mcp", "serve"]
    }
  }
}
```

Use an absolute Windows path such as `C:/Users/you/repo/x-mcp` when applicable.
The executable is `x-mcp`; the distribution is **bk927-x-mcp**. The generic PyPI
name `x-mcp` is not this project. Repository `main` can change; check out a reviewed
commit for reproducible source installations.

## Tools

| Tool | Views / use |
|---|---|
| `x_search` | Public posts or users; posts: latest/top/media |
| `x_post_get` | post, author thread, replies, quotes, reposters |
| `x_user_get` | profile, posts, posts with replies, media, articles, followers, following |
| `x_collection_get` | Public list posts/members; community info/posts/members, subject to visibility proof |
| `x_trends_get` | trending; session also supports news/sport/entertainment |
| `x_analyze` | Saved-post activity, engagement, link domains, hashtags; sample statistics |
| `x_result_get` | Saved items and lossless text/JSON chunks, without network |
| `x_status` | capabilities, recorded health, or one tool's schema |

Examples: “Read this X thread and cite its posts”; “Find public posts discussing
MCP and show ten at a time”; “Compare reaction counts in these saved results,
keeping missing metrics separate from zero.”

All tools are read-only. No posting, likes, following changes, DMs, bookmarks,
personal home feeds, notifications, account management, or protected content.
Search and replies are samples, not a complete X archive. Trend geography is
provider-controlled and is not inferred from the client's language.

## Optional session: two setup methods

Install the session extra, and keep `--extra session` in the MCP launch command:

```sh
uv sync --frozen --no-dev --extra session
uv run --frozen --no-dev --extra session x-mcp auth import --file /private/path/export.json
uv run --frozen --no-dev --extra session x-mcp serve
```

Import accepts a JSON cookie list, Playwright storage-state JSON, a dictionary
containing `auth_token` and `ct0`, or a Netscape cookie file. Only those two X
cookies are retained. Do not paste them into a chat or tool argument.

Alternatively, log in manually in a fresh dedicated browser:

```sh
uv sync --frozen --no-dev --extra session --extra browser
uv run --frozen --no-dev --extra session --extra browser playwright install chromium
uv run --frozen --no-dev --extra session --extra browser x-mcp auth login
```

Finish authentication in the window, then press Enter in the terminal. This does
not import an everyday browser profile, automate passwords, or bypass challenges.
The browser closes after saving the same session file used by `auth import`.
It is not needed while the server runs. A headless server can mount a session
file prepared on a trusted local machine.

`x-mcp auth status` validates file presence/format only. `x-mcp doctor` reports
sanitized configuration and recorded health. `x-mcp doctor --live` explicitly
queries one public post, profile, and search, using the configured routes.
Session expiry requires reconnecting the account; there is no account rotation.

## Compact responses and continuation

Lists default to ten items, at most fifty. `detail=compact` preserves post ID,
URL, author, timestamp, text and basic reaction counts. Long text is excerpted at
600 characters with a marker. `full` requests extra fields but still obeys the
12 KiB normalized-payload cap. Both MCP text and structured representations are
provided for compatibility, so clients may consume approximately twice the
payload's tokens; benchmarks report that representation too.

Use a query response's `page.next_cursor` with **the original tool and unchanged
selection arguments**. Output-limited leftovers are served before another source
page is fetched. Provider cursors are never mixed. Stored results last one hour
and survive restarts in the same state directory.

For full text: `x_result_get(result_id=..., item_id=...)`. Continue with its
`page.next_cursor`. Use `field=json` for lossless chunks of the entire normalized
item. For saved item pages, `x_result_get` never fetches upstream; its
`page.source_cursor`, when present, must be passed to the original query tool.
`x_analyze` processes only posts already saved, not unvisited source pages.

The fixed EN/KO/JA list benchmark meets the 6,000-token tool-list and 50% median
payload-reduction targets. Actual savings depend on workload and client; see
[the methodology and results](docs/verification.md).

## Personal HTTP server

```sh
uv run --frozen --no-dev --extra session x-mcp serve --transport http
```

Endpoints: `http://127.0.0.1:8766/mcp`, `http://127.0.0.1:8766/healthz`.
Set `MCP_ACCESS_TOKEN` to a random secret of at least 32 characters before starting
HTTP, including on loopback. For HTTPS ingress set `PUBLIC_BASE_URL=https://x-mcp.example.com`
to your exact origin. Clients send `Authorization: Bearer ...`.

Docker is a single-user, single-instance deployment with a persistent state
volume. See [deployment instructions](docs/deployment.md). Web ChatGPT-specific
OAuth, multi-user SaaS, Cloud Run and background collectors are outside v0.1.

## Configuration and storage

| Environment variable | Default |
|---|---|
| `X_MCP_STATE_DIR` | OS user-data directory `bk927-x-mcp`; use a dedicated directory |
| `X_MCP_SESSION_FILE` | `session.json` inside state directory |
| `X_MCP_MAX_RESULT_BYTES` | 12288; configurable 4096–32768 |
| `X_MCP_RESULT_TTL` | 3600 seconds; configurable 60–86400 |
| `MCP_HOST`, `MCP_PORT` | 127.0.0.1, 8766 |
| `MCP_ACCESS_TOKEN` | Empty; mandatory for all HTTP; stdio does not require it |
| `PUBLIC_BASE_URL` | Empty; exact HTTPS origin for remote host/origin validation |

State contains public-result snapshots, cached queries, a cursor signing key,
health observations and optional session/account files. Queries may themselves
be sensitive. Files stay on your machine; protect the whole state directory.
FxTwitter receives public lookup IDs/handles/searches, **never X cookies**.
twscrape telemetry is disabled. See [privacy](PRIVACY.md) and [security](SECURITY.md).
X cookies are account credentials, not read-scoped API tokens. The current process
can read plaintext session files and its account DB; do not replicate a primary
account's cookies across cloud workers. See the [credential threat model](docs/security-model.md).

## Development

```sh
uv sync --frozen --extra session --extra browser
uv run --frozen --extra session --extra browser ruff check src tests scripts
uv run --frozen --extra session --extra browser pytest -q
uv run --frozen --extra session --extra browser python scripts/benchmark_tokens.py
```

`scripts/live_smoke.py` makes explicitly opted-in public network calls and stores
only local artifacts. CI uses fixtures, MCP process/HTTP checks and a Docker
smoke test. Browser login and live account access remain operator-run checks.

MIT. Unofficial and unaffiliated with X Corp. Free means no paid data API is
called; provider availability, access terms and future pricing can change.
