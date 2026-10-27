from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import pytz

from config.settings import GCSNotificationSettings, gcs_notification_settings
from jobs.pending_customer_notification_job import _parse_salesforce_datetime
from jobs.shift_digest_notification_job import _owner_in_scope
from pages.CasePriorityIndex import (
    apply_due_date_sla_gate,
    calculate_sla_deadline,
    calculate_sla_variance,
    convert_to_ist_dt,
    get_case_due_date_field,
    get_owner_region_map,
    get_sf_connection,
    get_sla_hours,
    is_generalized_comment,
)
from services.case_analyst_service import CaseAnalystService
from services.notification_service import CaseNotificationAuditService, SlackNotificationService

logger = logging.getLogger(__name__)
IST = pytz.timezone("Asia/Kolkata")


def _duration_text(total_seconds: float) -> str:
    total_minutes = max(0, int(total_seconds // 60))
    days, remaining = divmod(total_minutes, 1440)
    hours, minutes = divmod(remaining, 60)
    parts = []
    if days:
        parts.append(f"{days} day" if days == 1 else f"{days} days")
    if hours:
        parts.append(f"{hours} hour" if hours == 1 else f"{hours} hours")
    parts.append(f"{minutes} minute" if minutes == 1 else f"{minutes} minutes")
    return " ".join(parts)


class InProgressNotificationJob:
    """Remind scoped owners about escalated cases continuously In Progress."""

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
        status = self.settings.in_progress_status.replace("\\", "\\\\").replace("'", "\\'")
        due_date_field = get_case_due_date_field()
        due_date_select = f", {due_date_field}" if due_date_field else ""
        query = f"""
            SELECT Id, CaseNumber, Subject, Status, OwnerId, Owner.Name,
                Account.Name, AccountName__r.Name, Support_Level__c, Severity__c,
                CreatedDate{due_date_select},
                (SELECT CreatedDate, OldValue, NewValue
                 FROM Histories WHERE Field = 'Status'
                 ORDER BY CreatedDate DESC LIMIT 1),
                (SELECT CommentBody, CreatedBy.Name, CreatedDate, IsPublished
                 FROM CaseComments ORDER BY CreatedDate DESC)
            FROM Case
            WHERE IsEscalated = true AND Status = '{status}'
        """
        return sf.query_all(query)["records"]

    @staticmethod
    def _latest_status_change(record: dict[str, Any]) -> datetime | None:
        histories = (record.get("Histories") or {}).get("records") or []
        value = histories[0].get("CreatedDate") if histories else None
        return _parse_salesforce_datetime(value) if value else None

    @staticmethod
    def _account_or_project(record: dict[str, Any]) -> str:
        account = str((record.get("Account") or {}).get("Name") or "N/A").strip()
        project = str((record.get("AccountName__r") or {}).get("Name") or "").strip()
        if account.casefold() == "xactly corp" and project:
            return project
        return account

    @staticmethod
    def _configured_sla_text(severity: str, support_level: str) -> str:
        hours = get_sla_hours(severity, support_level)
        if hours is None:
            return "N/A"
        return f"{hours:g} hour" if hours == 1 else f"{hours:g} hours"

    @staticmethod
    def _priority_index_sla(record: dict[str, Any], owner_regions: dict[str, str]) -> str:
        """Calculate the SLA Response Time exactly as the Case Priority Index does."""
        support = str(record.get("Support_Level__c") or "N/A")
        severity = str(record.get("Severity__c") or "N/A")
        sla_hours = get_sla_hours(severity, support)
        comments = (record.get("CaseComments") or {}).get("records") or []
        published = [comment for comment in comments if comment.get("IsPublished") is True]
        last_customer_comment = None
        for comment in published:
            if (comment.get("CreatedBy") or {}).get("Name") == "Customer Support User":
                last_customer_comment = convert_to_ist_dt(comment.get("CreatedDate"))
                break

        sla_start = None
        if published:
            latest = published[0]
            author = str((latest.get("CreatedBy") or {}).get("Name") or "")
            if author in owner_regions and not is_generalized_comment(latest.get("CommentBody", "")):
                sla_start = convert_to_ist_dt(latest.get("CreatedDate"))

        due_date_field = get_case_due_date_field()
        due_date_value = record.get(due_date_field) if due_date_field else None
        effective_start = sla_start or last_customer_comment
        effective_start = apply_due_date_sla_gate(effective_start, due_date_value, support)
        deadline = calculate_sla_deadline(effective_start, sla_hours, support)
        if deadline is None:
            created = apply_due_date_sla_gate(
                convert_to_ist_dt(record.get("CreatedDate")), due_date_value, support,
            )
            deadline = calculate_sla_deadline(created, sla_hours, support)
        if deadline is None:
            return "N/A"
        return calculate_sla_variance(deadline, support, effective_start)[0]

    @classmethod
    def _internal_comment(
        cls,
        record: dict[str, Any],
        sla_response_time: str | None = None,
    ) -> str:
        support = str(record.get("Support_Level__c") or "N/A")
        severity = str(record.get("Severity__c") or "N/A")
        return (
            "Hi Team,\n\n"
            f"Account Name / Customer Project - {cls._account_or_project(record)}\n"
            f"Support Level - {support}\n"
            f"SLA - {sla_response_time or cls._configured_sla_text(severity, support)}\n"
            f"Severity - {severity}\n\n"
            "Please note this case has missed its SLA or is about to miss it.\n\n"
            "Thanks"
        )

    @staticmethod
    def _post_internal_comment(sf, case_id: str, body: str) -> None:
        response = sf.CaseComment.create({
            "ParentId": case_id,
            "CommentBody": body,
            "IsPublished": False,
        })
        if not response or not response.get("success"):
            raise RuntimeError(f"Salesforce rejected internal comment: {response!r}")

    def _record_action(
        self,
        milestone: str,
        record: dict[str, Any],
        owner: str,
        analyst_email: str | None,
        slack_user_id: str | None = None,
        slack_message_ts: str | None = None,
        delivered: set[tuple[str, str]] | None = None,
    ) -> None:
        self.audit.record_delivery([{
            "use_case": "IN_PROGRESS",
            "notification_type": milestone,
            "case_number": record.get("CaseNumber"),
            "customer_name": self._account_or_project(record),
            "current_owner": owner,
            "current_status": self.settings.in_progress_status,
            "current_escalated": True,
        }], owner, analyst_email, slack_user_id, slack_message_ts)
        if delivered is not None:
            delivered.add((str(record.get("CaseNumber") or ""), milestone))

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
        stats = {"eligible": 0, "slack_sent": 0, "comments_posted": 0, "skipped": 0, "errors": 0}
        if not self.settings.enabled or self.settings.test_only:
            return stats
        now = (now or datetime.now(IST)).astimezone(IST)
        sf = sf or get_sf_connection()
        owner_regions = owner_regions if owner_regions is not None else get_owner_region_map()
        cases = cases if cases is not None else self._fetch_cases(sf)
        pilot_owners = {
            owner.strip().casefold()
            for owner in self.settings.in_progress_pilot_owners
            if owner.strip()
        }
        for record in cases:
            owner = str((record.get("Owner") or {}).get("Name") or "").strip()
            # An empty pilot list enables the normal regional recipient scope
            # (all NA East owners plus the configured NA West exceptions).
            # A non-empty environment override can still narrow a rollout.
            if pilot_owners and owner.casefold() not in pilot_owners:
                stats["skipped"] += 1
                continue
            region = str(owner_regions.get(owner) or "")
            if not _owner_in_scope(owner, self.settings, region=region):
                stats["skipped"] += 1
                continue
            status_since = self._latest_status_change(record)
            if not status_since or status_since > now:
                stats["skipped"] += 1
                continue
            elapsed_seconds = (now - status_since).total_seconds()
            elapsed_days = int(elapsed_seconds // 86400)
            if not (
                self.settings.in_progress_first_alert_days
                <= elapsed_days
                <= self.settings.in_progress_last_alert_days
            ):
                continue

            case_number = str(record.get("CaseNumber") or "").strip()
            case_id = str(record.get("Id") or "").strip()
            if not case_number or not case_id:
                stats["skipped"] += 1
                continue
            episode = status_since.astimezone(pytz.utc).strftime("%Y%m%dT%H%M%SZ")
            base = f"IN_PROGRESS_{episode}_DAY_{elapsed_days}"
            slack_milestone = f"{base}_SLACK"
            comment_milestone = f"{base}_SF_COMMENT"
            slack_done = (
                (case_number, slack_milestone) in delivered
                if delivered is not None
                else self.audit.was_delivered(case_number, slack_milestone)
            )
            comments_enabled = self.settings.in_progress_salesforce_comments_enabled
            comment_done = (
                not comments_enabled
                or (
                    (case_number, comment_milestone) in delivered
                    if delivered is not None
                    else self.audit.was_delivered(case_number, comment_milestone)
                )
            )
            if slack_done and comment_done:
                stats["skipped"] += 1
                continue

            stats["eligible"] += 1
            analyst = (
                analysts_by_owner.get(owner.casefold())
                if analysts_by_owner is not None
                else self.analysts.find_active(owner)
            )
            analyst_email = analyst.email if analyst else None

            if not comment_done:
                try:
                    sla_response_time = self._priority_index_sla(record, owner_regions)
                    self._post_internal_comment(
                        sf, case_id,
                        self._internal_comment(record, sla_response_time),
                    )
                    self._record_action(
                        comment_milestone, record, owner, analyst_email,
                        delivered=delivered,
                    )
                    stats["comments_posted"] += 1
                except Exception:
                    stats["errors"] += 1
                    logger.exception("Could not post In Progress comment for %s", case_number)

            if not slack_done:
                if not analyst:
                    stats["skipped"] += 1
                    continue
                case = {
                    "Case Id": case_id,
                    "Case Number": case_number,
                    "Case Owner": owner,
                }
                result = self.slack.send_in_progress_alert(
                    case, analyst.name, analyst.email, _duration_text(elapsed_seconds),
                )
                if result.sent:
                    self._record_action(
                        slack_milestone, record, owner, analyst.email,
                        result.slack_user_id, result.slack_message_ts,
                        delivered,
                    )
                    stats["slack_sent"] += 1
                elif result.skipped:
                    stats["skipped"] += 1
                else:
                    stats["errors"] += 1
        return stats
