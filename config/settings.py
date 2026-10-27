from __future__ import annotations

import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_csv(name: str, default: str) -> tuple[str, ...]:
    value = os.getenv(name, default)
    return tuple(item.strip() for item in value.split(",") if item.strip())



SALESFORCE_USERNAME = os.getenv(
    "SALESFORCE_USERNAME"
)

SALESFORCE_COMBINED = os.getenv(
    "SALESFORCE_COMBINED"
)

SALESFORCE_DOMAIN = os.getenv(
    "SALESFORCE_DOMAIN"
)



OPENAI_API_KEY = os.getenv(
    "OPENAI_API_KEY"
)

APTEDGE_API_KEY = os.getenv(
    "APTEDGE_API_KEY"
)

APTEDGE_BASE_URL = os.getenv(
    "APTEDGE_BASE_URL"
)

APTEDGE_MODEL = os.getenv(
    "APTEDGE_MODEL"
)


@dataclass(frozen=True)
class GCSNotificationSettings:
    """Non-secret notification controls. Slack credentials come from Delinea."""

    enabled: bool = _env_bool("GCS_SLACK_ENABLED", True)
    test_only: bool = _env_bool("GCS_SLACK_TEST_ONLY", False)
    dry_run: bool = _env_bool("GCS_SLACK_DRY_RUN", False)
    recipient_scope: str = "NA EAST"
    additional_region_recipients: tuple[tuple[str, str], ...] = (
        ("NA WEST", "Sanjay Kademani"),
        ("NA WEST", "Aniket Chinde"),
    )
    digest_cases_per_message: int = 20
    salesforce_case_url: str = os.getenv("GCS_SALESFORCE_CASE_URL", "")
    dashboard_url: str = os.getenv("GCS_DASHBOARD_URL", "")
    analyst_table: str = os.getenv(
        "GCS_CASE_ANALYST_TABLE",
        "CUSTOMER_SUPPORT_BOT_LOGS.CHAT_DATA.SF_CASE_ANALYST",
    )
    runs_table: str = os.getenv(
        "GCS_NOTIFICATION_RUNS_TABLE", "DBD_GCS_NOTIFICATION_RUNS"
    )
    case_notification_audit_table: str = "DBD_GCS_CASE_NOTIFICATION_AUDIT"
    pending_customer_first_alert_days: int = int(
        os.getenv("GCS_PENDING_CUSTOMER_FIRST_ALERT_DAYS", "2")
    )
    pending_customer_last_owner_alert_days: int = int(
        os.getenv("GCS_PENDING_CUSTOMER_LAST_OWNER_ALERT_DAYS", "4")
    )
    pending_customer_manager_alert_days: int = int(
        os.getenv("GCS_PENDING_CUSTOMER_MANAGER_ALERT_DAYS", "5")
    )
    pending_customer_status: str = os.getenv(
        "GCS_PENDING_CUSTOMER_STATUS", "Pending_Customer"
    )
    in_progress_status: str = os.getenv("GCS_IN_PROGRESS_STATUS", "In Progress")
    in_progress_first_alert_days: int = int(
        os.getenv("GCS_IN_PROGRESS_FIRST_ALERT_DAYS", "1")
    )
    in_progress_last_alert_days: int = int(
        os.getenv("GCS_IN_PROGRESS_LAST_ALERT_DAYS", "4")
    )
    in_progress_salesforce_comments_enabled: bool = _env_bool(
        "GCS_IN_PROGRESS_SALESFORCE_COMMENTS_ENABLED", True
    )
    in_progress_pilot_owners: tuple[str, ...] = _env_csv(
        "GCS_IN_PROGRESS_PILOT_OWNERS", ""
    )


gcs_notification_settings = GCSNotificationSettings()
