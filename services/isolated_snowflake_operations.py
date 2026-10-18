"""Run Snowflake side-effect operations in short-lived child processes.

The Snowflake connector and its native dependencies can retain allocator memory
after a connection is closed.  Keeping these writes outside the dashboard
process lets the operating system reclaim that memory when the child exits.
"""

from __future__ import annotations

import pickle
import socket
import subprocess
import sys
from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]


def _run(operation: str, payload: dict) -> None:
    subprocess.run(
        [sys.executable, "-m", "services.isolated_snowflake_operations", operation],
        cwd=str(BASE_DIR),
        input=pickle.dumps(payload, protocol=pickle.HIGHEST_PROTOCOL),
        check=True,
    )


def sync_audit_history(dataframe) -> None:
    _run("audit", {"dataframe": dataframe})


def sync_sla_breach_impact_history(dataframe) -> None:
    _run("sla", {"dataframe": dataframe})


def sync_priority_snapshot(dataframe, snapshot_at: datetime) -> None:
    _run("priority", {"dataframe": dataframe, "snapshot_at": snapshot_at})


def write_performance_record(table_name: str, now: datetime, record: dict) -> None:
    _run("performance", {"table_name": table_name, "now": now, "record": record})


def write_application_log_batch(table_name: str, rows: list[tuple]) -> None:
    _run("app_log", {"table_name": table_name, "rows": rows})


def get_processed_data(refresh_token=None, escalated_only=False):
    """Run the recurring Salesforce/Snowflake read pipeline outside the parent."""
    completed = subprocess.run(
        [sys.executable, "-m", "services.isolated_snowflake_operations", "processed_data"],
        cwd=str(BASE_DIR),
        input=pickle.dumps(
            {
                "refresh_token": refresh_token,
                "escalated_only": escalated_only,
            },
            protocol=pickle.HIGHEST_PROTOCOL,
        ),
        capture_output=True,
        check=True,
    )
    if completed.stderr:
        sys.__stderr__.buffer.write(completed.stderr)
        sys.__stderr__.flush()
    return pickle.loads(completed.stdout)


def _write_application_log_batch(table_name: str, rows: list[tuple]) -> None:
    from services.snowflake_service import SnowflakeService

    database, schema, _ = table_name.split(".")
    conn = SnowflakeService().connect(database=database, schema=schema)
    cursor = conn.cursor()
    try:
        cursor.executemany(
            f"INSERT INTO {table_name} (LOGGED_AT, STREAM, MESSAGE, HOST_NAME) VALUES (%s, %s, %s, %s)",
            [(*row, socket.gethostname()) for row in rows],
        )
        conn.commit()
    finally:
        cursor.close()
        conn.close()


def _write_performance_record(table_name: str, now: datetime, record: dict) -> None:
    from services.performance_monitor_service import PerformanceMonitorService

    # Reuse the existing SQL/resource lifecycle exactly; only the process
    # boundary changes.
    PerformanceMonitorService(table_name=table_name)._write_record_direct(now, record)


def _run_child(operation: str, payload: dict) -> None:
    if operation == "audit":
        from pages.CasePriorityIndex import sync_audit_history as operation_fn
        operation_fn(payload["dataframe"])
    elif operation == "sla":
        from pages.OngoingSLABreaches import sync_sla_breach_impact_history as operation_fn
        operation_fn(payload["dataframe"])
    elif operation == "priority":
        from services.case_priority_snapshot_service import CasePrioritySnapshotService
        CasePrioritySnapshotService().sync(payload["dataframe"], payload["snapshot_at"])
    elif operation == "performance":
        _write_performance_record(payload["table_name"], payload["now"], payload["record"])
    elif operation == "app_log":
        _write_application_log_batch(payload["table_name"], payload["rows"])
    elif operation == "processed_data":
        from pages.CasePriorityIndex import get_processed_data as operation_fn
        return operation_fn(
            refresh_token=payload.get("refresh_token"),
            escalated_only=payload.get("escalated_only", False),
        )
    else:
        raise ValueError(f"Unknown isolated Snowflake operation: {operation}")


if __name__ == "__main__":
    operation = sys.argv[1]
    payload = pickle.loads(sys.stdin.buffer.read())
    # Application status prints must not corrupt the binary result channel.
    with redirect_stdout(sys.stderr):
        result = _run_child(operation, payload)
    if operation == "processed_data":
        sys.stdout.buffer.write(pickle.dumps(result, protocol=pickle.HIGHEST_PROTOCOL))
