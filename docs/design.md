# Design and external contract, v0.1

The adopted design is a public research AIO with eight task-oriented tools,
free API first, optional cookie sessions, no account mutations or private reads.
Python 3.12+, the official MCP SDK, Pydantic and SQLite form the core. Playwright
is an optional local setup dependency. `twscrape==0.20.1` is pinned and isolated.
`uv.lock` pins the full dependency graph for tested installations.

## Provider routing

`tool -> validated Query -> provider routing -> explicit projection -> SQLite -> bounded output`

FxTwitter handles compatible public views first. Configured session search uses
twscrape first. Session-only operations explain how to configure the optional
extra. One fallback is permitted on an initial transient unavailable/timeout
failure. Empty successes, missing content, permission failures and rate limits
do not trigger fallback. Continuations never change provider.

Search 404s are ambiguous and become `PROVIDER_UNAVAILABLE`, not a successful
empty result. No provider failure silently becomes an empty list. The pinned
session dependency's raw generator may itself swallow errors; a missing raw
page is therefore also an error. Session raw generators are closed after one
yield, use a finite item bound, and have a 25-second timeout under the tool's
30-second timeout. No password login or account-pool rotation is exposed.

Provider compatibility facts were researched against:

- [X hosted MCP](https://docs.x.com/tools/mcp) and [official pricing](https://docs.x.com/x-api/getting-started/pricing): paid route excluded.
- [FxTwitter API v2](https://docs.fxembed.com/api/introduction/) and [OpenAPI source](https://github.com/FxEmbed/FxEmbed/blob/main/docs/specs/fxtwitter-openapi.json).
- [twscrape](https://github.com/vladkens/twscrape), pinned release 0.20.1.
- [44-tool x-mcp](https://github.com/realaman90/x-mcp), [twikit-x-mcp](https://github.com/bintangtimurlangit/twikit-x-mcp), and [Xee-mcp](https://github.com/Aiyo28/Xee-mcp) as alternative design examples.
- [MCP tools contract](https://modelcontextprotocol.io/specification/2025-11-25/server/tools).

These are references, not bundled sources or a promise of provider uptime.

## Input and output

Tools use explicit typed parameters and `view` enums. No general HTTP executor,
untyped action dispatcher, arbitrary callback URL or cookie input is exposed.
Post IDs stay strings. Handles and supported X URLs are parsed locally; supplied
URLs are not fetched directly. `x_status(view="schema", tool="NAME")` returns
the actual registered input schema, avoiding a second hand-maintained schema.

Successful query results contain `data` or `items`, `result_id`, `page` and `meta`.
Metadata includes provider, operation, retrieval time, completeness and warnings.
Source text is marked `untrusted_external_data`. Missing observations stay null.
`structuredContent` conforms to the shared output schema; serialized JSON is
also returned as text for MCP compatibility. Errors set `isError=true` and carry
`error.code`, a sanitized message, retryability and optional wait seconds.

Compact posts retain ID, URL, author, time, text and likes/reposts/replies.
Compact text ends at 600 Unicode characters with `text_truncated`. Full mode adds
available metadata; it does not remove the 12 KiB cap. If a single full item
cannot fit, it is reduced to an explicitly marked compact excerpt. The original
normalized object remains available through `x_result_get(field="json")`.

## Durable pagination

Each source query creates a saved snapshot. SQLite stores its selection, provider,
session fingerprint, original normalized items, source cursor and visited cursor
history. Cache TTL is 600 seconds for entities, 120 seconds for collections.
Snapshots default to one hour and a maximum of 16 MiB per snapshot. Expired rows
are purged during startup/new queries. SQLite may retain allocated file space.

HMAC-authenticated opaque cursors bind result ID, query fingerprint, provider,
session context, offset and expiry. Secrets persist across restart. Limits and
rendering detail can change during pagination; selection and sort cannot.

The query tool consumes saved leftovers before fetching another source page.
New pages deduplicate IDs. Repeated source cursors, or three pages with no new
items, stop with a partial-result warning. API output byte limits never discard
unreturned items. Retrying the same cursor reads the same stored offset.

`x_result_get` is offline. Its `next_cursor` continues stored items/text only;
`source_cursor` signals that the original query tool can fetch more. Text chunks
carry exact character offsets. `field=json` chunks reconstruct the normalized
object, not raw GraphQL transport payloads. Session-bound snapshots and derived
analyses cannot be read after changing the session.

## Analysis and scope

`x_analyze` accepts up to ten saved result IDs, deduplicates posts, and computes
sample-only activity, engagement, link domains and hashtags. Missing metrics are
counted separately from zero; a wholly unobserved metric has a null sum. Dates
cover observed posts, not the nominal search window. No new network or LLM calls
occur. Activity shows at most 100 days, explicitly reporting omitted day count;
links/hashtags show at most 20 entries. Full source posts remain retrievable.

Lists and communities require an explicit public marker. Open membership is not
assumed to mean public visibility. Unknown/protected authors are omitted from
session results. Home timelines, bookmarks, notifications, DMs, account writes,
background collection and automatic translation are deliberately unsupported.
