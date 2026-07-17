from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Callable

import pandas as pd

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BackgroundSnapshot:
    dataframe: pd.DataFrame
    cases: list
    refreshed_at: float


class BackgroundCaseRefreshService:
    """Refresh case data independently from Streamlit's visible UI snapshot."""

    def __init__(
        self,
        loader: Callable,
        interval_seconds: int = 600,
        on_refresh: Callable[[BackgroundSnapshot | None, BackgroundSnapshot], None] | None = None,
    ):
        self.loader = loader
        self.interval_seconds = interval_seconds
        self.on_refresh = on_refresh
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._snapshot: BackgroundSnapshot | None = None
        self._last_error: str | None = None

    def start(self, run_immediately: bool = True) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            stop_event = threading.Event()
            self._stop_event = stop_event
            self._thread = threading.Thread(
                target=self._run,
                args=(stop_event, run_immediately),
                name="gcs-background-case-refresh",
                daemon=True,
            )
            self._thread.start()

    def restart(self, run_immediately: bool = False) -> None:
        with self._lock:
            old_thread = self._thread
            self._stop_event.set()
        if old_thread and old_thread.is_alive():
            old_thread.join(timeout=5)
        with self._lock:
            self._thread = None
        self.start(run_immediately=run_immediately)

    def get_snapshot(self) -> BackgroundSnapshot | None:
        with self._lock:
            return self._snapshot

    def get_last_error(self) -> str | None:
        with self._lock:
            return self._last_error

    def _run(self, stop_event: threading.Event, run_immediately: bool) -> None:
        if not run_immediately and stop_event.wait(self.interval_seconds):
            return
        while not stop_event.is_set():
            try:
                refresh_token = f"background-{time.time_ns()}"
                dataframe, cases = self.loader(refresh_token=refresh_token)
                snapshot = BackgroundSnapshot(dataframe, cases, time.time())
                with self._lock:
                    previous_snapshot = self._snapshot
                    self._snapshot = snapshot
                    self._last_error = None
                if self.on_refresh:
                    self.on_refresh(previous_snapshot, snapshot)
                logger.info("Background case snapshot refreshed (%s cases)", len(dataframe))
            except Exception as exc:
                logger.exception("Background case refresh failed")
                with self._lock:
                    self._last_error = str(exc)
            if stop_event.wait(self.interval_seconds):
                return
