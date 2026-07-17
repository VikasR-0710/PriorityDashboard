from __future__ import annotations

from datetime import datetime

import pandas as pd

from config.settings import GCSNotificationSettings, gcs_notification_settings
from services.case_analyst_service import CaseAnalystService
from services.notification_service import SlackNotificationService


SHIFT_STARTS_IST = {
    "APAC": "6:00 AM",
    "EMEA": "2:00 PM",
    "NA EAST": "6:00 PM",
    "NA WEST": "9:00 PM",
}


def _numeric(value, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _priority_sort_columns(dataframe: pd.DataFrame) -> tuple[list[str], list[bool]]:
    if "Priority" in dataframe.columns:
        return ["Priority"], [True]
    if "Sequential_Rank" in dataframe.columns:
        return ["Sequential_Rank"], [True]
    return ["Case Score", "SLA_Minutes"], [False, True]


def _ensure_owner_priority(dataframe: pd.DataFrame) -> pd.DataFrame:
    if "Priority" in dataframe.columns or "Sequential_Rank" in dataframe.columns:
        return dataframe
    if "Case Score" not in dataframe.columns:
        return dataframe

    sort_columns = ["Case Owner", "Case Score"]
    sort_ascending = [True, False]

    dataframe = dataframe.sort_values(sort_columns, ascending=sort_ascending).copy()
    dataframe["Priority"] = dataframe.groupby("Case Owner").cumcount() + 1
    return dataframe


def _owner_in_scope(
    owner: str,
    settings: GCSNotificationSettings,
    region: str | None = None,
) -> bool:
    scope = (settings.recipient_scope or "all").strip()
    normalized_scope = scope.casefold()
    return (
        normalized_scope == "all"
        or owner.strip().casefold() == normalized_scope
        or (region is not None and region.strip().casefold() == normalized_scope)
    )


class ShiftDigestNotificationJob:
    """Sends one ranked digest per active case owner at shift start."""

    def __init__(
        self,
        settings: GCSNotificationSettings = gcs_notification_settings,
        analysts: CaseAnalystService | None = None,
        slack: SlackNotificationService | None = None,
    ):
        self.settings = settings
        self.analysts = analysts or CaseAnalystService(settings)
        self.slack = slack or SlackNotificationService(settings)

    def run(
        self,
        dataframe: pd.DataFrame,
        shift_name: str,
        snapshot_timestamp: float | datetime,
    ) -> dict[str, int]:
        stats = {"owners": 0, "sent": 0, "skipped": 0, "errors": 0}
        if not self.settings.enabled or dataframe.empty:
            return stats

        shift = shift_name.strip().upper()
        if shift not in SHIFT_STARTS_IST:
            raise ValueError(f"Unknown shift: {shift_name}")
        shift_cases = dataframe[
            dataframe["Region"].astype(str).str.strip().str.upper() == shift
        ].copy()
        if shift_cases.empty:
            return stats

        shift_cases = _ensure_owner_priority(shift_cases)
        for column in ("Priority", "Sequential_Rank", "Case Score", "SLA_Minutes"):
            if column in shift_cases.columns:
                default = float("inf") if column != "Case Score" else 0
                shift_cases[column] = shift_cases[column].apply(
                    lambda value, default=default: _numeric(value, default)
                )
        sort_columns, sort_ascending = _priority_sort_columns(shift_cases)
        shift_cases = shift_cases.sort_values(
            sort_columns, ascending=sort_ascending
        )
        for owner, owner_cases in shift_cases.groupby("Case Owner", sort=True):
            if not _owner_in_scope(str(owner), self.settings, region=shift):
                continue
            stats["owners"] += 1
            analyst = self.analysts.find_active(str(owner))
            if not analyst:
                stats["skipped"] += 1
                continue
            result = self.slack.send_shift_digest(
                owner_cases.to_dict(orient="records"),
                analyst.name,
                analyst.email,
                shift,
                SHIFT_STARTS_IST[shift],
                snapshot_timestamp,
            )
            if result.sent:
                stats["sent"] += 1
            elif result.skipped:
                stats["skipped"] += 1
            else:
                stats["errors"] += 1
        return stats
