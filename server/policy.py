"""Server-side Safety Policy Engine for HomeCare Copilot.

Enforces spending limits, order expiry, confirmation tokens, idempotency,
and device capability validation.
"""

from __future__ import annotations

import time
from typing import Any

# Mandatory safety limits
MAX_PER_ORDER_SPEND: float = 75.00
MAX_DAILY_SPEND: float = 150.00
PENDING_ORDER_TIMEOUT_SECONDS: float = 120.00


class PolicyViolation(Exception):
    """Raised when an operation violates safety policy."""

    def __init__(self, message: str, code: str = "POLICY_VIOLATION") -> None:
        super().__init__(message)
        self.message = message
        self.code = code


def validate_purchase_request(
    part: dict[str, Any],
    quantity: int,
    current_daily_spend: float,
) -> tuple[bool, str | None]:
    """Validate a requested purchase against safety spending limits."""
    if quantity <= 0:
        return False, "Quantity must be at least 1."

    if not part.get("in_stock", 1):
        return False, f"Part '{part.get('name')}' is currently out of stock."

    unit_price = float(part.get("price", 0.0))
    total_price = round(unit_price * quantity, 2)

    # Per-order limit check
    if total_price > MAX_PER_ORDER_SPEND:
        return (
            False,
            f"Safety limit exceeded: Requested order total of ${total_price:.2f} "
            f"exceeds the maximum per-order limit of ${MAX_PER_ORDER_SPEND:.2f}.",
        )

    # Daily spending limit check
    projected_daily = round(current_daily_spend + total_price, 2)
    if projected_daily > MAX_DAILY_SPEND:
        return (
            False,
            f"Daily spending limit exceeded: Adding ${total_price:.2f} to current daily "
            f"spend of ${current_daily_spend:.2f} would reach ${projected_daily:.2f}, "
            f"exceeding the daily limit of ${MAX_DAILY_SPEND:.2f}.",
        )

    return True, None


def validate_purchase_confirmation(
    order: dict[str, Any],
    confirmation_token: str,
    idempotency_key: str,
) -> tuple[bool, str | None, bool]:
    """Validate confirmation request.

    Returns:
        (is_valid, error_reason, duplicate_suppressed)
    """
    if not idempotency_key or not idempotency_key.strip():
        return False, "Idempotency key is required to confirm purchase.", False

    # Check if already confirmed with the same idempotency key (idempotent repeat)
    if order.get("status") == "CONFIRMED":
        if order.get("idempotency_key") == idempotency_key:
            return True, None, True
        return (
            False,
            f"Order '{order.get('order_id')}' was already confirmed under a different idempotency key.",
            False,
        )

    # Check if already cancelled
    if order.get("status") == "CANCELLED":
        return False, f"Order '{order.get('order_id')}' has been cancelled.", False

    # Check expiration (120 seconds limit)
    now = time.time()
    expires_at = float(order.get("expires_at", 0))
    if order.get("status") == "EXPIRED" or now > expires_at:
        return (
            False,
            f"Pending order '{order.get('order_id')}' expired after {PENDING_ORDER_TIMEOUT_SECONDS:.0f} seconds. "
            f"Please request a fresh order quote.",
            False,
        )

    # Check confirmation token
    expected_token = str(order.get("confirmation_token", "")).strip()
    provided_token = str(confirmation_token).strip()
    if expected_token != provided_token:
        return (
            False,
            "Invalid confirmation token. Confirmation requires explicit authorization from the simulated host.",
            False,
        )

    return True, None, False


def validate_device_action(
    device: dict[str, Any],
    action: str,
    parameters: dict[str, Any] | None = None,
) -> tuple[bool, str | None, dict[str, Any]]:
    """Validate action and parameters strictly against appliance capabilities schema."""
    params = parameters or {}
    caps = device.get("capabilities", {})
    dev_type = device.get("type", "")

    # Clean parameter keys - reject unexpected keys
    sanitized_params: dict[str, Any] = {}

    if dev_type == "dishwasher":
        valid_actions = ["run_cycle", "pause", "resume", "cancel", "reset_filter"]
        if action not in valid_actions:
            return (
                False,
                f"Unsupported action '{action}' for dishwasher. Valid actions: {valid_actions}",
                {},
            )

        if action == "run_cycle":
            allowed_keys = {"cycle", "water_temp", "dry_mode", "options"}
            for k, v in params.items():
                if k not in allowed_keys:
                    return False, f"Unsupported parameter '{k}' for dishwasher cycle.", {}

            cycle = params.get("cycle")
            if cycle is not None:
                valid_cycles = caps.get("cycles", [])
                if cycle not in valid_cycles:
                    return (
                        False,
                        f"Unsupported cycle '{cycle}'. Supported cycles: {valid_cycles}",
                        {},
                    )
                sanitized_params["cycle"] = cycle

            temp = params.get("water_temp")
            if temp is not None:
                valid_temps = caps.get("water_temp", [])
                if temp not in valid_temps:
                    return (
                        False,
                        f"Unsupported water_temp '{temp}'. Supported values: {valid_temps}",
                        {},
                    )
                sanitized_params["water_temp"] = temp

            dry = params.get("dry_mode")
            if dry is not None:
                valid_drys = caps.get("dry_mode", [])
                if dry not in valid_drys:
                    return (
                        False,
                        f"Unsupported dry_mode '{dry}'. Supported values: {valid_drys}",
                        {},
                    )
                sanitized_params["dry_mode"] = dry

            opts = params.get("options")
            if opts is not None:
                if not isinstance(opts, list):
                    return False, "Parameter 'options' must be a list of strings.", {}
                valid_opts = caps.get("options", [])
                for opt in opts:
                    if opt not in valid_opts:
                        return (
                            False,
                            f"Unsupported option '{opt}'. Supported options: {valid_opts}",
                            {},
                        )
                sanitized_params["options"] = opts

    elif dev_type == "washing_machine":
        valid_actions = ["run_cycle", "pause", "resume", "drain_spin", "clean_washer", "cancel"]
        if action not in valid_actions:
            return (
                False,
                f"Unsupported action '{action}' for washing machine. Valid actions: {valid_actions}",
                {},
            )

        if action == "run_cycle":
            allowed_keys = {"cycle", "water_temp", "soil_level", "spin_speed", "options"}
            for k, v in params.items():
                if k not in allowed_keys:
                    return False, f"Unsupported parameter '{k}' for washing machine cycle.", {}

            cycle = params.get("cycle")
            if cycle is not None:
                valid_cycles = caps.get("cycles", [])
                if cycle not in valid_cycles:
                    return (
                        False,
                        f"Unsupported cycle '{cycle}'. Supported cycles: {valid_cycles}",
                        {},
                    )
                sanitized_params["cycle"] = cycle

            temp = params.get("water_temp")
            if temp is not None:
                valid_temps = caps.get("water_temp", [])
                if temp not in valid_temps:
                    return (
                        False,
                        f"Unsupported water_temp '{temp}'. Supported values: {valid_temps}",
                        {},
                    )
                sanitized_params["water_temp"] = temp

            soil = params.get("soil_level")
            if soil is not None:
                valid_soils = caps.get("soil_level", [])
                if soil not in valid_soils:
                    return (
                        False,
                        f"Unsupported soil_level '{soil}'. Supported values: {valid_soils}",
                        {},
                    )
                sanitized_params["soil_level"] = soil

            spin = params.get("spin_speed")
            if spin is not None:
                valid_spins = caps.get("spin_speed", [])
                if spin not in valid_spins:
                    return (
                        False,
                        f"Unsupported spin_speed '{spin}'. Supported values: {valid_spins}",
                        {},
                    )
                sanitized_params["spin_speed"] = spin

            opts = params.get("options")
            if opts is not None:
                if not isinstance(opts, list):
                    return False, "Parameter 'options' must be a list of strings.", {}
                valid_opts = caps.get("options", [])
                for opt in opts:
                    if opt not in valid_opts:
                        return (
                            False,
                            f"Unsupported option '{opt}'. Supported options: {valid_opts}",
                            {},
                        )
                sanitized_params["options"] = opts

    elif dev_type == "robot_vacuum":
        valid_actions = [
            "start_clean",
            "pause",
            "dock",
            "empty_bin",
            "deep_clean_zone",
            "replace_brush",
        ]
        if action not in valid_actions:
            return (
                False,
                f"Unsupported action '{action}' for robot vacuum. Valid actions: {valid_actions}",
                {},
            )

        allowed_keys = {"suction_power", "cleaning_mode"}
        for k, v in params.items():
            if k not in allowed_keys:
                return False, f"Unsupported parameter '{k}' for robot vacuum.", {}

        suction = params.get("suction_power")
        if suction is not None:
            valid_suctions = caps.get("suction_power", [])
            if suction not in valid_suctions:
                return (
                    False,
                    f"Unsupported suction_power '{suction}'. Supported values: {valid_suctions}",
                    {},
                )
            sanitized_params["suction_power"] = suction

        mode = params.get("cleaning_mode")
        if mode is not None:
            valid_modes = caps.get("cleaning_mode", [])
            if mode not in valid_modes:
                return (
                    False,
                    f"Unsupported cleaning_mode '{mode}'. Supported values: {valid_modes}",
                    {},
                )
            sanitized_params["cleaning_mode"] = mode

    else:
        return False, f"Unknown appliance type '{dev_type}'.", {}

    return True, None, sanitized_params
