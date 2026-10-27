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


def run_pending_customer_notifications() -> dict[str, int]:
    completed = subprocess.run(
        [sys.executable, "-m", "services.isolated_notification_operations", "pending_customer"],
        cwd=str(BASE_DIR),
        input=pickle.dumps({}, protocol=pickle.HIGHEST_PROTOCOL),
        capture_output=True,
        check=True,
    )
    if completed.stderr:
        sys.__stderr__.buffer.write(completed.stderr)
        sys.__stderr__.flush()
    return pickle.loads(completed.stdout)


def run_in_progress_notifications() -> dict[str, int]:
    completed = subprocess.run(
        [sys.executable, "-m", "services.isolated_notification_operations", "in_progress"],
        cwd=str(BASE_DIR),
        input=pickle.dumps({}, protocol=pickle.HIGHEST_PROTOCOL),
        capture_output=True,
        check=True,
    )
    if completed.stderr:
        sys.__stderr__.buffer.write(completed.stderr)
        sys.__stderr__.flush()
    return pickle.loads(completed.stdout)


def run_ageing_notifications(owner_regions: dict[str, str]) -> dict:
    """Run both ageing rules in one child process with shared connections/lookups."""
    completed = subprocess.run(
        [sys.executable, "-m", "services.isolated_notification_operations", "ageing"],
        cwd=str(BASE_DIR),
        input=pickle.dumps(
            {"owner_regions": owner_regions}, protocol=pickle.HIGHEST_PROTOCOL,
        ),
        capture_output=True,
        check=True,
    )
    if completed.stderr:
        sys.__stderr__.buffer.write(completed.stderr)
        sys.__stderr__.flush()
    return pickle.loads(completed.stdout)


def _run_combined_ageing(payload: dict) -> dict:
    from jobs.in_progress_notification_job import InProgressNotificationJob
    from jobs.pending_customer_notification_job import PendingCustomerNotificationJob
    from pages.CasePriorityIndex import get_sf_connection
    from services.case_analyst_service import CaseAnalystService
    from services.notification_service import CaseNotificationAuditService, SlackNotificationService

    sf = get_sf_connection()
    audit = CaseNotificationAuditService()
    analysts = CaseAnalystService()
    slack = SlackNotificationService()
    pending_job = PendingCustomerNotificationJob(
        analysts=analysts, slack=slack, audit=audit,
    )
    in_progress_job = InProgressNotificationJob(
        analysts=analysts, slack=slack, audit=audit,
    )
    pending_cases = pending_job._fetch_cases(sf)
    in_progress_cases = in_progress_job._fetch_cases(sf)
    all_cases = pending_cases + in_progress_cases
    case_numbers = [record.get("CaseNumber") for record in all_cases]
    owners = {
        str((record.get("Owner") or {}).get("Name") or "").strip()
        for record in all_cases
    }
    delivered = audit.delivered_notifications(case_numbers)
    analysts_by_owner = analysts.find_active_many(owners)
    owner_regions = payload.get("owner_regions") or {}
    return {
        "pending_customer": pending_job.run(
            sf=sf,
            cases=pending_cases,
            owner_regions=owner_regions,
            delivered=delivered,
            analysts_by_owner=analysts_by_owner,
        ),
        "in_progress": in_progress_job.run(
            sf=sf,
            cases=in_progress_cases,
            owner_regions=owner_regions,
            delivered=delivered,
            analysts_by_owner=analysts_by_owner,
        ),
        "cases_checked": len(all_cases),
        "analysts_resolved": len(analysts_by_owner),
    }


def _run_child(operation: str, payload: dict):
    if operation == "case_changes":
        from jobs.case_change_notification_job import CaseChangeNotificationJob
        return CaseChangeNotificationJob().run(
            payload.get("previous_dataframe"), payload["current_dataframe"],
        )
    if operation == "pending_customer":
        from jobs.pending_customer_notification_job import PendingCustomerNotificationJob
        return PendingCustomerNotificationJob().run()
    if operation == "in_progress":
        from jobs.in_progress_notification_job import InProgressNotificationJob
        return InProgressNotificationJob().run()
    if operation == "ageing":
        return _run_combined_ageing(payload)
    raise ValueError(f"Unknown isolated notification operation: {operation}")


if __name__ == "__main__":
    operation = sys.argv[1]
    payload = pickle.loads(sys.stdin.buffer.read())
    # Keep application/status prints out of the binary result channel.
    with redirect_stdout(sys.stderr):
        result = _run_child(operation, payload)
    sys.stdout.buffer.write(pickle.dumps(result, protocol=pickle.HIGHEST_PROTOCOL))
