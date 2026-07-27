"""GCS Prioritization Index web application (FastAPI, no Streamlit)."""

from __future__ import annotations

import asyncio
import fcntl
import math
import os
import threading
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
import pytz
from fastapi import FastAPI, Query, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from config.logging_setup import setup_snowflake_logging
from config.settings import gcs_notification_settings
from jobs.case_change_notification_job import CaseChangeNotificationJob
from pages.CasePriorityIndex import (
    ALL_PRIORITY_OPTION, ALL_REGIONS_OPTION, ALL_SUPPORT_LEVELS_OPTION,
    apply_filters_and_ranking, fetch_owner_config, get_processed_data,
    sync_audit_history,
)
from pages.OngoingSLABreaches import get_filtered_breach_data, sync_sla_breach_impact_history
from pages.Sentiment_analysis import main as run_sentiment_analysis
from pages.WeightageMeter import get_weightage_summary
from services.background_case_refresh_service import BackgroundCaseRefreshService
from services.case_priority_snapshot_service import CasePrioritySnapshotService
from services.notification_service import ShiftNotificationScheduler

setup_snowflake_logging()
BASE_DIR = Path(__file__).resolve().parent
BACKGROUND_REFRESH_SECONDS = 60
BACKGROUND_REFRESH_LABEL = "1 minute(s)"
SESSION_TTL_SECONDS = int(os.getenv("GCS_SESSION_TTL_SECONDS", "86400"))
SESSION_CLEANUP_SECONDS = int(os.getenv("GCS_SESSION_CLEANUP_SECONDS", "900"))
INITIAL_DELAY_MINUTES = 0.5
INTERVAL_MINUTES = 60
SLA_IMPACT_RUN_HOUR_IST = 18

state_lock = threading.RLock()
session_states = {}
runtime_lock_handle = None


def new_session_state():
    return {
        "snapshot": None,
        "last_accessed": time.time(),
        "warnings": [],
        "progress": {"ready": False, "loading": False, "percent": 0,
                     "text": "Preparing to load...", "error": None},
    }


def get_session_state(client_id):
    with state_lock:
        session = session_states.setdefault(client_id, new_session_state())
        session["last_accessed"] = time.time()
        return session


def cleanup_expired_sessions(now=None):
    cutoff = (now or time.time()) - SESSION_TTL_SECONDS
    with state_lock:
        expired = [key for key, value in session_states.items() if value["last_accessed"] < cutoff]
        for key in expired:
            session_states.pop(key, None)
    return len(expired)


def session_cleanup_loop():
    while True:
        time.sleep(SESSION_CLEANUP_SECONDS)
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


def update_startup_progress(client_id, percent, text):
    with state_lock:
        get_session_state(client_id)["progress"].update(
            percent=int(percent), text=text, loading=True, error=None
        )


def load_visible_snapshot(client_id, claimed=False):
    session = get_session_state(client_id)
    with state_lock:
        if session["progress"]["loading"] and not claimed:
            return None
        session["progress"].update(
            ready=False, loading=True, percent=0,
            text="Preparing to load...", error=None,
        )
        session["warnings"] = []
    try:
        dataframe, cases = get_processed_data(
            progress_callback=lambda percent, text: update_startup_progress(client_id, percent, text),
            refresh_token=f"ui-{uuid.uuid4()}",
        )
        update_startup_progress(client_id, 92, "Syncing audit history...")
        try:
            sync_audit_history(dataframe)
        except Exception as exc:
            session["warnings"].append(f"Audit history synchronization failed: {exc}")
        update_startup_progress(client_id, 95, "Syncing SLA breach impact...")
        try:
            sync_sla_breach_impact_history(dataframe)
        except Exception as exc:
            session["warnings"].append(f"SLA breach impact synchronization failed: {exc}")
        update_startup_progress(client_id, 100, "Rendering dashboard...")
        snapshot = {"dataframe": dataframe, "cases": cases, "loaded_at": time.time()}
        with state_lock:
            session["snapshot"] = snapshot
            session["progress"].update(
                ready=True, loading=False, percent=100, text="Rendering dashboard..."
            )
        return snapshot
    except Exception as exc:
        with state_lock:
            session["progress"].update(ready=False, loading=False, error=str(exc))
        raise


def notify_case_changes(previous_snapshot, current_snapshot):
    try:
        CasePrioritySnapshotService().sync(
            current_snapshot.dataframe,
            datetime.fromtimestamp(current_snapshot.refreshed_at, tz=pytz.utc),
        )
    except Exception as exc:
        print(f"⚠️ GCS case priority snapshot sync failed: {exc}")
    if gcs_notification_settings.enabled and not gcs_notification_settings.test_only:
        try:
            CaseChangeNotificationJob().run(
                previous_snapshot.dataframe if previous_snapshot else None,
                current_snapshot.dataframe,
            )
        except Exception as exc:
            print(f"⚠️ GCS case change notifications failed: {exc}")


background_refresh = BackgroundCaseRefreshService(
    loader=get_processed_data,
    interval_seconds=BACKGROUND_REFRESH_SECONDS,
    on_refresh=notify_case_changes,
)


def sentiment_loop():
    time.sleep(INITIAL_DELAY_MINUTES * 60)
    while True:
        try:
            run_sentiment_analysis()
        except Exception as exc:
            print(f"❌ Pipeline execution failed: {exc}")
        time.sleep(INTERVAL_MINUTES * 60)


def sla_impact_loop():
    ist = pytz.timezone("Asia/Kolkata")
    while True:
        now = datetime.now(ist)
        target = now.replace(hour=SLA_IMPACT_RUN_HOUR_IST, minute=0, second=0, microsecond=0)
        if now >= target:
            target += timedelta(days=1)
        time.sleep(max(60, int((target - now).total_seconds())))
        try:
            dataframe, _ = get_processed_data()
            sync_sla_breach_impact_history(dataframe)
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
    threading.Thread(target=sentiment_loop, daemon=True, name="sentiment-pipeline").start()
    threading.Thread(target=sla_impact_loop, daemon=True, name="sla-impact-pipeline").start()
    threading.Thread(target=session_cleanup_loop, daemon=True, name="session-cleanup").start()
    def start_notification_scheduler():
        try:
            scheduler = ShiftNotificationScheduler(snapshot_loader=get_processed_data)
            scheduler.start()
        except Exception as exc:
            print(f"Notification scheduler failed to start: {exc}")
    threading.Thread(target=start_notification_scheduler, daemon=True, name="notification-scheduler-start").start()
    try:
        yield
    finally:
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
    session = get_session_state(client_id)
    with state_lock:
        progress = dict(session["progress"])
        if not progress["ready"] and not progress["loading"] and not progress["error"]:
            session["progress"]["loading"] = True
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
    search: str = "", heal_desk_only: bool = False, sort: Optional[str] = None,
    ascending: bool = True,
):
    client_id = request.state.gcs_client_id
    with state_lock:
        snapshot = get_session_state(client_id)["snapshot"]
    if snapshot is None:
        return {"ready": False}
    df = snapshot["dataframe"].copy()
    filtered, active_owners, search_query, heal_filter = apply_filters_and_ranking(
        df, region or [ALL_REGIONS_OPTION], owner,
        support or [ALL_SUPPORT_LEVELS_OPTION], priority or [ALL_PRIORITY_OPTION],
        search, heal_desk_only,
    )
    if sort and sort in filtered.columns:
        target = "SLA_Minutes" if sort == "SLA Response Time" else sort
        filtered = filtered.sort_values(target, ascending=ascending, na_position="last")
    owner_map = fetch_owner_config()
    regions = sorted(set(owner_map.values()) - {"Agent"})
    active_regions = regions if not region or ALL_REGIONS_OPTION in region else region
    available_owners = sorted(name for name, value in owner_map.items() if value in active_regions)
    support_levels = sorted(str(v).strip() for v in df.get("Support Level", pd.Series(dtype=str)).dropna().unique() if str(v).strip())
    breaches = get_filtered_breach_data(active_owners, search_query, heal_filter)
    background = background_refresh.get_snapshot()
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
        "warnings": list(get_session_state(client_id)["warnings"]),
        "footer": f"Backend data refreshes every {BACKGROUND_REFRESH_LABEL}. The visible index changes only when Refresh is clicked. Audit history retains 2-day change snapshots.",
    }


@app.post("/api/refresh")
async def refresh(request: Request):
    client_id = request.state.gcs_client_id
    background_refresh.restart(run_immediately=False)
    fetch_owner_config.clear()
    with state_lock:
        get_session_state(client_id)["progress"]["loading"] = False
    snapshot = await asyncio.to_thread(load_visible_snapshot, client_id)
    if snapshot is None:
        return {"ok": False}
    return {"ok": True, "loaded_at": snapshot["loaded_at"]}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=os.getenv("HOST", "0.0.0.0"), port=int(os.getenv("PORT", "8505")), reload=False)
