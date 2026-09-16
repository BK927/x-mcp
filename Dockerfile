FROM ghcr.io/astral-sh/uv:0.12.9 AS uv
FROM python:3.12-slim

COPY --from=uv /uv /uvx /usr/local/bin/
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock README.md LICENSE THIRD_PARTY_NOTICES.md ./
COPY src ./src
RUN uv sync --frozen --no-dev --extra session \
    && useradd --uid 10001 --create-home app \
    && mkdir -p /state/x-mcp \
    && chown -R app:app /state \
    && chmod 700 /state/x-mcp

ENV PATH="/app/.venv/bin:$PATH" \
    X_MCP_STATE_DIR=/state/x-mcp \
    MCP_HOST=0.0.0.0 MCP_PORT=8766 PYTHONUNBUFFERED=1 TWS_TELEMETRY=0
USER app
VOLUME ["/state"]
EXPOSE 8766
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8766/healthz', timeout=3)"
CMD ["x-mcp", "serve", "--transport", "http"]
