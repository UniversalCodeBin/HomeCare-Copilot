"""Database storage layer for HomeCare Copilot using SQLite.

Maintains appliances, replacement parts catalog, orders, and audit records.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

DEFAULT_DB_PATH = os.environ.get(
    "HOMECARE_DB_PATH",
    str(Path(__file__).resolve().parent.parent / "data" / "homecare.db"),
)

INITIAL_APPLIANCES: list[dict[str, Any]] = [
    {
        "id": "dishwasher_01",
        "name": "AquaClean Pro Dishwasher 3000",
        "type": "dishwasher",
        "status": "needs_maintenance",
        "health_score": 68,
        "capabilities": {
            "cycles": ["normal", "heavy", "express", "sanitize", "cleaning_cycle"],
            "water_temp": ["eco", "normal", "high"],
            "dry_mode": ["air_dry", "heat_dry", "boost"],
            "options": ["delay_start", "extra_rinse"],
        },
        "error_codes": ["E24_DRAIN_FILTER_BLOCKED"],
        "wear_counters": {
            "filter_mesh_clog": 88,
            "spray_arm_scale": 65,
            "water_hardness_mineral_buildup": 72,
        },
        "current_settings": {
            "cycle": "normal",
            "water_temp": "normal",
            "dry_mode": "heat_dry",
        },
    },
    {
        "id": "washer_01",
        "name": "UltraWash Front-Load Washer",
        "type": "washing_machine",
        "status": "idle",
        "health_score": 94,
        "capabilities": {
            "cycles": ["normal", "heavy_duty", "delicates", "quick_wash", "clean_washer"],
            "water_temp": ["tap_cold", "cold", "warm", "hot", "sanitize"],
            "soil_level": ["light", "normal", "heavy", "extra_heavy"],
            "spin_speed": ["no_spin", "low", "medium", "high", "max"],
            "options": ["extra_rinse", "pre_wash", "steam"],
        },
        "error_codes": [],
        "wear_counters": {
            "drum_seal_wear": 22,
            "inlet_valve_cycles": 310,
        },
        "current_settings": {
            "cycle": "normal",
            "water_temp": "warm",
            "soil_level": "normal",
            "spin_speed": "high",
        },
    },
    {
        "id": "vacuum_01",
        "name": "RoboVac Matrix LiDAR",
        "type": "robot_vacuum",
        "status": "docked",
        "health_score": 58,
        "capabilities": {
            "actions": ["start_clean", "pause", "dock", "empty_bin", "deep_clean_zone"],
            "suction_power": ["quiet", "standard", "turbo", "max"],
            "cleaning_mode": ["vacuum", "mop", "vacuum_and_mop"],
        },
        "error_codes": ["WARN_BRUSH_TANGLED"],
        "wear_counters": {
            "main_roller_brush_wear": 96,
            "hepa_filter_wear": 52,
            "side_brush_wear": 78,
        },
        "current_settings": {
            "suction_power": "standard",
            "cleaning_mode": "vacuum",
        },
    },
]

INITIAL_PARTS: list[dict[str, Any]] = [
    {
        "id": "part_dw_filter_01",
        "device_type": "dishwasher",
        "device_id": "dishwasher_01",
        "name": "Dishwasher Micro-Fine Mesh Filter",
        "part_number": "DW-FLT-882",
        "price": 24.99,
        "in_stock": 1,
        "estimated_delivery": "Tomorrow by 2 PM (Simulated Prime)",
        "description": "Original manufacturer replacement 3-stage micro mesh filter assembly.",
    },
    {
        "id": "part_dw_descaler_01",
        "device_type": "dishwasher",
        "device_id": "dishwasher_01",
        "name": "Active Enzyme Descaler Tabs (6-pack)",
        "part_number": "DW-DSC-06",
        "price": 14.50,
        "in_stock": 1,
        "estimated_delivery": "Tomorrow by 2 PM (Simulated Prime)",
        "description": "Removes hard-water mineral buildup and grease from internal pump and spray arms.",
    },
    {
        "id": "part_vac_brush_01",
        "device_type": "robot_vacuum",
        "device_id": "vacuum_01",
        "name": "Anti-Tangle Rubber & Bristle Main Roller Brush",
        "part_number": "VAC-RB-401",
        "price": 19.99,
        "in_stock": 1,
        "estimated_delivery": "Tomorrow by 11 AM (Simulated Prime)",
        "description": "OEM replacement hybrid roller brush with removable end-caps for easy hair clearing.",
    },
    {
        "id": "part_vac_hepa_01",
        "device_type": "robot_vacuum",
        "device_id": "vacuum_01",
        "name": "High-Efficiency E12 HEPA Filter (2-pack)",
        "part_number": "VAC-HP-202",
        "price": 16.50,
        "in_stock": 1,
        "estimated_delivery": "2 days (Simulated Standard)",
        "description": "Captures 99.97% of fine dust, pet dander, and pollen particles down to 0.3 microns.",
    },
    {
        "id": "part_vac_side_01",
        "device_type": "robot_vacuum",
        "device_id": "vacuum_01",
        "name": "Side Sweeper Corner Brushes (4-pack)",
        "part_number": "VAC-SB-104",
        "price": 11.99,
        "in_stock": 1,
        "estimated_delivery": "Tomorrow by 5 PM (Simulated Prime)",
        "description": "Corner reaching 3-arm sweep brushes with silicone flex arms.",
    },
    {
        "id": "part_wm_gasket_01",
        "device_type": "washing_machine",
        "device_id": "washer_01",
        "name": "Antimicrobial Door Bellow Boot Seal Gasket",
        "part_number": "WM-GSK-901",
        "price": 54.00,
        "in_stock": 1,
        "estimated_delivery": "2 days (Simulated Standard)",
        "description": "Molded silicone drum boot seal with dual water drain ports.",
    },
    {
        "id": "part_wm_cleaner_01",
        "device_type": "washing_machine",
        "device_id": "washer_01",
        "name": "Washing Machine Tub Cleaner Tablets (4-pack)",
        "part_number": "WM-CLN-44",
        "price": 12.99,
        "in_stock": 1,
        "estimated_delivery": "Tomorrow by 2 PM (Simulated Prime)",
        "description": "Deep cleaning oxygen tabs to dissolve residue and odors behind the drum.",
    },
    {
        "id": "part_expensive_motor_01",
        "device_type": "washing_machine",
        "device_id": "washer_01",
        "name": "Commercial Heavy-Duty Direct-Drive Inverter Motor",
        "part_number": "WM-MTR-999",
        "price": 289.00,
        "in_stock": 1,
        "estimated_delivery": "3 days (Simulated Freight)",
        "description": "High-torque brushless direct drive motor assembly. (Exceeds $75 order limit).",
    },
]


class Storage:
    """Manages SQLite storage for appliances, parts catalog, orders, and audits."""

    def __init__(self, db_path: str = DEFAULT_DB_PATH) -> None:
        self.db_path = db_path
        if db_path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self.init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self, force_reseed: bool = False) -> None:
        """Create tables if not existing and populate default data."""
        with self._get_connection() as conn:
            cur = conn.cursor()
            if force_reseed:
                cur.execute("DROP TABLE IF EXISTS audit_log")
                cur.execute("DROP TABLE IF EXISTS orders")
                cur.execute("DROP TABLE IF EXISTS parts")
                cur.execute("DROP TABLE IF EXISTS appliances")

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS appliances (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    health_score INTEGER NOT NULL,
                    capabilities TEXT NOT NULL,
                    error_codes TEXT NOT NULL,
                    wear_counters TEXT NOT NULL,
                    current_settings TEXT NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS parts (
                    id TEXT PRIMARY KEY,
                    device_type TEXT NOT NULL,
                    device_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    part_number TEXT NOT NULL,
                    price REAL NOT NULL,
                    in_stock INTEGER NOT NULL,
                    estimated_delivery TEXT NOT NULL,
                    description TEXT NOT NULL
                )
                """
            )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS orders (
                    order_id TEXT PRIMARY KEY,
                    device_id TEXT NOT NULL,
                    part_id TEXT NOT NULL,
                    quantity INTEGER NOT NULL,
                    unit_price REAL NOT NULL,
                    total_price REAL NOT NULL,
                    status TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    expires_at REAL NOT NULL,
                    confirmed_at REAL,
                    idempotency_key TEXT,
                    confirmation_token TEXT NOT NULL
                )
                """
            )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    operation TEXT NOT NULL,
                    device_id TEXT,
                    details TEXT NOT NULL,
                    status TEXT NOT NULL,
                    idempotency_key TEXT
                )
                """
            )
            conn.commit()

            # Seed if appliances empty
            cur.execute("SELECT COUNT(*) FROM appliances")
            if cur.fetchone()[0] == 0:
                now = time.time()
                for app in INITIAL_APPLIANCES:
                    cur.execute(
                        """
                        INSERT INTO appliances
                        (id, name, type, status, health_score, capabilities, error_codes, wear_counters, current_settings, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            app["id"],
                            app["name"],
                            app["type"],
                            app["status"],
                            app["health_score"],
                            json.dumps(app["capabilities"]),
                            json.dumps(app["error_codes"]),
                            json.dumps(app["wear_counters"]),
                            json.dumps(app["current_settings"]),
                            now,
                        ),
                    )

            # Seed if parts empty
            cur.execute("SELECT COUNT(*) FROM parts")
            if cur.fetchone()[0] == 0:
                for p in INITIAL_PARTS:
                    cur.execute(
                        """
                        INSERT INTO parts
                        (id, device_type, device_id, name, part_number, price, in_stock, estimated_delivery, description)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            p["id"],
                            p["device_type"],
                            p["device_id"],
                            p["name"],
                            p["part_number"],
                            p["price"],
                            p["in_stock"],
                            p["estimated_delivery"],
                            p["description"],
                        ),
                    )
            conn.commit()

    def reset_database(self) -> None:
        """Reset database to initial state."""
        self.init_db(force_reseed=True)

    # Appliance operations
    def get_all_appliances(self) -> list[dict[str, Any]]:
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM appliances ORDER BY id ASC")
            rows = cur.fetchall()
            result = []
            for r in rows:
                result.append(
                    {
                        "id": r["id"],
                        "name": r["name"],
                        "type": r["type"],
                        "status": r["status"],
                        "health_score": r["health_score"],
                        "capabilities": json.loads(r["capabilities"]),
                        "error_codes": json.loads(r["error_codes"]),
                        "wear_counters": json.loads(r["wear_counters"]),
                        "current_settings": json.loads(r["current_settings"]),
                        "updated_at": r["updated_at"],
                    }
                )
            return result

    def get_appliance(self, appliance_id: str) -> dict[str, Any] | None:
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM appliances WHERE id = ?", (appliance_id,))
            r = cur.fetchone()
            if not r:
                return None
            return {
                "id": r["id"],
                "name": r["name"],
                "type": r["type"],
                "status": r["status"],
                "health_score": r["health_score"],
                "capabilities": json.loads(r["capabilities"]),
                "error_codes": json.loads(r["error_codes"]),
                "wear_counters": json.loads(r["wear_counters"]),
                "current_settings": json.loads(r["current_settings"]),
                "updated_at": r["updated_at"],
            }

    def update_appliance(
        self,
        appliance_id: str,
        *,
        status: str | None = None,
        health_score: int | None = None,
        error_codes: list[str] | None = None,
        wear_counters: dict[str, Any] | None = None,
        current_settings: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        current = self.get_appliance(appliance_id)
        if not current:
            return None

        new_status = status if status is not None else current["status"]
        new_health = health_score if health_score is not None else current["health_score"]
        new_errors = error_codes if error_codes is not None else current["error_codes"]
        new_wear = wear_counters if wear_counters is not None else current["wear_counters"]
        new_settings = current_settings if current_settings is not None else current["current_settings"]
        now = time.time()

        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE appliances
                SET status = ?, health_score = ?, error_codes = ?, wear_counters = ?, current_settings = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    new_status,
                    new_health,
                    json.dumps(new_errors),
                    json.dumps(new_wear),
                    json.dumps(new_settings),
                    now,
                    appliance_id,
                ),
            )
            conn.commit()

        return self.get_appliance(appliance_id)

    # Parts operations
    def search_parts(self, device_id: str | None = None, query: str = "") -> list[dict[str, Any]]:
        with self._get_connection() as conn:
            cur = conn.cursor()
            sql = "SELECT * FROM parts WHERE 1=1"
            params: list[Any] = []
            if device_id:
                # Also match if device_id matches or part is suitable for device type
                appliance = self.get_appliance(device_id)
                dev_type = appliance["type"] if appliance else None
                if dev_type:
                    sql += " AND (device_id = ? OR device_type = ?)"
                    params.extend([device_id, dev_type])
                else:
                    sql += " AND device_id = ?"
                    params.append(device_id)

            if query:
                q = f"%{query.strip().lower()}%"
                sql += " AND (LOWER(name) LIKE ? OR LOWER(description) LIKE ? OR LOWER(part_number) LIKE ?)"
                params.extend([q, q, q])

            cur.execute(sql, params)
            rows = cur.fetchall()
            return [dict(r) for r in rows]

    def get_part(self, part_id: str) -> dict[str, Any] | None:
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM parts WHERE id = ?", (part_id,))
            r = cur.fetchone()
            return dict(r) if r else None

    # Order operations
    def create_order(
        self,
        order_id: str,
        device_id: str,
        part_id: str,
        quantity: int,
        unit_price: float,
        total_price: float,
        expires_at: float,
        confirmation_token: str,
    ) -> dict[str, Any]:
        now = time.time()
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO orders
                (order_id, device_id, part_id, quantity, unit_price, total_price, status, created_at, expires_at, confirmation_token)
                VALUES (?, ?, ?, ?, ?, ?, 'PENDING', ?, ?, ?)
                """,
                (
                    order_id,
                    device_id,
                    part_id,
                    quantity,
                    unit_price,
                    total_price,
                    now,
                    expires_at,
                    confirmation_token,
                ),
            )
            conn.commit()
        return self.get_order(order_id)  # type: ignore

    def get_order(self, order_id: str) -> dict[str, Any] | None:
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,))
            r = cur.fetchone()
            if not r:
                return None
            res = dict(r)
            # Auto-update status to EXPIRED if now > expires_at and still PENDING
            if res["status"] == "PENDING" and time.time() > res["expires_at"]:
                cur.execute("UPDATE orders SET status = 'EXPIRED' WHERE order_id = ?", (order_id,))
                conn.commit()
                res["status"] = "EXPIRED"
            return res

    def get_order_by_idempotency_key(self, idempotency_key: str) -> dict[str, Any] | None:
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM orders WHERE idempotency_key = ?", (idempotency_key,))
            r = cur.fetchone()
            return dict(r) if r else None

    def confirm_order(self, order_id: str, idempotency_key: str) -> dict[str, Any] | None:
        now = time.time()
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE orders
                SET status = 'CONFIRMED', confirmed_at = ?, idempotency_key = ?
                WHERE order_id = ?
                """,
                (now, idempotency_key, order_id),
            )
            conn.commit()
        return self.get_order(order_id)

    def get_all_orders(self) -> list[dict[str, Any]]:
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM orders ORDER BY created_at DESC")
            rows = cur.fetchall()
            now = time.time()
            res = []
            for r in rows:
                d = dict(r)
                if d["status"] == "PENDING" and now > d["expires_at"]:
                    d["status"] = "EXPIRED"
                res.append(d)
            return res

    def get_confirmed_spend_since(self, since_timestamp: float) -> float:
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT SUM(total_price) FROM orders
                WHERE status = 'CONFIRMED' AND confirmed_at >= ?
                """,
                (since_timestamp,),
            )
            total = cur.fetchone()[0]
            return float(total) if total is not None else 0.0

    # Audit operations
    def log_audit(
        self,
        operation: str,
        details: dict[str, Any],
        status: str,
        device_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> int:
        now = time.time()
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO audit_log
                (timestamp, operation, device_id, details, status, idempotency_key)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    now,
                    operation,
                    device_id,
                    json.dumps(details),
                    status,
                    idempotency_key,
                ),
            )
            conn.commit()
            return cur.lastrowid or 0

    def get_audit_logs(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,))
            rows = cur.fetchall()
            res = []
            for r in rows:
                res.append(
                    {
                        "id": r["id"],
                        "timestamp": r["timestamp"],
                        "operation": r["operation"],
                        "device_id": r["device_id"],
                        "details": json.loads(r["details"]),
                        "status": r["status"],
                        "idempotency_key": r["idempotency_key"],
                    }
                )
            return res
