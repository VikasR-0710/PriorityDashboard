"""Periodic host/process performance snapshots stored in Snowflake."""

from __future__ import annotations

import logging
import os
import re
import socket
import threading
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import psutil

logger = logging.getLogger(__name__)

DEFAULT_TABLE = "CUSTOMER_SUPPORT_BOT_LOGS.CHAT_DATA.DBD_GCS_SERVER_PERFORMANCE"
SERVICE_NAME = "GCS_PRIORITISATION_INDEX"
_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")


class PerformanceMonitorService:
    def __init__(self, table_name: str = DEFAULT_TABLE, interval_seconds: int = 900, disk_path: Path | None = None):
        parts = table_name.split(".")
        if len(parts) != 3 or not all(_IDENTIFIER_PATTERN.fullmatch(part) for part in parts):
            raise ValueError("Performance table must be a database.schema.table identifier")
        if not parts[-1].upper().startswith("DBD"):
            raise ValueError("Performance table name must start with DBD")
        self.table_name = ".".join(parts)
        self.disk_path = Path(disk_path or Path.cwd())
        self.interval_seconds = interval_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._write_lock = threading.Lock()
        self._previous_network = None

    def start(self, run_immediately: bool = True) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._run, args=(run_immediately,), daemon=True,
            name="snowflake-performance-monitor",
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)

    def _run(self, run_immediately: bool) -> None:
        if run_immediately:
            self._record_safely()
        while not self._stop.wait(self.interval_seconds):
            self._record_safely()

    def _record_safely(self) -> None:
        try:
            self.record_once()
        except Exception:
            logger.exception("Could not write performance snapshot to Snowflake")

    def record_once(self) -> dict:
        process = psutil.Process()
        system_cpu = psutil.cpu_percent(interval=0.2)
        process_cpu = process.cpu_percent(interval=0.2)
        memory = psutil.virtual_memory()
        process_memory = process.memory_info().rss
        network = psutil.net_io_counters()
        disk = psutil.disk_usage(str(self.disk_path.resolve()))
        try:
            swap = psutil.swap_memory()
        except (PermissionError, OSError):
            # Some hardened macOS/container environments deny host swap details.
            swap = SimpleNamespace(percent=0.0)

        previous = self._previous_network
        received_delta = max(0, network.bytes_recv - previous.bytes_recv) if previous else 0
        sent_delta = max(0, network.bytes_sent - previous.bytes_sent) if previous else 0
        self._previous_network = network

        process_limit_mb = float(os.getenv("GCS_PROCESS_MEMORY_LIMIT_MB", "2048"))
        process_mb = process_memory / 1048576
        reasons = []
        status = "OK"
        if memory.percent >= 90:
            reasons.append(f"critical system memory ({memory.percent:.1f}%)")
        if disk.percent >= 95:
            reasons.append(f"critical disk usage ({disk.percent:.1f}%)")
        if swap.percent >= 80:
            reasons.append(f"critical swap usage ({swap.percent:.1f}%)")
        if process_mb >= process_limit_mb * 0.9:
            reasons.append(f"process near memory limit ({process_mb:.1f}/{process_limit_mb:.0f} MB)")
        if system_cpu >= 95:
            reasons.append(f"critical CPU ({system_cpu:.1f}%)")
        if reasons:
            status = "CRITICAL"
        elif memory.percent >= 80 or disk.percent >= 85 or system_cpu >= 85:
            status = "WARNING"

        now = datetime.now().astimezone()
        record = {
            "Timestamp": now.isoformat(timespec="seconds"),
            "Service name": SERVICE_NAME,
            "Host": socket.gethostname(),
            "Status": status,
            "Critical reasons": "; ".join(reasons),
            "System CPU %": round(system_cpu, 2),
            "System memory %": round(memory.percent, 2),
            "System memory used MB": round(memory.used / 1048576, 2),
            "System memory available MB": round(memory.available / 1048576, 2),
            "Process CPU %": round(process_cpu, 2),
            "Process memory MB": round(process_mb, 2),
            "Process memory %": round(process.memory_percent(), 3),
            "Process threads": process.num_threads(),
            "Data in MB (total)": round(network.bytes_recv / 1048576, 2),
            "Data out MB (total)": round(network.bytes_sent / 1048576, 2),
            "Data in MB (interval)": round(received_delta / 1048576, 2),
            "Data out MB (interval)": round(sent_delta / 1048576, 2),
            "Disk used %": round(disk.percent, 2),
            "Disk free GB": round(disk.free / 1073741824, 2),
            "Swap used %": round(swap.percent, 2),
            "Process uptime hours": round((now.timestamp() - process.create_time()) / 3600, 3),
        }
        self._write_record(now, record)
        return record

    def _write_record(self, now: datetime, record: dict) -> None:
        from services.snowflake_service import SnowflakeService

        database, schema, _table = self.table_name.split(".")
        columns = (
            "RECORDED_AT, SERVICE_NAME, HOST_NAME, STATUS, CRITICAL_REASONS, SYSTEM_CPU_PERCENT, "
            "SYSTEM_MEMORY_PERCENT, SYSTEM_MEMORY_USED_MB, SYSTEM_MEMORY_AVAILABLE_MB, "
            "PROCESS_CPU_PERCENT, PROCESS_MEMORY_MB, PROCESS_MEMORY_PERCENT, PROCESS_THREADS, "
            "DATA_IN_MB_TOTAL, DATA_OUT_MB_TOTAL, DATA_IN_MB_INTERVAL, DATA_OUT_MB_INTERVAL, "
            "DISK_USED_PERCENT, DISK_FREE_GB, SWAP_USED_PERCENT, PROCESS_UPTIME_HOURS"
        )
        values = (
            now, record["Service name"], record["Host"], record["Status"], record["Critical reasons"],
            record["System CPU %"], record["System memory %"], record["System memory used MB"],
            record["System memory available MB"], record["Process CPU %"],
            record["Process memory MB"], record["Process memory %"], record["Process threads"],
            record["Data in MB (total)"], record["Data out MB (total)"],
            record["Data in MB (interval)"], record["Data out MB (interval)"],
            record["Disk used %"], record["Disk free GB"], record["Swap used %"],
            record["Process uptime hours"],
        )
        with self._write_lock:
            conn = SnowflakeService().connect(database=database, schema=schema)
            cursor = conn.cursor()
            try:
                cursor.execute(
                    f"INSERT INTO {self.table_name} ({columns}) VALUES "
                    f"({', '.join(['%s'] * len(values))})",
                    values,
                )
                conn.commit()
            finally:
                cursor.close()
                conn.close()
