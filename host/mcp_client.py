"""MCP Client for the Simulated Alexa+ Host.

Connects to the HomeCare MCP Server over Streamable HTTP and executes tools with latency tracking.
"""

from __future__ import annotations

import json
import time
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


class HomeCareMCPClient:
    """Client for connecting to HomeCare MCP server over Streamable HTTP."""

    def __init__(self, server_url: str = "http://127.0.0.1:8000/mcp") -> None:
        self.server_url = server_url

    async def list_tools(self) -> list[dict[str, Any]]:
        """Query available tools from the server via MCP protocol."""
        async with streamable_http_client(self.server_url) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                res = await session.list_tools()
                tools_list = []
                for t in res.tools:
                    tools_list.append(
                        {
                            "name": t.name,
                            "description": t.description,
                            "input_schema": getattr(t, "input_schema", getattr(t, "inputSchema", {})),
                        }
                    )
                return tools_list

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], float, str]:
        """Invoke an MCP tool over Streamable HTTP and measure round-trip latency.

        Returns:
            (parsed_result_dict, latency_ms, status)
        """
        args = arguments or {}
        start_time = time.perf_counter()
        status = "SUCCESS"

        try:
            async with streamable_http_client(self.server_url) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    call_result = await session.call_tool(name, args)

                    # Parse output content from MCP ToolResult
                    text_content = ""
                    for c in call_result.content:
                        if hasattr(c, "text"):
                            text_content += c.text

                    elapsed_ms = (time.perf_counter() - start_time) * 1000.0

                    try:
                        parsed = json.loads(text_content)
                    except json.JSONDecodeError:
                        parsed = {"spoken_summary": text_content, "details": {}}

                    return parsed, round(elapsed_ms, 2), status

        except Exception as e:
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            status = "ERROR"
            return (
                {
                    "spoken_summary": f"Failed to connect to MCP server: {str(e)}",
                    "details": {"error": str(e), "tool": name, "arguments": args},
                },
                round(elapsed_ms, 2),
                status,
            )
