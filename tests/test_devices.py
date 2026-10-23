"""Unit tests for simulated appliances and diagnostics engine."""

import os
import pytest
from server.devices import DeviceManager
from server.storage import Storage


@pytest.fixture
def storage(tmp_path):
    db_file = str(tmp_path / "test_devices.db")
    st = Storage(db_path=db_file)
    st.reset_database()
    return st


@pytest.fixture
def device_mgr(storage):
    return DeviceManager(storage=storage)


def test_list_appliances(device_mgr):
    apps = device_mgr.list_appliances()
    assert len(apps) == 3
    ids = [a["id"] for a in apps]
    assert "dishwasher_01" in ids
    assert "washer_01" in ids
    assert "vacuum_01" in ids


def test_get_device_state(device_mgr):
    state = device_mgr.get_device_state("dishwasher_01")
    assert state is not None
    assert state["id"] == "dishwasher_01"
    assert state["status"] == "needs_maintenance"
    assert "E24_DRAIN_FILTER_BLOCKED" in state["error_codes"]
    assert state["wear_counters"]["filter_mesh_clog"] == 88


def test_diagnose_dishwasher_odor(device_mgr):
    diag = device_mgr.diagnose_issue("dishwasher_01", "My dishwasher smells and my dishes are cloudy.")
    assert diag["device_id"] == "dishwasher_01"
    assert diag["confidence"] >= 0.85
    assert len(diag["evidence"]) >= 2
    assert len(diag["causes"]) >= 2
    assert "filter" in diag["causes"][0]["cause"].lower()
    assert len(diag["recommended_actions"]) >= 1
    assert diag["recommended_actions"][0]["parameters"]["cycle"] == "cleaning_cycle"


def test_diagnose_vacuum_brush_tangled(device_mgr):
    diag = device_mgr.diagnose_issue("vacuum_01", "The vacuum roller brush seems stuck and making noise.")
    assert diag["device_id"] == "vacuum_01"
    assert diag["confidence"] >= 0.90
    assert "brush" in diag["causes"][0]["cause"].lower()
    assert any("part_vac_brush_01" == a.get("part_id") for a in diag["recommended_actions"])


def test_suggest_settings_muddy_cold_wash(device_mgr):
    res = device_mgr.suggest_settings(
        "washer_01",
        goal="My soccer jersey is really muddy",
        constraints=["cold wash only"],
    )
    assert res["is_schema_valid"] is True
    settings = res["settings"]
    assert settings["water_temp"] == "cold"
    assert settings["soil_level"] in ("heavy", "extra_heavy")
    assert settings["spin_speed"] == "low"
    assert "extra_rinse" in settings.get("options", [])


def test_run_action_dry_run_immutability(device_mgr, storage):
    before = storage.get_appliance("dishwasher_01")
    res = device_mgr.run_action(
        "dishwasher_01",
        action="run_cycle",
        parameters={"cycle": "cleaning_cycle", "water_temp": "high"},
        dry_run=True,
    )
    assert res["success"] is True
    assert res["dry_run"] is True
    after = storage.get_appliance("dishwasher_01")
    assert before["health_score"] == after["health_score"]
    assert before["status"] == after["status"]


def test_run_action_live_execution(device_mgr, storage):
    res = device_mgr.run_action(
        "dishwasher_01",
        action="run_cycle",
        parameters={"cycle": "cleaning_cycle", "water_temp": "high"},
        dry_run=False,
    )
    assert res["success"] is True
    assert res["dry_run"] is False
    after = storage.get_appliance("dishwasher_01")
    assert after["status"] == "running"
    assert after["health_score"] == 96
    assert "E24_DRAIN_FILTER_BLOCKED" not in after["error_codes"]
    assert after["wear_counters"]["filter_mesh_clog"] == 12


def test_advance_wear(device_mgr, storage):
    updated = device_mgr.advance_wear("vacuum_01", "main_roller_brush_wear", 99)
    assert updated["wear_counters"]["main_roller_brush_wear"] == 99
    assert "WARN_BRUSH_TANGLED" in updated["error_codes"]
    assert updated["health_score"] <= 60
