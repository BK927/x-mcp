import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def test_real_stdio_subprocess_handshake_and_eight_tools(tmp_path):
    env = {
        **os.environ,
        "X_MCP_STATE_DIR": str(tmp_path / "state"),
        "X_MCP_SESSION_FILE": str(tmp_path / "absent.json"),
    }
    parameters = StdioServerParameters(
        command=sys.executable, args=["-m", "x_mcp", "serve"], env=env
    )
    async with stdio_client(parameters) as streams, ClientSession(*streams) as client:
        initialized = await client.initialize()
        assert initialized.server_info.name == "x-research-mcp"
        tools = await client.list_tools()
        assert len(tools.tools) == 8
        output = await client.call_tool("x_status", {"view": "health"})
        assert not output.is_error
        assert output.structured_content["data"]["session"] == "not_configured"
