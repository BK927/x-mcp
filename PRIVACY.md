# Privacy

This single-owner server sends public reference IDs, handles and search queries
to FxTwitter when using its free public API. Optional session requests go to X
using the owner's session; session cookies are never sent to FxTwitter. Provider
operators have their own policies. Search queries can contain sensitive text.

Local state includes public data snapshots, queries, provider health, a cursor
signing key, and optionally `session.json` and twscrape's `account.db`. Cookies
are credentials. They are stored locally with restricted filesystem access,
not encrypted by this application. Use OS disk protection and protect backups.
Only `auth_token` and `ct0` are imported; no passwords or ordinary browser profile
are read. The browser setup uses an isolated context and closes it afterward.

There is no application telemetry, advertising, LLM API or paid data API. The
optional twscrape dependency's telemetry is explicitly disabled before its
network runtime initializes. Its automatic raw-data error-dump parsers are not
used. Logs contain sanitized error classes/codes, not upstream response bodies,
cookie values or HTTP authorization headers. HTTP access logs are disabled.

Snapshot TTL defaults to one hour; expiry is enforced at read time and purged
on startup/new queries. This is logical expiry, not secure erasure of SQLite or
backups. Removing the dedicated state directory after stopping the server
removes local snapshots, signing key and account state. Also remove any
separately mounted session file and revoke the X session if no longer needed.

All returned posts are external untrusted content. The server does not interpret
post text as instructions and does not follow links embedded in posts.
