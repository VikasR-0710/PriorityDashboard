from __future__ import annotations

import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()



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

GEMINI_API_KEY = os.getenv(
    "GEMINI_API_KEY"
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


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class GCSNotificationSettings:
    """Non-secret notification controls. Slack credentials come from Delinea."""

    enabled: bool = True
    test_only: bool = False
    dry_run: bool = False
    recipient_scope: str = "NA EAST"
    digest_cases_per_message: int = 20
    salesforce_case_url: str = os.getenv("GCS_SALESFORCE_CASE_URL", "")
    dashboard_url: str = os.getenv("GCS_DASHBOARD_URL", "")
    analyst_table: str = os.getenv(
        "GCS_CASE_ANALYST_TABLE",
        "CUSTOMER_SUPPORT_BOT_LOGS.CHAT_DATA.SF_CASE_ANALYST",
    )
    reminder_hours: int = int(os.getenv("GCS_NOTIFICATION_REMINDER_HOURS", "24"))
    score_threshold: float | None = (
        float(os.environ["GCS_NOTIFICATION_SCORE_THRESHOLD"])
        if os.getenv("GCS_NOTIFICATION_SCORE_THRESHOLD")
        else None
    )
    immediate_attention_only: bool = _bool_env(
        "GCS_NOTIFICATION_IMMEDIATE_ATTENTION_ONLY", False
    )
    notifications_table: str = os.getenv(
        "GCS_NOTIFICATION_TABLE", "DBD_GCS_NOTIFICATIONS"
    )
    runs_table: str = os.getenv(
        "GCS_NOTIFICATION_RUNS_TABLE", "DBD_GCS_NOTIFICATION_RUNS"
    )


gcs_notification_settings = GCSNotificationSettings()
