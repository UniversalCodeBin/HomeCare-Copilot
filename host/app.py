"""FastAPI backend for the Simulated Alexa+ Host.

Serves the chat interface, communicates with the HomeCare MCP server over Streamable HTTP,
and proxies telemetry and audit logs to the frontend dashboard.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# Ensure root package path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from host.mcp_client import HomeCareMCPClient
from host.planner import AlexaPlusPlanner
from server.storage import Storage

# Initialize Storage for dashboard fallback queries
storage = Storage()

# MCP Server URL (configurable via env var)
MCP_SERVER_URL = os.environ.get("HOMECARE_MCP_URL", "http://127.0.0.1:8000/mcp")

mcp_client = HomeCareMCPClient(server_url=MCP_SERVER_URL)
planner = AlexaPlusPlanner(mcp_client=mcp_client)

app = FastAPI(
    title="HomeCare Copilot - Simulated Alexa+ Host",
    description="Simulated Alexa+ Assistant Host communicating with HomeCare MCP Server over Streamable HTTP.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    message: str


class ConfirmRequest(BaseModel):
    order_id: str
    confirmation_token: str
    idempotency_key: str | None = None


class AdvanceWearRequest(BaseModel):
    device_id: str = "vacuum_01"
    wear_key: str = "main_roller_brush_wear"
    amount: int = 96


@app.get("/api/health")
async def api_health() -> dict[str, Any]:
    return {
        "status": "healthy",
        "service": "Simulated Alexa+ Host",
        "mcp_server_url": MCP_SERVER_URL,
        "mode": "Simulation (Not affiliated with Amazon Alexa)",
    }


@app.post("/api/chat")
async def chat_endpoint(req: ChatRequest) -> dict[str, Any]:
    """Handle conversational turn through the planner and real MCP client."""
    if not req.message or not req.message.strip():
        raise HTTPException(status_code=400, detail="Empty message.")
    result = await planner.handle_utterance(req.message.strip())
    return result


@app.get("/api/tools")
async def get_mcp_tools() -> dict[str, Any]:
    """Discover available tools from the real MCP server over Streamable HTTP."""
    try:
        tools = await mcp_client.list_tools()
        return {"tools": tools, "count": len(tools)}
    except Exception as e:
        return {"error": str(e), "tools": [], "count": 0}


@app.get("/api/appliances")
async def get_appliances() -> dict[str, Any]:
    """Get all appliance telemetry from SQLite storage."""
    apps = storage.get_all_appliances()
    return {"appliances": apps}


@app.get("/api/orders")
async def get_orders() -> dict[str, Any]:
    """Get all pending and completed orders."""
    orders = storage.get_all_orders()
    return {"orders": orders}


@app.get("/api/audit")
async def get_audit_logs() -> dict[str, Any]:
    """Get append-only audit trail."""
    logs = storage.get_audit_logs(limit=100)
    return {"audit_logs": logs}


@app.post("/api/confirm_order")
async def confirm_order_endpoint(req: ConfirmRequest) -> dict[str, Any]:
    """Direct confirmation endpoint for UI buttons."""
    idempotency_key = req.idempotency_key or f"IDEM-{req.order_id}"
    res, latency, status = await mcp_client.call_tool(
        "confirm_purchase",
        {
            "order_id": req.order_id,
            "confirmation_token": req.confirmation_token,
            "idempotency_key": idempotency_key,
        },
    )
    return {"result": res, "latency_ms": latency, "status": status}


@app.post("/api/advance_wear")
async def advance_wear_endpoint(req: AdvanceWearRequest) -> dict[str, Any]:
    """Advance wear counter on an appliance for testing Scenario D."""
    from server.devices import DeviceManager

    mgr = DeviceManager(storage=storage)
    updated = mgr.advance_wear(req.device_id, req.wear_key, req.amount)
    from server.audit import AuditLogger

    aud = AuditLogger(storage=storage)
    aud.record(
        operation="simulate_advance_wear",
        device_id=req.device_id,
        details={"wear_key": req.wear_key, "amount": req.amount},
        status="SUCCESS",
    )
    return {"success": True, "appliance": updated}


@app.post("/api/reset")
async def reset_database_endpoint() -> dict[str, Any]:
    """Reset database to initial clean demo state."""
    storage.reset_database()
    from server.audit import AuditLogger

    aud = AuditLogger(storage=storage)
    aud.record(
        operation="demo_database_reset",
        details={"message": "Demo state reset via host."},
        status="SUCCESS",
    )
    return {"success": True, "message": "Database successfully reset to initial demo state."}


# Mount Static Files
static_dir = Path(__file__).resolve().parent / "static"
if static_dir.exists():
    app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")


def main() -> None:
    parser = argparse.ArgumentParser(description="HomeCare Copilot Simulated Alexa+ Host")
    parser.add_argument("--host", default="127.0.0.1", help="Host interface (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8080, help="Port to listen on (default: 8080)")
    parser.add_argument(
        "--mcp-url",
        default="http://127.0.0.1:8000/mcp",
        help="HomeCare MCP server URL (default: http://127.0.0.1:8000/mcp)",
    )
    args = parser.parse_args()

    os.environ["HOMECARE_MCP_URL"] = args.mcp_url

    import uvicorn

    print(f"Starting Simulated Alexa+ Host on http://{args.host}:{args.port} ...")
    print(f"Connecting to MCP Server at: {args.mcp_url}")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
