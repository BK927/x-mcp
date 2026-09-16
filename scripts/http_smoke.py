"""Exercise a running container without contacting X or using real session data."""

import json
import os
import urllib.error
import urllib.request


def main():
    base = os.environ.get("SMOKE_BASE_URL", "http://127.0.0.1:8766")
    token = os.environ["MCP_ACCESS_TOKEN"]

    def request(path, body=None, *, authenticated=True):
        headers = {"Accept": "application/json, text/event-stream"}
        if authenticated:
            headers["Authorization"] = f"Bearer {token}"
        if body is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(
            base + path,
            headers=headers,
            data=json.dumps(body).encode() if body is not None else None,
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            return json.load(response)

    assert request("/healthz", authenticated=False) == {"status": "ok"}
    try:
        request("/mcp", {}, authenticated=False)
    except urllib.error.HTTPError as exc:
        assert exc.code == 401
    else:
        raise AssertionError("Unauthenticated request was accepted")
    init = request(
        "/mcp",
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "container-smoke", "version": "1"},
            },
        },
    )
    assert init["result"]["serverInfo"]["name"] == "x-research-mcp"
    listed = request("/mcp", {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    assert len(listed["result"]["tools"]) == 8
    status = request(
        "/mcp",
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "x_status", "arguments": {}},
        },
    )
    assert not status["result"]["isError"]
    assert status["result"]["structuredContent"]["data"]["scope"] == "public_research_only"
    print("Container health, authentication, MCP initialize, eight tools, and status passed.")


if __name__ == "__main__":
    main()
