import json

import httpx
import pytest
from conftest import FakeProvider, make_post
from jsonschema import validate
from starlette.testclient import TestClient

from x_mcp.errors import XError
from x_mcp.models import ProviderPage
from x_mcp.server import TOOLS, create_http_app, create_server


async def test_mcp_tools_annotations_schemas_and_text_compatibility(service_factory):
    service = service_factory(
        fx=FakeProvider("fxtwitter", {None: ProviderPage("fxtwitter", data=make_post())})
    )
    server = create_server(service)
    tools = await server.list_tools()
    assert [t.name for t in tools] == TOOLS
    assert all(t.annotations.read_only_hint and not t.annotations.destructive_hint for t in tools)
    result = await server.call_tool("x_post_get", {"post": "100"})
    assert not result.is_error
    assert json.loads(result.content[0].text) == result.structured_content
    validate(result.structured_content, tools[1].output_schema)
    for name, args in [
        ("x_status", {}),
        ("x_status", {"view": "schema", "tool": "x_post_get"}),
        ("x_status", {"view": "health"}),
    ]:
        output = await server.call_tool(name, args)
        assert not output.is_error
        assert service.store.size(output.structured_content) <= 12288
    invalid = await server.call_tool("x_post_get", {"post": "https://internal.test/123"})
    assert invalid.is_error
    assert invalid.structured_content["error"]["code"] == "INVALID_ARGUMENT"


async def test_service_errors_are_mcp_errors(service_factory):
    service = service_factory(
        fx=FakeProvider(
            "fxtwitter",
            {None: XError("RATE_LIMITED", "Cooling down", retryable=True, retry_after=5)},
        )
    )
    output = await create_server(service).call_tool("x_search", {"query": "test"})
    assert output.is_error
    assert output.structured_content["error"]["retry_after_seconds"] == 5


async def test_http_gateway_requires_bearer_and_leaves_health_minimal(service_factory):
    service = service_factory()
    service.settings.access_token = "synthetic-http-token-" * 3
    gateway = create_http_app(create_server(service), service)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=gateway), base_url="http://localhost"
    ) as client:
        health = await client.get("/healthz")
        assert health.json() == {"status": "ok"}
        response = await client.post("/mcp", json={})
        assert response.status_code == 401
        assert service.settings.access_token not in response.text


def test_non_loopback_server_refuses_missing_token(service_factory):
    service = service_factory()
    service.settings.host = "0.0.0.0"
    with pytest.raises(XError) as error:
        create_http_app(create_server(service), service)
    assert error.value.code == "HTTP_AUTH_REQUIRED"


def test_http_full_initialize_list_call_and_origin_rejection(service_factory):
    service = service_factory()
    service.settings.access_token = "synthetic-http-token-" * 3
    gateway = create_http_app(create_server(service), service)
    headers = {
        "Authorization": f"Bearer {service.settings.access_token}",
        "Accept": "application/json, text/event-stream",
    }
    with TestClient(gateway, base_url="http://localhost") as client:
        assert client.post("/mcp", json={}).status_code == 401
        init = client.post(
            "/mcp",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "1"},
                },
            },
        )
        assert init.status_code == 200
        assert init.json()["result"]["serverInfo"]["name"] == "x-research-mcp"
        listed = client.post(
            "/mcp", headers=headers, json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
        )
        assert len(listed.json()["result"]["tools"]) == 8
        output = client.post(
            "/mcp",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "x_status", "arguments": {"view": "health"}},
            },
        )
        assert not output.json()["result"]["isError"]
        hostile = client.post(
            "/mcp",
            headers={**headers, "Origin": "https://evil.test"},
            json={"jsonrpc": "2.0", "id": 4, "method": "tools/list"},
        )
        assert hostile.status_code == 403
