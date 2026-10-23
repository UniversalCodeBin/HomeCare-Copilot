"""MCP Tool implementations for HomeCare Copilot.

All tools return structured dictionaries containing `spoken_summary` and `details`.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from server.audit import AuditLogger
from server.devices import DeviceManager
from server.policy import (
    MAX_DAILY_SPEND,
    MAX_PER_ORDER_SPEND,
    PENDING_ORDER_TIMEOUT_SECONDS,
    validate_purchase_confirmation,
    validate_purchase_request,
)
from server.storage import Storage


class HomeCareTools:
    """Implements the 8 core MCP tools with structured outputs and safety logging."""

    def __init__(self, storage: Storage, device_mgr: DeviceManager, audit: AuditLogger) -> None:
        self.storage = storage
        self.device_mgr = device_mgr
        self.audit = audit

    # Tool 1: list_appliances
    def list_appliances(self) -> dict[str, Any]:
        """Return available appliances, IDs, types, status, and health scores."""
        apps = self.device_mgr.list_appliances()
        needs_attention = [a for a in apps if a["needs_service"]]

        if needs_attention:
            spoken = (
                f"You have {len(apps)} connected appliances. {len(needs_attention)} requires attention: "
                f"{', '.join(a['name'] for a in needs_attention)}."
            )
        else:
            spoken = f"All {len(apps)} connected appliances are operating normally."

        return {
            "spoken_summary": spoken,
            "details": {
                "appliances": apps,
                "total_count": len(apps),
                "timestamp": time.time(),
            },
        }

    # Tool 2: get_device_state
    def get_device_state(self, device_id: str) -> dict[str, Any]:
        """Return the selected appliance's state, capabilities, wear counters, and error codes."""
        if not device_id:
            return {
                "spoken_summary": "Please provide a valid appliance identifier.",
                "details": {"error": "Missing device_id parameter."},
            }

        state = self.device_mgr.get_device_state(device_id)
        if not state:
            return {
                "spoken_summary": f"I couldn't find an appliance with ID {device_id}.",
                "details": {"error": f"Appliance '{device_id}' does not exist."},
            }

        health = state.get("health_score", 100)
        status = state.get("status", "unknown")
        errors = state.get("error_codes", [])
        wear = state.get("wear_counters", {})

        spoken = (
            f"{state.get('name')} is currently {status} with a health score of {health} percent. "
        )
        if errors:
            spoken += f"Active alerts: {', '.join(errors)}. "
        if health < 70:
            spoken += "Maintenance is recommended."

        return {
            "spoken_summary": spoken.strip(),
            "details": state,
        }

    # Tool 3: diagnose_issue
    def diagnose_issue(self, device_id: str, symptom: str) -> dict[str, Any]:
        """Accept a device ID and symptom description. Return ranked possible causes, confidence, supporting evidence, and recommended next actions."""
        if not device_id:
            return {
                "spoken_summary": "I need to know which appliance you'd like me to diagnose.",
                "details": {"error": "Missing device_id parameter."},
            }
        if not symptom:
            return {
                "spoken_summary": "Please describe the symptom or problem you are noticing.",
                "details": {"error": "Missing symptom parameter."},
            }

        diag = self.device_mgr.diagnose_issue(device_id, symptom)
        if "error" in diag:
            return {
                "spoken_summary": diag["error"],
                "details": diag,
            }

        causes = diag.get("causes", [])
        evidence = diag.get("evidence", [])
        actions = diag.get("recommended_actions", [])

        if causes:
            top_cause = causes[0]
            conf_pct = int(top_cause.get("confidence", 0.8) * 100)
            spoken = (
                f"Based on the device telemetry and your description, the most likely cause is "
                f"{top_cause.get('cause')}, with {conf_pct} percent confidence. "
            )
            if actions:
                spoken += f"I recommend: {actions[0].get('description')}"
        else:
            spoken = "No specific failure was diagnosed from current telemetry."

        return {
            "spoken_summary": spoken.strip(),
            "details": diag,
        }

    # Tool 4: suggest_settings
    def suggest_settings(
        self,
        device_id: str,
        goal: str,
        constraints: list[str] | None = None,
    ) -> dict[str, Any]:
        """Map a natural-language goal to supported appliance settings validated against capability schema."""
        if not device_id:
            return {
                "spoken_summary": "Which appliance should I configure settings for?",
                "details": {"error": "Missing device_id parameter."},
            }

        res = self.device_mgr.suggest_settings(device_id, goal, constraints)
        if "error" in res:
            return {
                "spoken_summary": res["error"],
                "details": res,
            }

        settings = res.get("settings", {})
        settings_str = ", ".join(f"{k} set to {v}" for k, v in settings.items())
        spoken = (
            f"For {res.get('device_name')}, I suggest: {settings_str}. "
            f"All settings have been verified against the device's supported capabilities."
        )

        return {
            "spoken_summary": spoken,
            "details": res,
        }

    # Tool 5: run_action
    def run_action(
        self,
        device_id: str,
        action: str,
        parameters: dict[str, Any] | None = None,
        dry_run: bool = True,
    ) -> dict[str, Any]:
        """Validate requested action and parameters. Default dry_run=True. Execute state changes only when explicitly authorized."""
        if not device_id or not action:
            return {
                "spoken_summary": "Device ID and action name are required.",
                "details": {"error": "Missing required device_id or action parameters."},
            }

        res = self.device_mgr.run_action(
            device_id=device_id,
            action=action,
            parameters=parameters,
            dry_run=dry_run,
        )

        if not res.get("success"):
            err_msg = res.get("error", "Unknown validation error.")
            self.audit.record(
                operation="run_action_refusal",
                device_id=device_id,
                status="REFUSED",
                details={"action": action, "parameters": parameters, "error": err_msg},
            )
            return {
                "spoken_summary": f"Action refused: {err_msg}",
                "details": res,
            }

        if dry_run:
            spoken = (
                f"Dry run preview for {action} on {device_id}: "
                + " ".join(res.get("effects_summary", []))
                + " No changes were applied. User confirmation required to proceed."
            )
            self.audit.record(
                operation="run_action_dry_run",
                device_id=device_id,
                status="SUCCESS",
                details={"action": action, "parameters": parameters, "dry_run": True},
            )
        else:
            spoken = f"Successfully executed {action} on {device_id}. " + " ".join(
                res.get("effects_summary", [])
            )
            self.audit.record(
                operation="run_action_executed",
                device_id=device_id,
                status="SUCCESS",
                details={"action": action, "parameters": parameters, "dry_run": False},
            )

        return {
            "spoken_summary": spoken.strip(),
            "details": res,
        }

    # Tool 6: find_part
    def find_part(self, device_id: str, part_name_or_query: str) -> dict[str, Any]:
        """Return compatible replacement parts with simulated prices, availability, and delivery."""
        if not device_id:
            return {
                "spoken_summary": "Please specify which appliance you need parts for.",
                "details": {"error": "Missing device_id parameter."},
            }

        parts = self.storage.search_parts(device_id=device_id, query=part_name_or_query or "")
        device = self.storage.get_appliance(device_id)

        if not parts:
            spoken = f"I could not find any compatible replacement parts matching '{part_name_or_query}' for {device_id}."
        else:
            first = parts[0]
            spoken = (
                f"I found {len(parts)} compatible part{'s' if len(parts) > 1 else ''}. "
                f"The recommended match is {first.get('name')} for ${first.get('price'):.2f} "
                f"with delivery {first.get('estimated_delivery')}."
            )

        return {
            "spoken_summary": spoken,
            "details": {
                "device_id": device_id,
                "device_name": device.get("name") if device else None,
                "query": part_name_or_query,
                "parts": parts,
                "count": len(parts),
                "is_simulated": True,
            },
        }

    # Tool 7: request_purchase
    def request_purchase(
        self,
        device_id: str,
        part_id: str,
        quantity: int = 1,
    ) -> dict[str, Any]:
        """Create a pending order without charging or completing a purchase. Return order ID, total, and 120s expiry."""
        if not device_id or not part_id:
            return {
                "spoken_summary": "Device ID and part ID are required to prepare a purchase quote.",
                "details": {"error": "Missing required parameters."},
            }

        part = self.storage.get_part(part_id)
        if not part:
            return {
                "spoken_summary": f"Part '{part_id}' was not found in the verified parts catalog.",
                "details": {"error": f"Part '{part_id}' not found."},
            }

        # Calculate current daily spend (past 24h)
        one_day_ago = time.time() - 86400.0
        current_daily = self.storage.get_confirmed_spend_since(one_day_ago)

        # Policy limit validation
        is_allowed, reason = validate_purchase_request(part, quantity, current_daily)
        if not is_allowed:
            self.audit.record(
                operation="purchase_request_refused",
                device_id=device_id,
                status="REFUSED",
                details={
                    "part_id": part_id,
                    "quantity": quantity,
                    "unit_price": part.get("price"),
                    "current_daily_spend": current_daily,
                    "reason": reason,
                },
            )
            return {
                "spoken_summary": f"Purchase request refused by safety policy: {reason}",
                "details": {
                    "allowed": False,
                    "error": reason,
                    "error_code": "SPENDING_LIMIT_EXCEEDED",
                    "max_per_order": MAX_PER_ORDER_SPEND,
                    "max_daily": MAX_DAILY_SPEND,
                    "current_daily_spend": current_daily,
                },
            }

        # Create pending order
        order_id = f"ORD-{uuid.uuid4().hex[:6].upper()}"
        confirmation_token = f"AUTH-{uuid.uuid4().hex[:6].upper()}"
        now = time.time()
        expires_at = now + PENDING_ORDER_TIMEOUT_SECONDS
        unit_price = float(part.get("price", 0.0))
        total_price = round(unit_price * quantity, 2)

        order = self.storage.create_order(
            order_id=order_id,
            device_id=device_id,
            part_id=part_id,
            quantity=quantity,
            unit_price=unit_price,
            total_price=total_price,
            expires_at=expires_at,
            confirmation_token=confirmation_token,
        )

        self.audit.record(
            operation="purchase_order_created",
            device_id=device_id,
            status="SUCCESS",
            details={
                "order_id": order_id,
                "part_id": part_id,
                "total_price": total_price,
                "expires_at": expires_at,
            },
        )

        spoken = (
            f"I have prepared pending order {order_id} for {quantity} {part.get('name')} "
            f"at a total simulated cost of ${total_price:.2f}. "
            f"This order expires in two minutes and will NOT be charged until you explicitly confirm."
        )

        return {
            "spoken_summary": spoken,
            "details": {
                "order_id": order_id,
                "device_id": device_id,
                "part_id": part_id,
                "part_name": part.get("name"),
                "quantity": quantity,
                "unit_price": unit_price,
                "total_price": total_price,
                "status": "PENDING",
                "confirmation_token": confirmation_token,
                "expires_at": expires_at,
                "expires_in_seconds": int(PENDING_ORDER_TIMEOUT_SECONDS),
                "is_simulated": True,
                "spending_limits": {
                    "per_order_limit": MAX_PER_ORDER_SPEND,
                    "daily_limit": MAX_DAILY_SPEND,
                    "current_daily_spend": current_daily,
                },
            },
        }

    # Tool 8: confirm_purchase
    def confirm_purchase(
        self,
        order_id: str,
        confirmation_token: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Require valid unexpired pending order, confirmation token, and idempotency key to prevent duplicate charges."""
        if not order_id or not confirmation_token or not idempotency_key:
            return {
                "spoken_summary": "Order ID, confirmation token, and idempotency key are all required.",
                "details": {"error": "Missing required confirmation parameters."},
            }

        order = self.storage.get_order(order_id)
        if not order:
            self.audit.record(
                operation="confirm_purchase_failed",
                status="FAILED",
                idempotency_key=idempotency_key,
                details={"order_id": order_id, "error": "Order not found."},
            )
            return {
                "spoken_summary": f"Order {order_id} was not found.",
                "details": {"error": f"Order '{order_id}' not found."},
            }

        is_valid, error_reason, duplicate_suppressed = validate_purchase_confirmation(
            order=order,
            confirmation_token=confirmation_token,
            idempotency_key=idempotency_key,
        )

        if not is_valid:
            self.audit.record(
                operation="confirm_purchase_refusal",
                device_id=order.get("device_id"),
                status="REFUSED",
                idempotency_key=idempotency_key,
                details={"order_id": order_id, "reason": error_reason},
            )
            return {
                "spoken_summary": f"Purchase confirmation refused: {error_reason}",
                "details": {
                    "success": False,
                    "error": error_reason,
                    "order_id": order_id,
                },
            }

        # Check duplicate suppression (same idempotency key confirmed previously)
        if duplicate_suppressed:
            self.audit.record(
                operation="confirm_purchase_idempotent_repeat",
                device_id=order.get("device_id"),
                status="SUCCESS",
                idempotency_key=idempotency_key,
                details={
                    "order_id": order_id,
                    "message": "Duplicate confirmation suppressed; existing order returned without additional charge.",
                },
            )
            spoken = (
                f"Order {order_id} was already confirmed. "
                f"No duplicate charge was applied under idempotency key {idempotency_key}."
            )
            return {
                "spoken_summary": spoken,
                "details": {
                    "success": True,
                    "duplicate_suppressed": True,
                    "order": order,
                    "message": "Order already confirmed. Duplicate charge prevented.",
                },
            }

        # Confirm order in storage
        confirmed = self.storage.confirm_order(order_id, idempotency_key)
        part = self.storage.get_part(order.get("part_id", ""))

        self.audit.record(
            operation="purchase_confirmed",
            device_id=order.get("device_id"),
            status="SUCCESS",
            idempotency_key=idempotency_key,
            details={
                "order_id": order_id,
                "total_price": order.get("total_price"),
                "part_id": order.get("part_id"),
                "idempotency_key": idempotency_key,
            },
        )

        part_name = part.get("name") if part else "replacement part"
        delivery = part.get("estimated_delivery") if part else "standard delivery"
        spoken = (
            f"Your order {order_id} for {part_name} has been successfully confirmed. "
            f"Total simulated charge: ${order.get('total_price'):.2f}. "
            f"Estimated delivery: {delivery}."
        )

        return {
            "spoken_summary": spoken,
            "details": {
                "success": True,
                "duplicate_suppressed": False,
                "order": confirmed,
                "part": part,
                "simulated_payment": {
                    "status": "APPROVED",
                    "method": "SIMULATED VISA (Ending 4242)",
                    "amount": order.get("total_price"),
                },
            },
        }
