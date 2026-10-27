from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import pytz

from config.settings import GCSNotificationSettings, gcs_notification_settings
from jobs.shift_digest_notification_job import _owner_in_scope
from pages.CasePriorityIndex import get_owner_region_map, get_sf_connection
from services.case_analyst_service import CaseAnalystService
from services.notification_service import CaseNotificationAuditService, SlackNotificationService

logger = logging.getLogger(__name__)
IST = pytz.timezone("Asia/Kolkata")


def _parse_salesforce_datetime(value: str) -> datetime:
    normalized = value.replace("Z", "+0000")
    for pattern in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            return datetime.strptime(normalized, pattern).astimezone(IST)
        except ValueError:
            continue
    raise ValueError(f"Unsupported Salesforce datetime: {value!r}")


class PendingCustomerNotificationJob:
    """Send exact daily ageing reminders for escalated Pending Customer cases."""

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

    def _fetch_cases(self, sf=None) -> list[dict[str, Any]]:
        sf = sf or get_sf_connection()
        status = self.settings.pending_customer_status.replace("\\", "\\\\").replace("'", "\\'")
        query = f"""
            SELECT Id, CaseNumber, Subject, Status, OwnerId, Owner.Name,
                Account.Name,
                (SELECT CreatedDate, OldValue, NewValue
                 FROM Histories WHERE Field = 'Status'
                 ORDER BY CreatedDate DESC LIMIT 1)
            FROM Case
            WHERE IsEscalated = true AND Status = '{status}'
        """
        return sf.query_all(query)["records"]

    @staticmethod
    def _latest_status_change(record: dict[str, Any]) -> datetime | None:
        histories = (record.get("Histories") or {}).get("records") or []
        if not histories:
            return None
        value = histories[0].get("CreatedDate")
        return _parse_salesforce_datetime(value) if value else None

    @staticmethod
    def _manager(sf, owner_id: str) -> tuple[str, str | None] | None:
        if not owner_id or not owner_id.startswith("005"):
            return None
        result = sf.query(
            "SELECT Manager.Name, Manager.Email FROM User "
            f"WHERE Id = '{owner_id}' LIMIT 1"
        )
        records = result.get("records") or []
        manager = (records[0].get("Manager") or {}) if records else {}
        name = str(manager.get("Name") or "").strip()
        return (name, manager.get("Email")) if name else None

    def run(
        self,
        now: datetime | None = None,
        *,
        sf=None,
        cases: list[dict[str, Any]] | None = None,
        owner_regions: dict[str, str] | None = None,
        delivered: set[tuple[str, str]] | None = None,
        analysts_by_owner=None,
    ) -> dict[str, int]:
        stats = {"eligible": 0, "sent": 0, "skipped": 0, "errors": 0}
        if not self.settings.enabled or self.settings.test_only:
            return stats
        now = (now or datetime.now(IST)).astimezone(IST)
        sf = sf or get_sf_connection()
        owner_regions = owner_regions if owner_regions is not None else get_owner_region_map()
        cases = cases if cases is not None else self._fetch_cases(sf)
        for record in cases:
            owner = str((record.get("Owner") or {}).get("Name") or "").strip()
            region = str(owner_regions.get(owner) or "")
            if not _owner_in_scope(owner, self.settings, region=region):
                stats["skipped"] += 1
                continue
            pending_since = self._latest_status_change(record)
            if not pending_since or pending_since > now:
                stats["skipped"] += 1
                continue
            elapsed_days = int((now - pending_since).total_seconds() // 86400)
            manager_escalation = elapsed_days >= self.settings.pending_customer_manager_alert_days
            owner_alert = (
                self.settings.pending_customer_first_alert_days
                <= elapsed_days
                <= self.settings.pending_customer_last_owner_alert_days
            )
            if not owner_alert and not manager_escalation:
                continue

            # Include the status episode in the key. If a case leaves Pending
            # Customer and enters it again later, the new episode must receive
            # its own reminders rather than matching the old audit records.
            episode = pending_since.astimezone(pytz.utc).strftime("%Y%m%dT%H%M%SZ")
            case_number = str(record.get("CaseNumber") or "").strip()
            if not case_number:
                stats["skipped"] += 1
                continue

            analyst = (
                analysts_by_owner.get(owner.casefold())
                if analysts_by_owner is not None
                else self.analysts.find_active(owner)
            )
            recipients: list[tuple[str, str | None, str, bool]] = []
            if manager_escalation:
                if analyst:
                    recipients.append((
                        analyst.name,
                        analyst.email,
                        f"PENDING_CUSTOMER_{episode}_OWNER_ESCALATION",
                        False,
                    ))
                manager = self._manager(sf, str(record.get("OwnerId") or ""))
                if manager:
                    recipients.append((
                        manager[0],
                        manager[1],
                        f"PENDING_CUSTOMER_{episode}_MANAGER",
                        True,
                    ))
            else:
                if analyst:
                    recipients.append((
                        analyst.name,
                        analyst.email,
                        f"PENDING_CUSTOMER_{episode}_DAY_{elapsed_days}",
                        False,
                    ))
            if not recipients:
                stats["skipped"] += 1
                continue

            case = {
                "Case Id": record.get("Id"),
                "Case Number": case_number,
                "Case Owner": owner,
                "Customer Name": (record.get("Account") or {}).get("Name", "N/A"),
                "Status": record.get("Status"),
                "Subject": record.get("Subject"),
            }
            for recipient_name, recipient_email, milestone, is_manager in recipients:
                already_delivered = (
                    (case_number, milestone) in delivered
                    if delivered is not None
                    else self.audit.was_delivered(case_number, milestone)
                )
                if already_delivered:
                    stats["skipped"] += 1
                    continue
                stats["eligible"] += 1
                result = self.slack.send_pending_customer_alert(
                    case, recipient_name, recipient_email, pending_since, elapsed_days,
                    manager_escalation=is_manager,
                )
                if result.sent:
                    event = {
                        "use_case": "PENDING_CUSTOMER",
                        "notification_type": milestone,
                        "case_number": case_number,
                        "customer_name": case["Customer Name"],
                        "current_owner": owner,
                        "current_status": self.settings.pending_customer_status,
                        "current_escalated": True,
                    }
                    self.audit.record_delivery(
                        [event], recipient_name, recipient_email,
                        result.slack_user_id, result.slack_message_ts,
                    )
                    if delivered is not None:
                        delivered.add((case_number, milestone))
                    stats["sent"] += 1
                elif result.skipped:
                    stats["skipped"] += 1
                else:
                    stats["errors"] += 1
        return stats
