"""Live end-to-end integration tests over MCP Streamable HTTP transport."""

import threading
import time
import pytest
import uvicorn
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from server.main import app as mcp_app
from server.storage import Storage

INTEGRATION_PORT = 8225
INTEGRATION_URL = f"http://127.0.0.1:{INTEGRATION_PORT}/mcp"


@pytest.fixture(scope="module")
def running_server():
    """Start MCP Streamable HTTP server in background thread during integration tests."""
    storage = Storage()
    storage.reset_database()

    config = uvicorn.Config(mcp_app, host="127.0.0.1", port=INTEGRATION_PORT, log_level="warning")
    server = uvicorn.Server(config)
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    time.sleep(0.7)

    yield INTEGRATION_URL

    server.should_exit = True
    t.join(timeout=2.0)


@pytest.mark.asyncio
async def test_mcp_tool_discovery(running_server):
    """Verify official MCP client discovers all 8 tools over Streamable HTTP."""
    async with streamable_http_client(running_server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            res = await session.list_tools()
            tool_names = [t.name for t in res.tools]
            assert len(tool_names) == 8
            expected_tools = [
                "list_appliances",
                "get_device_state",
                "diagnose_issue",
                "suggest_settings",
                "run_action",
                "find_part",
                "request_purchase",
                "confirm_purchase",
            ]
            for exp in expected_tools:
                assert exp in tool_names


@pytest.mark.asyncio
async def test_mcp_call_list_appliances(running_server):
    """Test list_appliances tool invocation over Streamable HTTP."""
    async with streamable_http_client(running_server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            res = await session.call_tool("list_appliances", {})
            assert len(res.content) > 0
            text = res.content[0].text
            assert "spoken_summary" in text
            assert "details" in text
            assert "dishwasher_01" in text


@pytest.mark.asyncio
async def test_mcp_call_diagnose_issue(running_server):
    """Test diagnose_issue tool invocation over Streamable HTTP."""
    async with streamable_http_client(running_server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            res = await session.call_tool(
                "diagnose_issue",
                {"device_id": "dishwasher_01", "symptom": "Dishwasher smells like sulfur and dishes are cloudy"},
            )
            text = res.content[0].text
            assert "filter" in text.lower()
            assert "confidence" in text.lower()


@pytest.mark.asyncio
async def test_mcp_call_run_action_dry_run(running_server):
    """Test run_action dry run over Streamable HTTP."""
    async with streamable_http_client(running_server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            res = await session.call_tool(
                "run_action",
                {
                    "device_id": "dishwasher_01",
                    "action": "run_cycle",
                    "parameters": {"cycle": "cleaning_cycle", "water_temp": "high"},
                    "dry_run": True,
                },
            )
            text = res.content[0].text
            assert "dry_run" in text.lower()
            assert "true" in text.lower()
