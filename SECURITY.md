# Security

Use this server for one trusted operator. It is not a public multi-tenant API.
Never publish `.env`, state directories, browser cookie exports, account databases
or bearer secrets. Git and Docker ignore runtime credentials/state.

All HTTP, including loopback, requires a bearer secret of at least 32 characters. Use a TLS
reverse proxy and an exact `PUBLIC_BASE_URL`. Host/Origin validation remains
enabled. `/healthz` is intentionally unauthenticated and returns only `ok`.
The server does not implement web ChatGPT OAuth or dynamic client registration.
Loopback binding is not authentication: a reverse proxy/tunnel can expose it.
stdio remains available without an HTTP bearer token.

X session setup is a local CLI operation, not an MCP tool. Browser login is
manual. The optional session provider uses a single account, respects cooldowns,
and has bounded execution. Protected/unknown account visibility and unverified
collection visibility fail closed. No account-mutating routes are registered.

These tool restrictions do not reduce the authority of an X session cookie.
The current process can read plaintext `session.json` and `account.db`; host or
dependency compromise can expose them. A stolen MCP bearer token permits the
owner's research tools and saved results, but does not by itself expose a cookie
export endpoint. See the [credential threat model](docs/security-model.md) for
trust boundaries, residual risk and proposed isolation work.

Provider responses are projected to known data fields. Original post text is
preserved as untrusted data rather than treated as configuration or code.
Cursor HMACs bind requests to their provider, query, expiry and session context.
Input reference URLs are parsed; arbitrary URLs are not fetched. HTTP redirects
are disabled for the free API, and input/output response sizes are bounded.

To report a vulnerability, use GitHub's private vulnerability reporting if
available on this repository. Otherwise open an issue with only a non-sensitive
summary and ask for a private reporting channel. Do not post working session
cookies, private data or bearer tokens in an issue.
