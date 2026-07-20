from __future__ import annotations

import re
from dataclasses import dataclass

from config.settings import GCSNotificationSettings, gcs_notification_settings
from services.snowflake_service import SnowflakeService


# Salesforce owner names that differ from the shared SF_CASE_ANALYST display name.
# This alias is intentionally local to GCS Slack recipient resolution.
ANALYST_NAME_ALIASES = {
    "prabu r": "Prabu Rajendran",
}


def _safe_identifier(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$.]*", value):
        raise ValueError(f"Invalid Snowflake identifier: {value!r}")
    return value


@dataclass(frozen=True)
class CaseAnalyst:
    name: str
    email: str


class CaseAnalystService:
    """Resolves active case owners through Snowflake SF_CASE_ANALYST."""

    def __init__(
        self,
        settings: GCSNotificationSettings = gcs_notification_settings,
        snowflake: SnowflakeService | None = None,
    ):
        self.table = _safe_identifier(settings.analyst_table)
        self.snowflake = snowflake or SnowflakeService()

    def find_active(self, analyst_name: str) -> CaseAnalyst | None:
        lookup_name = ANALYST_NAME_ALIASES.get(
            analyst_name.strip().casefold(), analyst_name
        )
        conn = self.snowflake.connect(
            warehouse="CS_BOT_WH",
            database="CUSTOMER_SUPPORT_BOT_LOGS",
            schema="CHAT_DATA",
        )
        cursor = conn.cursor()
        try:
            cursor.execute(
                f"""SELECT ANALYST_NAME, EMAIL
                FROM {self.table}
                WHERE IS_ACTIVE = TRUE
                  AND EMAIL IS NOT NULL
                  AND UPPER(TRIM(ANALYST_NAME)) = UPPER(TRIM(%s))
                QUALIFY ROW_NUMBER() OVER (ORDER BY LAST_UPDATED DESC NULLS LAST) = 1""",
                (lookup_name,),
            )
            row = cursor.fetchone()
            # Preserve the Salesforce owner name in Slack text and audit records;
            # only the shared-table lookup uses the alias.
            return CaseAnalyst(analyst_name, str(row[1])) if row else None
        finally:
            cursor.close()
            conn.close()
