"""Append-only audit logger for HomeCare Copilot.

Writes immutable JSONL audit records to disk and persists them in SQLite.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

DEFAULT_AUDIT_LOG_PATH = os.environ.get(
    "HOMECARE_AUDIT_LOG_PATH",
    str(Path(__file__).resolve().parent.parent / "logs" / "audit.jsonl"),
)


class AuditLogger:
    """Append-only JSONL audit logger."""

    def __init__(self, log_path: str = DEFAULT_AUDIT_LOG_PATH, storage: Any = None) -> None:
        self.log_path = log_path
        self.storage = storage
        if log_path:
            os.makedirs(os.path.dirname(os.path.abspath(log_path)), exist_ok=True)

    def record(
        self,
        operation: str,
        details: dict[str, Any],
        status: str = "SUCCESS",
        device_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Record an immutable event into the append-only JSONL log and database."""
        event = {
            "timestamp": time.time(),
            "iso_time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "operation": operation,
            "device_id": device_id,
            "status": status,
            "idempotency_key": idempotency_key,
            "details": details,
        }

        # Append to JSONL file
        if self.log_path:
            try:
                with open(self.log_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(event) + "\n")
            except Exception as e:
                print(f"[AuditLogger] Warning: Could not write to JSONL: {e}")

        # Also store in SQLite for structured query/dashboard
        if self.storage:
            try:
                self.storage.log_audit(
                    operation=operation,
                    details=details,
                    status=status,
                    device_id=device_id,
                    idempotency_key=idempotency_key,
                )
            except Exception as e:
                print(f"[AuditLogger] Warning: Could not write to SQLite: {e}")

        return event

    def read_recent_records(self, limit: int = 50) -> list[dict[str, Any]]:
        """Read latest records from the JSONL file."""
        if not self.log_path or not os.path.exists(self.log_path):
            return []
        records = []
        try:
            with open(self.log_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            records.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue
            return records[-limit:]
        except Exception:
            return []
