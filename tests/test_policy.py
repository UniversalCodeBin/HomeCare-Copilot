"""Unit tests for server-side safety policy rules."""

import time
import pytest
from server.policy import (
    MAX_DAILY_SPEND,
    MAX_PER_ORDER_SPEND,
    validate_device_action,
    validate_purchase_confirmation,
    validate_purchase_request,
)


def test_purchase_request_under_limit():
    part = {"id": "p1", "name": "Filter", "price": 24.99, "in_stock": 1}
    allowed, reason = validate_purchase_request(part, quantity=1, current_daily_spend=0.0)
    assert allowed is True
    assert reason is None


def test_purchase_request_exceeds_per_order_limit():
    part = {"id": "p2", "name": "Heavy Motor", "price": 89.00, "in_stock": 1}
    allowed, reason = validate_purchase_request(part, quantity=1, current_daily_spend=0.0)
    assert allowed is False
    assert "maximum per-order limit of $75.00" in reason


def test_purchase_request_exceeds_daily_limit():
    part = {"id": "p3", "name": "Filter", "price": 40.00, "in_stock": 1}
    # Current daily spend is already $120.00. 120 + 40 = 160 > 150.
    allowed, reason = validate_purchase_request(part, quantity=1, current_daily_spend=120.00)
    assert allowed is False
    assert "daily limit of $150.00" in reason


def test_purchase_request_zero_or_negative_quantity():
    part = {"id": "p1", "price": 20.00, "in_stock": 1}
    allowed, reason = validate_purchase_request(part, quantity=0, current_daily_spend=0.0)
    assert allowed is False
    assert "Quantity must be at least 1" in reason


def test_validate_device_action_valid():
    device = {
        "type": "dishwasher",
        "capabilities": {
            "cycles": ["normal", "cleaning_cycle"],
            "water_temp": ["eco", "high"],
            "dry_mode": ["heat_dry"],
            "options": ["extra_rinse"],
        },
    }
    valid, err, sanitized = validate_device_action(
        device,
        action="run_cycle",
        parameters={"cycle": "cleaning_cycle", "water_temp": "high"},
    )
    assert valid is True
    assert err is None
    assert sanitized["cycle"] == "cleaning_cycle"


def test_validate_device_action_unknown_action():
    device = {"type": "dishwasher", "capabilities": {"cycles": ["normal"]}}
    valid, err, _ = validate_device_action(device, action="self_destruct")
    assert valid is False
    assert "Unsupported action" in err


def test_validate_device_action_unknown_parameter():
    device = {
        "type": "dishwasher",
        "capabilities": {"cycles": ["normal"], "water_temp": ["high"]},
    }
    valid, err, _ = validate_device_action(
        device, action="run_cycle", parameters={"cycle": "normal", "turbo_burn": True}
    )
    assert valid is False
    assert "Unsupported parameter 'turbo_burn'" in err


def test_validate_device_action_unsupported_value():
    device = {
        "type": "dishwasher",
        "capabilities": {"cycles": ["normal"], "water_temp": ["eco", "high"]},
    }
    valid, err, _ = validate_device_action(
        device, action="run_cycle", parameters={"cycle": "normal", "water_temp": "lava_hot"}
    )
    assert valid is False
    assert "Unsupported water_temp 'lava_hot'" in err


def test_confirmation_expired_order():
    order = {
        "order_id": "ORD-1",
        "status": "PENDING",
        "expires_at": time.time() - 10,  # Expired
        "confirmation_token": "TOKEN-1",
    }
    valid, err, _ = validate_purchase_confirmation(
        order, confirmation_token="TOKEN-1", idempotency_key="IDEM-1"
    )
    assert valid is False
    assert "expired" in err.lower()


def test_confirmation_token_mismatch():
    order = {
        "order_id": "ORD-1",
        "status": "PENDING",
        "expires_at": time.time() + 100,
        "confirmation_token": "CORRECT-TOKEN",
    }
    valid, err, _ = validate_purchase_confirmation(
        order, confirmation_token="WRONG-TOKEN", idempotency_key="IDEM-1"
    )
    assert valid is False
    assert "Invalid confirmation token" in err


def test_confirmation_idempotent_duplicate_suppression():
    order = {
        "order_id": "ORD-1",
        "status": "CONFIRMED",
        "idempotency_key": "IDEM-1",
        "confirmation_token": "TOKEN-1",
    }
    valid, err, duplicate_suppressed = validate_purchase_confirmation(
        order, confirmation_token="TOKEN-1", idempotency_key="IDEM-1"
    )
    assert valid is True
    assert duplicate_suppressed is True
    assert err is None


def test_confirmation_different_idempotency_key_refusal():
    order = {
        "order_id": "ORD-1",
        "status": "CONFIRMED",
        "idempotency_key": "IDEM-ORIGINAL",
        "confirmation_token": "TOKEN-1",
    }
    valid, err, _ = validate_purchase_confirmation(
        order, confirmation_token="TOKEN-1", idempotency_key="IDEM-NEW-ATTEMPT"
    )
    assert valid is False
    assert "already confirmed under a different idempotency key" in err
