"""Unit tests for safe purchasing flows, expiration, and idempotency guarantees."""

import time
import pytest
from server.audit import AuditLogger
from server.devices import DeviceManager
from server.storage import Storage
from server.tools import HomeCareTools


@pytest.fixture
def storage(tmp_path):
    db_file = str(tmp_path / "test_purchases.db")
    st = Storage(db_path=db_file)
    st.reset_database()
    return st


@pytest.fixture
def audit(tmp_path, storage):
    log_file = str(tmp_path / "test_audit.jsonl")
    return AuditLogger(log_path=log_file, storage=storage)


@pytest.fixture
def tools(storage, audit):
    dev_mgr = DeviceManager(storage=storage)
    return HomeCareTools(storage=storage, device_mgr=dev_mgr, audit=audit)


def test_request_purchase_creates_pending_order(tools, storage):
    res = tools.request_purchase(device_id="dishwasher_01", part_id="part_dw_filter_01", quantity=1)
    details = res["details"]
    assert details["status"] == "PENDING"
    assert "ORD-" in details["order_id"]
    assert details["total_price"] == 24.99
    assert details["expires_in_seconds"] == 120
    assert details["confirmation_token"].startswith("AUTH-")

    # Verify order is persisted in DB as PENDING
    saved = storage.get_order(details["order_id"])
    assert saved is not None
    assert saved["status"] == "PENDING"
    assert saved["confirmed_at"] is None

    # Verify no funds were charged
    confirmed_spend = storage.get_confirmed_spend_since(0)
    assert confirmed_spend == 0.0


def test_confirm_purchase_success(tools, storage):
    req = tools.request_purchase(device_id="vacuum_01", part_id="part_vac_brush_01", quantity=1)
    order_id = req["details"]["order_id"]
    token = req["details"]["confirmation_token"]
    idem_key = f"IDEM-{order_id}"

    # Confirm order
    conf = tools.confirm_purchase(order_id=order_id, confirmation_token=token, idempotency_key=idem_key)
    details = conf["details"]
    assert details["success"] is True
    assert details["duplicate_suppressed"] is False
    assert details["simulated_payment"]["status"] == "APPROVED"

    # Verify in DB
    saved = storage.get_order(order_id)
    assert saved["status"] == "CONFIRMED"
    assert saved["confirmed_at"] is not None
    assert saved["idempotency_key"] == idem_key

    # Confirmed spend is now $19.99
    confirmed_spend = storage.get_confirmed_spend_since(0)
    assert confirmed_spend == 19.99


def test_idempotency_prevents_duplicate_charge(tools, storage):
    req = tools.request_purchase(device_id="vacuum_01", part_id="part_vac_brush_01", quantity=1)
    order_id = req["details"]["order_id"]
    token = req["details"]["confirmation_token"]
    idem_key = f"IDEM-{order_id}"

    # First confirmation
    conf1 = tools.confirm_purchase(order_id=order_id, confirmation_token=token, idempotency_key=idem_key)
    assert conf1["details"]["success"] is True
    assert conf1["details"]["duplicate_suppressed"] is False
    spend_after_first = storage.get_confirmed_spend_since(0)

    # Second confirmation with identical idempotency key
    conf2 = tools.confirm_purchase(order_id=order_id, confirmation_token=token, idempotency_key=idem_key)
    assert conf2["details"]["success"] is True
    assert conf2["details"]["duplicate_suppressed"] is True
    spend_after_second = storage.get_confirmed_spend_since(0)

    # Spending must NOT have increased!
    assert spend_after_first == spend_after_second == 19.99


def test_expired_order_cannot_be_confirmed(tools, storage):
    req = tools.request_purchase(device_id="dishwasher_01", part_id="part_dw_filter_01", quantity=1)
    order_id = req["details"]["order_id"]
    token = req["details"]["confirmation_token"]

    # Fast forward expiration in DB
    with storage._get_connection() as conn:
        conn.cursor().execute("UPDATE orders SET expires_at = ? WHERE order_id = ?", (time.time() - 5, order_id))
        conn.commit()

    # Attempt confirmation
    conf = tools.confirm_purchase(order_id=order_id, confirmation_token=token, idempotency_key=f"IDEM-{order_id}")
    assert conf["details"]["success"] is False
    assert "expired" in conf["spoken_summary"].lower()

    # Confirm order state in DB
    order = storage.get_order(order_id)
    assert order["status"] == "EXPIRED"
    assert storage.get_confirmed_spend_since(0) == 0.0
