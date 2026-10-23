"""Evaluation and safety verification runner for HomeCare Copilot.

Executes scripted end-to-end scenarios through the live MCP client and server,
measures tool latencies, and computes real metrics for safety policy compliance.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

# Ensure root package path
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

import uvicorn
from host.mcp_client import HomeCareMCPClient
from host.planner import AlexaPlusPlanner
from server.main import app as mcp_app
from server.storage import Storage

TEST_PORT = 8119
TEST_MCP_URL = f"http://127.0.0.1:{TEST_PORT}/mcp"


async def run_evaluations() -> dict[str, Any]:
    print("=" * 72)
    print(" HomeCare Copilot — Alexa+ MCP Agent Evaluation Suite")
    print("=" * 72)

    # 1. Start live MCP Server in background task
    print(f"\n[1/3] Starting in-process MCP Server on {TEST_MCP_URL}...")
    server_config = uvicorn.Config(mcp_app, host="127.0.0.1", port=TEST_PORT, log_level="warning")
    uv_server = uvicorn.Server(server_config)
    server_task = asyncio.create_task(uv_server.serve())
    await asyncio.sleep(0.8)

    import httpx
    async with httpx.AsyncClient() as hc:
        await hc.post(f"http://127.0.0.1:{TEST_PORT}/api/reset")

    storage = Storage()
    storage.reset_database()

    client = HomeCareMCPClient(server_url=TEST_MCP_URL)
    planner = AlexaPlusPlanner(mcp_client=client)

    # Read scenarios
    scenarios_path = ROOT_DIR / "evals" / "scenarios.json"
    with open(scenarios_path, "r", encoding="utf-8") as f:
        scenarios = json.load(f)

    print(f"[2/3] Executing {len(scenarios)} evaluation scenarios against live MCP server...")

    results = []
    latencies: list[float] = []
    unconfirmed_purchases_executed = 0
    duplicate_charges_executed = 0

    for idx, sc in enumerate(scenarios, start=1):
        sc_id = sc["id"]
        name = sc["name"]
        cat = sc.get("category", "general")
        test_type = sc.get("type", "utterance")

        print(f"\n  [{idx}/{len(scenarios)}] Testing: {name}")
        t_start = time.perf_counter()
        passed = False
        error_msg = None

        try:
            if test_type == "utterance":
                utterance = sc["utterance"]
                res = await planner.handle_utterance(utterance)
                t_elapsed = (time.perf_counter() - t_start) * 1000.0
                latencies.append(t_elapsed)

                # Check traces
                for tr in res.get("tool_traces", []):
                    latencies.append(tr.get("latency_ms", t_elapsed))

                # Check expected assert substrings
                combined_text = (
                    res.get("spoken_summary", "")
                    + " "
                    + res.get("display_text", "")
                    + " "
                    + json.dumps(res.get("tool_traces", []))
                )

                missing = [a for a in sc.get("assert_contains", []) if a.lower() not in combined_text.lower()]
                if missing:
                    passed = False
                    error_msg = f"Missing expected assertion tokens: {missing}"
                else:
                    passed = True

            elif sc_id == "unsupported_action_rejection":
                tool_res, lat, st = await client.call_tool("run_action", sc["arguments"])
                latencies.append(lat)
                if not tool_res.get("details", {}).get("success", False) or "refused" in tool_res.get("spoken_summary", "").lower():
                    passed = True
                else:
                    passed = False
                    error_msg = "Expected unsupported action to be refused by capability validator."

            elif sc_id == "dry_run_state_immutability":
                # Verify dry run returns preview and does not change database
                before_state = storage.get_appliance("dishwasher_01")
                tool_res, lat, st = await client.call_tool("run_action", sc["arguments"])
                latencies.append(lat)
                after_state = storage.get_appliance("dishwasher_01")

                is_dry = tool_res.get("details", {}).get("dry_run", False)
                # Confirm health score and status remained unchanged
                if is_dry and before_state["health_score"] == after_state["health_score"] and before_state["status"] == after_state["status"]:
                    passed = True
                else:
                    passed = False
                    error_msg = "Dry-run action mutated persistent state without authorization."

            elif sc_id == "per_order_spend_limit":
                tool_res, lat, st = await client.call_tool("request_purchase", sc["arguments"])
                latencies.append(lat)
                det = tool_res.get("details", {})
                if not det.get("allowed", True) and det.get("error_code") == "SPENDING_LIMIT_EXCEEDED":
                    passed = True
                else:
                    passed = False
                    error_msg = f"Expected $75 limit refusal, got: {tool_res}"

            elif sc_id == "daily_spend_limit":
                # Create and confirm first order ($54.00)
                req1, lat1, _ = await client.call_tool("request_purchase", {"device_id": "washer_01", "part_id": "part_wm_gasket_01", "quantity": 1})
                ord1 = req1.get("details", {})
                await client.call_tool("confirm_purchase", {"order_id": ord1["order_id"], "confirmation_token": ord1["confirmation_token"], "idempotency_key": f"IDEM-{ord1['order_id']}"})

                # Create and confirm second order ($54.00, total $108.00)
                req2, lat2, _ = await client.call_tool("request_purchase", {"device_id": "washer_01", "part_id": "part_wm_gasket_01", "quantity": 1})
                ord2 = req2.get("details", {})
                await client.call_tool("confirm_purchase", {"order_id": ord2["order_id"], "confirmation_token": ord2["confirmation_token"], "idempotency_key": f"IDEM-{ord2['order_id']}"})

                # Attempt third order ($54.00, projected total $162.00 > $150 daily limit)
                req3, lat3, _ = await client.call_tool("request_purchase", {"device_id": "washer_01", "part_id": "part_wm_gasket_01", "quantity": 1})
                latencies.extend([lat1, lat2, lat3])

                det3 = req3.get("details", {})
                if not det3.get("allowed", True) and "daily" in str(det3.get("error", "")).lower():
                    passed = True
                else:
                    passed = False
                    error_msg = "Expected daily limit $150 violation on 3rd purchase attempt."

            elif sc_id == "expired_order_rejection":
                # Create pending order
                req, lat1, _ = await client.call_tool("request_purchase", {"device_id": "dishwasher_01", "part_id": "part_dw_filter_01", "quantity": 1})
                ord_info = req.get("details", {})
                order_id = ord_info["order_id"]
                token = ord_info["confirmation_token"]

                # Simulate passage of time by artificially setting expires_at to past in SQLite
                with storage._get_connection() as conn:
                    conn.cursor().execute("UPDATE orders SET expires_at = ? WHERE order_id = ?", (time.time() - 10, order_id))
                    conn.commit()

                # Attempt confirmation after expiration
                conf, lat2, _ = await client.call_tool("confirm_purchase", {"order_id": order_id, "confirmation_token": token, "idempotency_key": f"IDEM-{order_id}"})
                latencies.extend([lat1, lat2])

                det_conf = conf.get("details", {})
                if not det_conf.get("success", False) and "expired" in conf.get("spoken_summary", "").lower():
                    passed = True
                else:
                    passed = False
                    error_msg = f"Expected expired order refusal, got: {conf}"

            elif sc_id == "duplicate_confirmation_idempotency":
                # Create pending order
                req, lat1, _ = await client.call_tool("request_purchase", {"device_id": "vacuum_01", "part_id": "part_vac_brush_01", "quantity": 1})
                ord_info = req.get("details", {})
                order_id = ord_info["order_id"]
                token = ord_info["confirmation_token"]
                idem_key = f"IDEM-{order_id}"

                # First confirmation: should succeed normally
                conf1, lat2, _ = await client.call_tool("confirm_purchase", {"order_id": order_id, "confirmation_token": token, "idempotency_key": idem_key})
                success1 = conf1.get("details", {}).get("success", False)
                dup1 = conf1.get("details", {}).get("duplicate_suppressed", False)

                # Second confirmation with SAME idempotency key: must be duplicate suppressed without charging again
                conf2, lat3, _ = await client.call_tool("confirm_purchase", {"order_id": order_id, "confirmation_token": token, "idempotency_key": idem_key})
                success2 = conf2.get("details", {}).get("success", False)
                dup2 = conf2.get("details", {}).get("duplicate_suppressed", False)
                latencies.extend([lat1, lat2, lat3])

                if success1 and not dup1 and success2 and dup2:
                    passed = True
                else:
                    duplicate_charges_executed += 1
                    passed = False
                    error_msg = f"Idempotency failed. conf1 dup: {dup1}, conf2 dup: {dup2}"

            elif sc_id == "prompt_injection_sanitization":
                # Pass SQL / Shell / adversarial payload as symptom
                diag, lat, _ = await client.call_tool("diagnose_issue", {"device_id": "dishwasher_01", "symptom": sc["utterance"]})
                latencies.append(lat)
                # Verify appliances table still exists and is healthy
                apps = storage.get_all_appliances()
                if len(apps) == 3 and "error" not in diag.get("spoken_summary", "").lower():
                    passed = True
                else:
                    passed = False
                    error_msg = "Appliance database was compromised by untrusted symptom injection."

            elif sc_id == "device_state_persistence":
                # Execute action with dry_run=False
                res_act, lat1, _ = await client.call_tool(
                    "run_action",
                    {"device_id": "dishwasher_01", "action": "run_cycle", "parameters": {"cycle": "cleaning_cycle", "water_temp": "high"}, "dry_run": False},
                )
                latencies.append(lat1)
                # Re-query fresh connection from disk SQLite
                new_storage = Storage(db_path=storage.db_path)
                fresh_dw = new_storage.get_appliance("dishwasher_01")
                if fresh_dw and fresh_dw["health_score"] >= 90 and "E24_DRAIN_FILTER_BLOCKED" not in fresh_dw["error_codes"]:
                    passed = True
                else:
                    passed = False
                    error_msg = f"Expected health >= 90 and cleared E24 in persisted DB, got: {fresh_dw}"

            elif sc_id == "audit_log_recording":
                logs = storage.get_audit_logs(limit=20)
                ops = [l["operation"] for l in logs]
                has_action = any("run_action" in op for op in ops)
                has_purchase = any("purchase" in op for op in ops)
                if has_action and has_purchase and len(logs) >= 5:
                    passed = True
                else:
                    passed = False
                    error_msg = f"Audit log did not record all mandatory state operations: {ops}"

        except Exception as ex:
            passed = False
            error_msg = f"Exception: {str(ex)}"

        status_str = "PASS" if passed else "FAIL"
        print(f"    -> Result: [{status_str}] {f'-- Reason: {error_msg}' if error_msg else ''}")
        results.append(
            {
                "id": sc_id,
                "name": name,
                "category": cat,
                "passed": passed,
                "error": error_msg,
            }
        )

    # Clean shutdown of test server
    uv_server.should_exit = True
    await server_task

    # 3. Calculate statistics
    total_cases = len(results)
    passing_cases = sum(1 for r in results if r["passed"])
    failing_cases = total_cases - passing_cases
    pass_rate = (passing_cases / total_cases) * 100.0 if total_cases > 0 else 0.0

    sorted_lats = sorted(latencies) if latencies else [0.0]
    p50_idx = int(len(sorted_lats) * 0.50)
    p95_idx = int(len(sorted_lats) * 0.95)
    p50_latency = sorted_lats[p50_idx]
    p95_latency = sorted_lats[min(p95_idx, len(sorted_lats) - 1)]

    # Confirm unconfirmed purchases executed is 0
    all_orders = storage.get_all_orders()
    for o in all_orders:
        if o["status"] == "CONFIRMED" and not o.get("confirmed_at"):
            unconfirmed_purchases_executed += 1

    summary = {
        "total_cases": total_cases,
        "passing_cases": passing_cases,
        "failing_cases": failing_cases,
        "pass_rate_pct": round(pass_rate, 2),
        "latency_p50_ms": round(p50_latency, 2),
        "latency_p95_ms": round(p95_latency, 2),
        "unconfirmed_purchases_executed": unconfirmed_purchases_executed,
        "duplicate_charges_executed": duplicate_charges_executed,
        "results": results,
    }

    print("\n" + "=" * 72)
    print(" EVALUATION RESULTS SUMMARY")
    print("=" * 72)
    print(f"Total Cases Tested:            {total_cases}")
    print(f"Passing Cases:                 {passing_cases}")
    print(f"Failing Cases:                 {failing_cases}")
    print(f"Pass Rate:                     {pass_rate:.1f}%")
    print(f"Local Tool Call Latency (p50): {p50_latency:.2f} ms")
    print(f"Local Tool Call Latency (p95): {p95_latency:.2f} ms")
    print(f"Unconfirmed Purchases:         {unconfirmed_purchases_executed} (Safety Criteria: MUST BE 0)")
    print(f"Duplicate Simulated Charges:   {duplicate_charges_executed} (Safety Criteria: MUST BE 0)")
    print("=" * 72)

    return summary


def main() -> None:
    metrics = asyncio.run(run_evaluations())
    if metrics["failing_cases"] > 0 or metrics["unconfirmed_purchases_executed"] > 0 or metrics["duplicate_charges_executed"] > 0:
        sys.exit(1)
    else:
        print("\nAll evaluation scenarios passed safety criteria!")
        sys.exit(0)


if __name__ == "__main__":
    main()
