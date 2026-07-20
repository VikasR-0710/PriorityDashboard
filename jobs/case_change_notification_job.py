from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import pandas as pd

from config.settings import GCSNotificationSettings, gcs_notification_settings
from jobs.shift_digest_notification_job import _ensure_owner_priority, _owner_in_scope
from services.case_analyst_service import CaseAnalystService
from services.notification_service import (
    CaseNotificationAuditService,
    SlackNotificationService,
)

logger = logging.getLogger(__name__)


def _owner_key(owner: str) -> str:
    return owner.strip().casefold()


@dataclass(frozen=True)
class CaseState:
    case_number: str
    owner: str
    priority: float | None
    escalated: bool
    status: str
    case: dict[str, Any]


class CaseChangeNotificationJob:
    """Detects owner assignment and priority changes between backend snapshots."""

    def __init__(
        self,
        settings: GCSNotificationSettings = gcs_notification_settings,
        analysts: CaseAnalystService | None = None,
        slack: SlackNotificationService | None = None,
        audit: CaseNotificationAuditService | None = None,
    ):
        self.settings = settings
        self.analysts = analysts or CaseAnalystService(settings)
        self.slack = slack or SlackNotificationService(settings)
        self.audit = audit or CaseNotificationAuditService(settings)

    def run(
        self,
        previous_dataframe: pd.DataFrame | None,
        current_dataframe: pd.DataFrame,
    ) -> dict[str, int]:
        stats = {
            "new_assignment": 0,
            "follow_up_response": 0,
            "priority_changed": 0,
            "sent": 0,
            "skipped": 0,
            "errors": 0,
            "audit_records": 0,
            "audit_errors": 0,
        }
        if (
            not self.settings.enabled
            or self.settings.test_only
            or current_dataframe.empty
            or previous_dataframe is None
            or previous_dataframe.empty
        ):
            return stats

        previous_ranked = _ensure_owner_priority(previous_dataframe.copy())
        current_ranked = _ensure_owner_priority(current_dataframe.copy())
        previous = self._state_by_case(previous_ranked)
        current = self._state_by_case(current_ranked)
        new_assignments: dict[str, list[CaseState]] = {}
        priority_changes: dict[str, list[CaseState]] = {}

        for case_number, current_state in current.items():
            if not _owner_in_scope(
                current_state.owner,
                self.settings,
                region=str(current_state.case.get("Region") or ""),
            ):
                continue
            owner_key = _owner_key(current_state.owner)
            previous_state = previous.get(case_number)
            if (
                previous_state is None
                or _owner_key(previous_state.owner) != _owner_key(current_state.owner)
            ):
                stats["new_assignment"] += 1
                new_assignments.setdefault(owner_key, []).append(current_state)
                continue

            if (
                current_state.status.casefold() == "assigned"
                and previous_state.status.casefold() != "assigned"
            ):
                stats["follow_up_response"] += 1
                new_assignments.setdefault(owner_key, []).append(current_state)

            if (
                (
                    current_state.priority is not None
                    and previous_state.priority is not None
                    and current_state.priority != previous_state.priority
                )
                or current_state.escalated != previous_state.escalated
            ):
                stats["priority_changed"] += 1
                priority_changes.setdefault(owner_key, []).append(current_state)

        for owner_key in set(new_assignments) | set(priority_changes):
            assigned_states = new_assignments.get(owner_key, [])
            changed_states = priority_changes.get(owner_key, [])
            representative = (assigned_states or changed_states)[0]
            change_type = "new_assignment" if assigned_states else "priority_changed"
            if assigned_states:
                # Use case two: show the new assignment and every resulting rank change.
                highlighted_case_numbers = {
                    state.case_number for state in assigned_states + changed_states
                }
            else:
                # Use case three: emphasize only cases whose priority increased
                # (a smaller rank number), or which have just become escalated.
                highlighted_case_numbers = set()
                for state in changed_states:
                    previous_state = previous.get(state.case_number)
                    if not previous_state:
                        continue
                    priority_increased = (
                        state.priority is not None
                        and previous_state.priority is not None
                        and state.priority < previous_state.priority
                    )
                    newly_escalated = state.escalated and not previous_state.escalated
                    if priority_increased or newly_escalated:
                        highlighted_case_numbers.add(state.case_number)
            owner_cases = current_ranked[
                current_ranked["Case Owner"].astype(str).str.strip().str.casefold()
                == owner_key
            ].to_dict(orient="records")
            representative_previous = previous.get(representative.case_number)
            audit_events = self._build_audit_events(
                assigned_states,
                changed_states,
                previous,
            )
            self._send(
                representative,
                change_type,
                previous_priority=(
                    representative_previous.priority if representative_previous else None
                ),
                highlighted_case_numbers=highlighted_case_numbers,
                owner_cases=owner_cases,
                audit_events=audit_events,
                stats=stats,
            )
        return stats

    def _send(
        self,
        state: CaseState,
        change_type: str,
        previous_priority: float | None,
        highlighted_case_numbers: set[str],
        owner_cases: list[dict[str, Any]] | None,
        audit_events: list[dict[str, Any]],
        stats: dict[str, int],
    ) -> None:
        analyst = self.analysts.find_active(state.owner)
        if not analyst:
            stats["skipped"] += 1
            return
        result = self.slack.send_case_change_alert(
            state.case,
            analyst.name,
            analyst.email,
            change_type,
            previous_priority=previous_priority,
            current_priority=state.priority,
            owner_cases=owner_cases,
            highlighted_case_numbers=highlighted_case_numbers,
        )
        if result.sent:
            stats["sent"] += 1
            try:
                stats["audit_records"] += self.audit.record_delivery(
                    audit_events,
                    analyst.name,
                    analyst.email,
                    result.slack_user_id,
                    result.slack_message_ts,
                )
            except Exception:
                stats["audit_errors"] += 1
                logger.exception(
                    "Slack delivered, but case notification audit failed for %s",
                    analyst.name,
                )
        elif result.skipped:
            stats["skipped"] += 1
        else:
            stats["errors"] += 1

    @staticmethod
    def _build_audit_events(
        assigned_states: list[CaseState],
        changed_states: list[CaseState],
        previous: dict[str, CaseState],
    ) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []

        def event_payload(
            state: CaseState,
            previous_state: CaseState | None,
            use_case: str,
            notification_type: str,
        ) -> dict[str, Any]:
            return {
                "use_case": use_case,
                "notification_type": notification_type,
                "case_number": state.case_number,
                "region": state.case.get("Region"),
                "customer_name": state.case.get("Customer Name"),
                "previous_owner": previous_state.owner if previous_state else None,
                "current_owner": state.owner,
                "previous_priority": previous_state.priority if previous_state else None,
                "current_priority": state.priority,
                "previous_status": previous_state.status if previous_state else None,
                "current_status": state.status,
                "previous_escalated": previous_state.escalated if previous_state else None,
                "current_escalated": state.escalated,
            }

        for state in assigned_states:
            previous_state = previous.get(state.case_number)
            is_new_owner = (
                previous_state is None
                or _owner_key(previous_state.owner) != _owner_key(state.owner)
            )
            events.append(event_payload(
                state,
                previous_state,
                "USE_CASE_2",
                "NEW_ASSIGNMENT" if is_new_owner else "FOLLOW_UP_RESPONSE",
            ))

        for state in changed_states:
            previous_state = previous.get(state.case_number)
            if not previous_state:
                continue
            if state.escalated != previous_state.escalated:
                events.append(event_payload(
                    state,
                    previous_state,
                    "USE_CASE_3",
                    "ESCALATION" if state.escalated else "DEESCALATION",
                ))
            if (
                state.priority is not None
                and previous_state.priority is not None
                and state.priority != previous_state.priority
            ):
                events.append(event_payload(
                    state,
                    previous_state,
                    "USE_CASE_3",
                    (
                        "PRIORITY_ELEVATION"
                        if state.priority < previous_state.priority
                        else "PRIORITY_DECREASE"
                    ),
                ))
        return events

    def _state_by_case(self, dataframe: pd.DataFrame) -> dict[str, CaseState]:
        dataframe = _ensure_owner_priority(dataframe.copy())
        if "Case Number" not in dataframe.columns or "Case Owner" not in dataframe.columns:
            return {}

        states: dict[str, CaseState] = {}
        for record in dataframe.to_dict(orient="records"):
            case_number = str(record.get("Case Number") or "").strip()
            owner = str(record.get("Case Owner") or "").strip()
            if not case_number or not owner:
                continue
            states[case_number] = CaseState(
                case_number=case_number,
                owner=owner,
                priority=self._priority(record),
                escalated=self._boolean(record.get("Escalated")),
                status=str(record.get("Status") or "").strip(),
                case=record,
            )
        return states

    @staticmethod
    def _changed_priorities_for_owner(
        owner: str,
        previous: dict[str, CaseState],
        current: dict[str, CaseState],
    ) -> set[str]:
        changed = set()
        owner_key = _owner_key(owner)
        for case_number, current_state in current.items():
            previous_state = previous.get(case_number)
            if not previous_state:
                continue
            if (
                _owner_key(current_state.owner) == owner_key
                and _owner_key(previous_state.owner) == owner_key
                and current_state.priority is not None
                and previous_state.priority is not None
                and current_state.priority != previous_state.priority
            ):
                changed.add(case_number)
        return changed

    @staticmethod
    def _priority(record: dict[str, Any]) -> float | None:
        value = record.get("Priority", record.get("Sequential_Rank"))
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _boolean(value: Any) -> bool:
        if value is None or pd.isna(value):
            return False
        if isinstance(value, str):
            return value.strip().casefold() in {"1", "true", "yes", "y"}
        return bool(value)
