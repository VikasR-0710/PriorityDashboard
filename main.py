"""GCS Prioritization Index web application (FastAPI, no Streamlit)."""

from __future__ import annotations

import asyncio
import ctypes
import fcntl
import gc
import math
import os
import subprocess
import sys
import threading
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
import psutil
import pytz
from fastapi import FastAPI, Query, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from config.logging_setup import setup_snowflake_logging
from config.settings import gcs_notification_settings
from pages.CasePriorityIndex import (
    ALL_PRIORITY_OPTION, ALL_REGIONS_OPTION, ALL_SUPPORT_LEVELS_OPTION,
    apply_filters_and_ranking, close_cached_connections, fetch_owner_config, get_processed_data,
)
from pages.OngoingSLABreaches import get_filtered_breach_data
from pages.WeightageMeter import get_weightage_summary
from services.background_case_refresh_service import BackgroundCaseRefreshService
from services.notification_service import ShiftNotificationScheduler
from services.performance_monitor_service import PerformanceMonitorService
from services.isolated_snowflake_operations import (
    sync_audit_history as isolated_sync_audit_history,
    sync_sla_breach_impact_history as isolated_sync_sla_breach_impact_history,
    sync_priority_snapshot as isolated_sync_priority_snapshot,
    get_processed_data as isolated_get_processed_data,
)
from services.isolated_notification_operations import run_case_change_notifications

setup_snowflake_logging()
BASE_DIR = Path(__file__).resolve().parent
BACKGROUND_REFRESH_SECONDS = 1 * 60
BACKGROUND_REFRESH_LABEL = "1 minute"
ESCALATED_SNAPSHOT_TTL_SECONDS = 60
SESSION_TTL_SECONDS = int(os.getenv("GCS_SESSION_TTL_SECONDS", "7200"))
SESSION_CLEANUP_SECONDS = int(os.getenv("GCS_SESSION_CLEANUP_SECONDS", "900"))
MEMORY_MAINTENANCE_SECONDS = max(
    60, int(os.getenv("GCS_MEMORY_MAINTENANCE_SECONDS", "18000"))
)
MAX_SESSIONS = max(1, int(os.getenv("GCS_MAX_SESSIONS", "100")))
INITIAL_DELAY_MINUTES = 0.5
INTERVAL_MINUTES = 60
SLA_IMPACT_RUN_HOUR_IST = 18

state_lock = threading.RLock()
session_states = {}
visible_state = {
    "snapshot": None,
    "warnings": [],
    "progress": {"ready": False, "loading": False, "percent": 0,
                 "text": "Preparing to load...", "error": None},
}
runtime_lock_handle = None
escalated_snapshot_lock = threading.Lock()
escalated_snapshot = {"dataframe": None, "loaded_at": 0.0}


def get_escalated_snapshot_dataframe(now=None):
    """Return a short-lived snapshot used only by the Escalated Only toggle."""
    current_time = time.time() if now is None else now
    with escalated_snapshot_lock:
        dataframe = escalated_snapshot["dataframe"]
        if (
            dataframe is not None
            and current_time - escalated_snapshot["loaded_at"] < ESCALATED_SNAPSHOT_TTL_SECONDS
        ):
            return dataframe

        dataframe, _cases = isolated_get_processed_data(
            refresh_token=f"escalated-{time.time_ns()}",
            escalated_only=True,
        )
        escalated_snapshot.update(dataframe=dataframe, loaded_at=time.time())
        return dataframe


def new_session_state():
    return {
        "last_accessed": time.time(),
    }


def get_session_state(client_id):
    with state_lock:
        session = session_states.get(client_id)
        if session is None:
            if len(session_states) >= MAX_SESSIONS:
                oldest_client_id = min(
                    session_states, key=lambda key: session_states[key]["last_accessed"]
                )
                session_states.pop(oldest_client_id, None)
            session = new_session_state()
            session_states[client_id] = session
        session["last_accessed"] = time.time()
        return session


def cleanup_expired_sessions(now=None):
    cutoff = (now or time.time()) - SESSION_TTL_SECONDS
    with state_lock:
        expired = [key for key, value in session_states.items() if value["last_accessed"] < cutoff]
        for key in expired:
            session_states.pop(key, None)
    return len(expired)


def session_cleanup_loop(stop_event):
    while not stop_event.wait(SESSION_CLEANUP_SECONDS):
        removed = cleanup_expired_sessions()
        if removed:
            print(f"GCS session cleanup: removed {removed} expired session(s).")


def serializable(value):
    if value is None or (isinstance(value, float) and (math.isnan(value) or math.isinf(value))):
        return None
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, (datetime, pd.Timestamp)):
        return value.isoformat()
    return value


def dataframe_records(df):
    return [{key: serializable(value) for key, value in row.items()} for row in df.to_dict(orient="records")]


def update_startup_progress(_client_id, percent, text):
    with state_lock:
        visible_state["progress"].update(
            percent=int(percent), text=text, loading=True, error=None
        )


def load_visible_snapshot(client_id, claimed=False, prefer_background=False):
    """Publish one read-only UI snapshot without controlling the alert scheduler."""
    return _load_visible_snapshot_impl(client_id, claimed, prefer_background)


def _load_visible_snapshot_impl(client_id, claimed=False, prefer_background=False):
    """Publish one read-only UI snapshot without controlling the alert scheduler."""
    with state_lock:
        if visible_state["progress"]["loading"] and not claimed:
            return None
        visible_state["progress"].update(
            ready=False, loading=True, percent=0,
            text="Preparing to load...", error=None,
        )
        visible_state["warnings"] = []
    try:
        background = background_refresh.get_completed_snapshot() if prefer_background else None
        if background is not None:
            dataframe = background.dataframe
            loaded_at = background.refreshed_at
            update_startup_progress(client_id, 90, "Publishing latest background data...")
        else:
            dataframe, _cases = get_processed_data(
                progress_callback=lambda percent, text: update_startup_progress(client_id, percent, text),
                refresh_token=f"ui-{uuid.uuid4()}",
            )
            loaded_at = time.time()
        update_startup_progress(client_id, 92, "Syncing audit history...")
        try:
            isolated_sync_audit_history(dataframe)
        except Exception as exc:
            with state_lock:
                visible_state["warnings"].append(f"Audit history synchronization failed: {exc}")
        update_startup_progress(client_id, 95, "Syncing SLA breach impact...")
        try:
            isolated_sync_sla_breach_impact_history(dataframe)
        except Exception as exc:
            with state_lock:
                visible_state["warnings"].append(f"SLA breach impact synchronization failed: {exc}")
        update_startup_progress(client_id, 100, "Rendering dashboard...")
        snapshot = {"dataframe": dataframe, "loaded_at": loaded_at}
        with state_lock:
            visible_state["snapshot"] = snapshot
            visible_state["progress"].update(
                ready=True, loading=False, percent=100, text="Rendering dashboard..."
            )
        return snapshot
    except Exception as exc:
        with state_lock:
            visible_state["progress"].update(ready=False, loading=False, error=str(exc))
        raise


def notify_case_changes(previous_snapshot, current_snapshot):
    try:
        isolated_sync_priority_snapshot(
            current_snapshot.dataframe,
            datetime.fromtimestamp(current_snapshot.refreshed_at, tz=pytz.utc),
        )
    except Exception as exc:
        print(f"⚠️ GCS case priority snapshot sync failed: {exc}")
    if gcs_notification_settings.enabled and not gcs_notification_settings.test_only:
        try:
            stats = run_case_change_notifications(
                previous_snapshot.dataframe if previous_snapshot else None,
                current_snapshot.dataframe,
            )
            print(f"ℹ️ GCS case change notification stats: {stats}")
        except Exception as exc:
            print(f"⚠️ GCS case change notifications failed: {exc}")


background_refresh = BackgroundCaseRefreshService(
    loader=isolated_get_processed_data,
    interval_seconds=BACKGROUND_REFRESH_SECONDS,
    on_refresh=notify_case_changes,
)
performance_monitor = PerformanceMonitorService(
    table_name=os.getenv(
        "GCS_PERFORMANCE_TABLE",
        "CUSTOMER_SUPPORT_BOT_LOGS.CHAT_DATA.DBD_GCS_SERVER_PERFORMANCE",
    ),
    interval_seconds=int(os.getenv("GCS_PERFORMANCE_INTERVAL_SECONDS", "900")),
    disk_path=BASE_DIR,
)


def sentiment_loop(stop_event):
    if stop_event.wait(INITIAL_DELAY_MINUTES * 60):
        return
    while not stop_event.is_set():
        try:
            subprocess.run(
                [sys.executable, "-c", "from pages.Sentiment_analysis import main; main()"],
                cwd=str(BASE_DIR),
                check=True,
            )
        except Exception as exc:
            print(f"❌ Pipeline execution failed: {exc}")
        if stop_event.wait(INTERVAL_MINUTES * 60):
            return


def release_unused_memory():
    """Collect unreachable objects and return eligible glibc heap pages to Linux."""
    process = psutil.Process()
    before_mb = process.memory_info().rss / 1048576
    collected = gc.collect()
    trimmed = False
    if sys.platform.startswith("linux"):
        try:
            libc = ctypes.CDLL("libc.so.6")
            libc.malloc_trim.argtypes = [ctypes.c_size_t]
            libc.malloc_trim.restype = ctypes.c_int
            trimmed = bool(libc.malloc_trim(0))
        except (AttributeError, OSError) as exc:
            print(f"Memory maintenance could not call malloc_trim: {exc}")
    after_mb = process.memory_info().rss / 1048576
    print(
        "Memory maintenance completed: "
        f"collected={collected}, malloc_trim={trimmed}, "
        f"rss_before={before_mb:.2f} MB, rss_after={after_mb:.2f} MB, "
        f"released={max(0.0, before_mb - after_mb):.2f} MB"
    )


def memory_maintenance_loop(stop_event):
    while not stop_event.wait(MEMORY_MAINTENANCE_SECONDS):
        try:
            release_unused_memory()
        except Exception as exc:
            print(f"Memory maintenance failed: {exc}")


def sla_impact_loop(stop_event):
    ist = pytz.timezone("Asia/Kolkata")
    while not stop_event.is_set():
        now = datetime.now(ist)
        target = now.replace(hour=SLA_IMPACT_RUN_HOUR_IST, minute=0, second=0, microsecond=0)
        if now >= target:
            target += timedelta(days=1)
        if stop_event.wait(max(60, int((target - now).total_seconds()))):
            return
        try:
            dataframe, _ = isolated_get_processed_data()
            isolated_sync_sla_breach_impact_history(dataframe)
        except Exception as exc:
            print(f"❌ Daily SLA breach impact sync failed: {exc}")


@asynccontextmanager
async def lifespan(_app):
    global runtime_lock_handle
    configured_workers = int(os.getenv("WEB_CONCURRENCY", os.getenv("UVICORN_WORKERS", "1")))
    if configured_workers != 1:
        raise RuntimeError("Newgcs requires exactly one Uvicorn worker because snapshots and schedulers are process-local.")
    lock_path = os.getenv("GCS_RUNTIME_LOCK_PATH", "/tmp/newgcs-runtime.lock")
    runtime_lock_handle = open(lock_path, "a+")
    try:
        fcntl.flock(runtime_lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        runtime_lock_handle.close()
        runtime_lock_handle = None
        raise RuntimeError("Another Newgcs worker is already active; configure exactly one Uvicorn worker.") from exc
    background_refresh.start(run_immediately=False)
    performance_monitor.start(run_immediately=True)
    stop_event = threading.Event()
    runtime_threads = [
        threading.Thread(target=sentiment_loop, args=(stop_event,), daemon=True, name="sentiment-pipeline"),
        threading.Thread(target=sla_impact_loop, args=(stop_event,), daemon=True, name="sla-impact-pipeline"),
        threading.Thread(target=session_cleanup_loop, args=(stop_event,), daemon=True, name="session-cleanup"),
        threading.Thread(
            target=memory_maintenance_loop,
            args=(stop_event,),
            daemon=True,
            name="memory-maintenance",
        ),
    ]
    for thread in runtime_threads:
        thread.start()
    notification_scheduler = ShiftNotificationScheduler(snapshot_loader=isolated_get_processed_data)
    try:
        notification_scheduler.start()
    except Exception as exc:
        print(f"Notification scheduler failed to start: {exc}")
    try:
        yield
    finally:
        stop_event.set()
        notification_scheduler.stop()
        performance_monitor.stop()
        background_refresh.stop()
        for thread in runtime_threads:
            thread.join(timeout=5)
        close_cached_connections()
        fcntl.flock(runtime_lock_handle.fileno(), fcntl.LOCK_UN)
        runtime_lock_handle.close()
        runtime_lock_handle = None


app = FastAPI(title="Prioritization Dashboard", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


@app.middleware("http")
async def disable_browser_cache_during_testing(request, call_next):
    """Always serve the latest UI assets while the dashboard is under test."""
    client_id = request.cookies.get("gcs_client_id") or uuid.uuid4().hex
    request.state.gcs_client_id = client_id
    response = await call_next(request)
    if not request.cookies.get("gcs_client_id"):
        response.set_cookie(
            "gcs_client_id", client_id, httponly=True,
            samesite="lax", max_age=30 * 24 * 60 * 60,
        )
    if request.url.path == "/" or request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


@app.get("/")
def index():
    return FileResponse(BASE_DIR / "static" / "index.html")


@app.get("/api/startup-status")
def startup_status(request: Request):
    client_id = request.state.gcs_client_id
    get_session_state(client_id)
    with state_lock:
        progress = dict(visible_state["progress"])
        if not progress["ready"] and not progress["loading"] and not progress["error"]:
            visible_state["progress"]["loading"] = True
            progress["loading"] = True
            threading.Thread(
                target=load_visible_snapshot, args=(client_id, True), daemon=True,
                name=f"visible-dashboard-load-{client_id[:8]}",
            ).start()
        return progress


@app.get("/api/dashboard")
def dashboard(
    request: Request,
    region: list[str] = Query(default=[]), owner: list[str] = Query(default=[]),
    support: list[str] = Query(default=[]), priority: list[str] = Query(default=[]),
    search: str = "", heal_desk_only: bool = False, escalated_only: bool = False,
    sort: Optional[str] = None,
    ascending: bool = True,
):
    client_id = request.state.gcs_client_id
    with state_lock:
        get_session_state(client_id)
        snapshot = visible_state["snapshot"]
    if snapshot is None:
        return {"ready": False}
    # The published snapshot is immutable. Filtering creates a new frame only
    # when ranking adds request-specific columns, avoiding a full copy here.
    df = snapshot["dataframe"]
    if escalated_only:
        expanded_escalated = get_escalated_snapshot_dataframe()
        df = pd.concat([df, expanded_escalated], ignore_index=True)
        if "Case Number" in df.columns:
            df = df.drop_duplicates(subset=["Case Number"], keep="last")
    filtered, active_owners, search_query, heal_filter = apply_filters_and_ranking(
        df, region or [ALL_REGIONS_OPTION], owner,
        support or [ALL_SUPPORT_LEVELS_OPTION], priority or [ALL_PRIORITY_OPTION],
        search, heal_desk_only, escalated_only,
    )
    if sort and sort in filtered.columns:
        target = "SLA_Minutes" if sort == "SLA Response Time" else sort
        filtered = filtered.sort_values(target, ascending=ascending, na_position="last")
    owner_map = fetch_owner_config()
    regions = sorted(set(owner_map.values()) - {"Agent"})
    active_regions = regions if not region or ALL_REGIONS_OPTION in region else region
    available_owners = sorted(name for name, value in owner_map.items() if value in active_regions)
    support_levels = sorted(str(v).strip() for v in df.get("Support Level", pd.Series(dtype=str)).dropna().unique() if str(v).strip())
    breaches = get_filtered_breach_data(active_owners, search_query, heal_filter, escalated_only)
    background = background_refresh.get_completed_snapshot()
    return {
        "rows": dataframe_records(filtered),
        "filters": {
            "regions": [ALL_REGIONS_OPTION] + regions,
            "owners": available_owners,
            "support_levels": [ALL_SUPPORT_LEVELS_OPTION] + support_levels,
            "priorities": [ALL_PRIORITY_OPTION, "Need Immediate Attention", "Need Secondary Attention"],
        },
        "weightage": get_weightage_summary(filtered),
        "breaches": breaches,
        "loaded_at": snapshot["loaded_at"],
        "new_data_available": bool(background and background.refreshed_at > snapshot["loaded_at"]),
        "background_refreshed_at": background.refreshed_at if background else None,
        "warnings": list(visible_state["warnings"]),
        "footer": f"Backend data refreshes every {BACKGROUND_REFRESH_LABEL}. The visible index changes only when Refresh is clicked. Audit history retains 2-day change snapshots.",
    }


@app.post("/api/refresh")
async def refresh(request: Request):
    client_id = request.state.gcs_client_id
    with state_lock:
        get_session_state(client_id)
        if visible_state["progress"]["loading"]:
            return {"ok": False, "reason": "A visible snapshot is already loading"}
    snapshot = await asyncio.to_thread(load_visible_snapshot, client_id, False, True)
    if snapshot is None:
        return {"ok": False}
    return {"ok": True, "loaded_at": snapshot["loaded_at"]}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=os.getenv("HOST", "0.0.0.0"), port=int(os.getenv("PORT", "8505")), reload=False)
