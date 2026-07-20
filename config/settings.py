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
    runs_table: str = os.getenv(
        "GCS_NOTIFICATION_RUNS_TABLE", "DBD_GCS_NOTIFICATION_RUNS"
    )
    case_notification_audit_table: str = "DBD_GCS_CASE_NOTIFICATION_AUDIT"


gcs_notification_settings = GCSNotificationSettings()
