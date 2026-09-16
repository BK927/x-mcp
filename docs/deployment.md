# Installation and personal HTTP deployment

Use Python 3.12+ and [uv](https://docs.astral.sh/uv/getting-started/installation/). The source package is `bk927-x-mcp`, and the command is `x-mcp`. No PyPI publication is claimed by this repository.

## Local stdio

```sh
git clone https://github.com/BK927/x-mcp.git
cd x-mcp
uv sync --frozen
uv run --frozen x-mcp doctor
uv run --frozen x-mcp serve
```

An MCP host starts the last command as a subprocess. See [stdio configuration](../examples/mcp-stdio.json). Replace the checkout path; Windows paths in JSON need doubled backslashes or forward slashes. The CLI sends protocol messages to stdout and diagnostic logs to stderr.

## Optional owner session

```sh
uv sync --frozen --extra session --extra browser
uv run --frozen --extra session --extra browser playwright install chromium
uv run --frozen --extra session --extra browser x-mcp auth login
```

Log in manually in the dedicated Chromium window, then return to the terminal and press Enter. The window closes after only `auth_token` and `ct0` are saved. Alternatively:

```sh
uv run --frozen --extra session x-mcp auth import --file /absolute/private/path/export.json
uv run --frozen --extra session x-mcp auth status
uv run --frozen --extra session x-mcp serve
```

The import accepts browser cookie JSON, a Playwright cookie container, a flat two-cookie object, or Netscape cookie text. Import reads the named file locally. Nothing is uploaded through an MCP argument. Cookie values are not printed. Securely handle the original export yourself; the importer does not remove it. Keep `--extra session` in the MCP launch command: uv may otherwise remove optional dependencies when synchronizing. See [session stdio example](../examples/mcp-stdio-session.json).

`auth status` verifies local format only. `doctor --live` performs explicit post/profile/search probes and may use your configured session for search. This is opt-in network activity. Session results require explicitly public authors. Collections additionally require explicit public visibility; an unknown signal returns `PUBLIC_UNVERIFIED`.

## Docker and TLS

```sh
cp .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(32))"
# Put the generated value in .env as MCP_ACCESS_TOKEN.
docker compose up -d --build
```

Compose binds `127.0.0.1:8766` on the host, stores state in a named volume, and runs as UID 10001 with a read-only root filesystem. `/healthz` is an unauthenticated minimal liveness response; `/mcp` requires the bearer token. The image includes the session adapter but no browser. Every HTTP launch, including a loopback listener, requires a random token of at least 32 printable ASCII characters without whitespace. A proxy/tunnel can publish loopback, so the listening address never exempts authentication. Local stdio does not require this token.

For a personal HTTPS endpoint, set `PUBLIC_BASE_URL=https://your-host.example` and put a TLS reverse proxy in front of the loopback port. An example Caddy configuration:

```caddyfile
your-host.example {
    reverse_proxy 127.0.0.1:8766
}
```

Preserve `Host` and `Authorization`; do not log authorization headers or request bodies. The MCP server allows only loopback hosts plus the exact configured HTTPS origin. Client requests from another browser origin are rejected. `PUBLIC_BASE_URL` takes an origin, without `/mcp`. The client endpoint includes `/mcp`; see [HTTP client shape](../examples/mcp-http.json). Each host's configuration format may differ. This server uses a personal bearer token and does not implement OAuth or web ChatGPT connector authorization.

To use a session in Docker, prepare `session.json` locally, make it readable by container UID 10001 only, and add an override such as:

```yaml
services:
  x-mcp:
    environment:
      X_MCP_SESSION_FILE: /run/secrets/x-session.json
    volumes:
      - /absolute/private/session.json:/run/secrets/x-session.json:ro
```

The source file is mounted read-only; the adapter keeps a second private cookie copy in `/state/x-mcp/account.db`. Read-only mounts prevent writes to the source file; they do not prevent the process from reading/exfiltrating it. Both copies are plaintext at the application layer. Refresh the mount when the session expires. Do not mount a complete browser profile. Backups of the state volume contain sensitive session and research data. Prefer one trusted credential-holding host instead of cookie replication across workers. See the [security model](security-model.md).

Run one process/replica per state directory. This implementation serializes provider requests; it is not a multi-user service. A token grants access to the owner's saved research. Rotate it by changing the environment and restarting the server. Do not publish `.env`, cookie exports, or the state volume.

## Environment

See the [README settings table](../README.md#configuration-and-storage). `.env` is consumed by Compose only; for direct CLI use export environment variables in the shell or supply the MCP host's `env` configuration. Use a dedicated `X_MCP_STATE_DIR` subdirectory, never a home or project root. Default paths follow the operating system's per-user application-data convention.

The HTTP transport is Streamable HTTP, stateless at the protocol level. SQLite preserves research snapshots and cursor signing keys across process restarts. Mount the state volume consistently; replacing it invalidates existing continuation tokens.
