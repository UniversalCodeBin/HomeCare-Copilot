"""HomeCare Copilot - Official MCP Server over Streamable HTTP.

Exposes 8 homecare appliance diagnosis, settings suggestion, control,
and safe parts purchasing tools over Streamable HTTP at /mcp.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any

from mcp.server.mcpserver import MCPServer
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

# Ensure server package path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from server.audit import AuditLogger
from server.devices import DeviceManager
from server.storage import Storage
from server.tools import HomeCareTools

# Initialize core services
storage = Storage()
audit = AuditLogger(storage=storage)
device_mgr = DeviceManager(storage=storage)
tools = HomeCareTools(storage=storage, device_mgr=device_mgr, audit=audit)

# Initialize MCP Server instance
mcp_server = MCPServer(
    name="HomeCare-MCP-Server",
    version="1.0.0",
    instructions=(
        "HomeCare Copilot MCP Server provides deterministic appliance diagnosis, "
        "capability-verified settings recommendations, safe action execution with dry-run support, "
        "and policy-guarded replacement parts ordering."
    ),
)


# Register Tool 1
@mcp_server.tool()
def list_appliances() -> dict[str, Any]:
    """List all connected appliances with their IDs, names, types, operational statuses, and health scores."""
    return tools.list_appliances()


# Register Tool 2
@mcp_server.tool()
def get_device_state(device_id: str) -> dict[str, Any]:
    """Get the complete operational state, capabilities schema, error codes, and wear counters for a given appliance ID."""
    return tools.get_device_state(device_id)


# Register Tool 3
@mcp_server.tool()
def diagnose_issue(device_id: str, symptom: str) -> dict[str, Any]:
    """Perform deterministic telemetry-based diagnosis for an appliance issue symptom. Returns ranked causes, confidence, supporting evidence, and next actions."""
    return tools.diagnose_issue(device_id, symptom)


# Register Tool 4
@mcp_server.tool()
def suggest_settings(
    device_id: str,
    goal: str,
    constraints: list[str] | None = None,
) -> dict[str, Any]:
    """Map natural language goals (e.g., muddy soccer jersey) and constraints (e.g., cold wash only) to supported appliance settings strictly validated against capability schema."""
    return tools.suggest_settings(device_id, goal, constraints)


# Register Tool 5
@mcp_server.tool()
def run_action(
    device_id: str,
    action: str,
    parameters: dict[str, Any] | None = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Validate and execute an appliance action against capability schema. Defaults to dry_run=True. Set dry_run=False only after explicit user confirmation."""
    return tools.run_action(device_id, action, parameters, dry_run=dry_run)


# Register Tool 6
@mcp_server.tool()
def find_part(device_id: str, part_name_or_query: str) -> dict[str, Any]:
    """Search for authentic compatible replacement parts for a device. Returns simulated pricing, inventory status, and delivery estimates."""
    return tools.find_part(device_id, part_name_or_query)


# Register Tool 7
@mcp_server.tool()
def request_purchase(
    device_id: str,
    part_id: str,
    quantity: int = 1,
) -> dict[str, Any]:
    """Generate a pending purchase quote with a 120-second expiration. Enforces per-order ($75) and daily ($150) simulated spending limits. Never completes a charge."""
    return tools.request_purchase(device_id, part_id, quantity)


# Register Tool 8
@mcp_server.tool()
def confirm_purchase(
    order_id: str,
    confirmation_token: str,
    idempotency_key: str,
) -> dict[str, Any]:
    """Explicitly authorize and confirm a pending unexpired order using an idempotency key to prevent duplicate charges. Enforces safety confirmation policy."""
    return tools.confirm_purchase(order_id, confirmation_token, idempotency_key)


# Create Streamable HTTP Starlette application
streamable_app = mcp_server.streamable_http_app(streamable_http_path="/mcp")


# REST Helper Handlers for Dashboard and Host inspection
async def api_health(request: Request) -> JSONResponse:
    return JSONResponse(
        {
            "status": "healthy",
            "server": "HomeCare-MCP-Server",
            "protocol": "Model Context Protocol (MCP)",
            "transport": "Streamable HTTP (/mcp)",
            "tools_count": 8,
        }
    )


async def api_get_appliances(request: Request) -> JSONResponse:
    return JSONResponse({"appliances": storage.get_all_appliances()})


async def api_get_appliance(request: Request) -> JSONResponse:
    app_id = request.path_params.get("device_id", "")
    dev = storage.get_appliance(app_id)
    if not dev:
        return JSONResponse({"error": "Device not found"}, status_code=404)
    return JSONResponse(dev)


async def api_get_parts(request: Request) -> JSONResponse:
    query = request.query_params.get("q", "")
    dev_id = request.query_params.get("device_id", None)
    return JSONResponse({"parts": storage.search_parts(dev_id, query)})


async def api_get_orders(request: Request) -> JSONResponse:
    return JSONResponse({"orders": storage.get_all_orders()})


async def api_get_audit(request: Request) -> JSONResponse:
    return JSONResponse({"audit_logs": storage.get_audit_logs(limit=100)})


async def api_reset_data(request: Request) -> JSONResponse:
    storage.reset_database()
    audit.record(
        operation="demo_database_reset",
        details={"message": "Demo data reset to initial values."},
        status="SUCCESS",
    )
    return JSONResponse({"success": True, "message": "Demo database reset successfully."})


async def api_advance_wear(request: Request) -> JSONResponse:
    try:
        body = await request.json()
        device_id = body.get("device_id", "vacuum_01")
        wear_key = body.get("wear_key", "main_roller_brush_wear")
        amount = int(body.get("amount", 95))
        updated = device_mgr.advance_wear(device_id, wear_key, amount)
        audit.record(
            operation="simulate_advance_wear",
            device_id=device_id,
            details={"wear_key": wear_key, "amount": amount},
            status="SUCCESS",
        )
        return JSONResponse({"success": True, "appliance": updated})
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=400)


# Add helper REST endpoints to streamable_app
streamable_app.routes.append(Route("/health", api_health, methods=["GET"]))
streamable_app.routes.append(Route("/api/appliances", api_get_appliances, methods=["GET"]))
streamable_app.routes.append(Route("/api/appliances/{device_id}", api_get_appliance, methods=["GET"]))
streamable_app.routes.append(Route("/api/parts", api_get_parts, methods=["GET"]))
streamable_app.routes.append(Route("/api/orders", api_get_orders, methods=["GET"]))
streamable_app.routes.append(Route("/api/audit", api_get_audit, methods=["GET"]))
streamable_app.routes.append(Route("/api/reset", api_reset_data, methods=["POST"]))
streamable_app.routes.append(Route("/api/advance_wear", api_advance_wear, methods=["POST"]))

# Add CORS middleware
streamable_app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app = streamable_app


def main() -> None:
    parser = argparse.ArgumentParser(description="HomeCare Copilot MCP Server")
    parser.add_argument("--host", default="127.0.0.1", help="Host interface (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="Port to listen on (default: 8000)")
    args = parser.parse_args()

    import uvicorn

    print(f"Starting HomeCare MCP Server on http://{args.host}:{args.port}/mcp ...")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
