"""Run recurring case-change notification work in a short-lived process.

The notification rules remain in ``CaseChangeNotificationJob``.  This module
only moves its imports, Slack client, and Snowflake audit connection outside
the dashboard process so their native allocations are reclaimed by the OS
after each background refresh.
"""

from __future__ import annotations

import pickle
import subprocess
import sys
from contextlib import redirect_stdout
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]


def run_case_change_notifications(previous_dataframe, current_dataframe) -> dict[str, int]:
    completed = subprocess.run(
        [sys.executable, "-m", "services.isolated_notification_operations", "case_changes"],
        cwd=str(BASE_DIR),
        input=pickle.dumps(
            {
                "previous_dataframe": previous_dataframe,
                "current_dataframe": current_dataframe,
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


def _run_child(operation: str, payload: dict):
    if operation != "case_changes":
        raise ValueError(f"Unknown isolated notification operation: {operation}")
    from jobs.case_change_notification_job import CaseChangeNotificationJob

    return CaseChangeNotificationJob().run(
        payload.get("previous_dataframe"),
        payload["current_dataframe"],
    )


if __name__ == "__main__":
    operation = sys.argv[1]
    payload = pickle.loads(sys.stdin.buffer.read())
    # Keep application/status prints out of the binary result channel.
    with redirect_stdout(sys.stderr):
        result = _run_child(operation, payload)
    sys.stdout.buffer.write(pickle.dumps(result, protocol=pickle.HIGHEST_PROTOCOL))
