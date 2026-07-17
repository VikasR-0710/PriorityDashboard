from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping

from config.settings import GCSNotificationSettings, gcs_notification_settings
from services.notification_service import (
    NotificationRuleService,
    NotificationTrackingService,
    SlackNotificationService,
)


@dataclass(frozen=True)
class Recipient:
    name: str
    email: str | None


RecipientResolver = Callable[[Mapping[str, Any]], Iterable[Recipient]]


class PriorityNotificationJob:
    """Explicitly invoked notification workflow; it is not registered with a scheduler."""

    def __init__(
        self,
        recipient_resolver: RecipientResolver,
        settings: GCSNotificationSettings = gcs_notification_settings,
        rules: NotificationRuleService | None = None,
        tracker: NotificationTrackingService | None = None,
        slack: SlackNotificationService | None = None,
    ):
        self.settings = settings
        self.recipient_resolver = recipient_resolver
        self.rules = rules or NotificationRuleService(settings)
        self.tracker = tracker or NotificationTrackingService(settings)
        self.slack = slack or SlackNotificationService(settings)

    def run(self, cases: Iterable[Mapping[str, Any]]) -> dict[str, int]:
        stats = {"evaluated": 0, "eligible": 0, "sent": 0, "skipped": 0, "errors": 0}
        if not self.settings.enabled:
            return stats

        for case in cases:
            stats["evaluated"] += 1
            candidate = self.rules.evaluate(case)
            if not candidate:
                continue
            stats["eligible"] += 1
            case_number = str(case.get("Case Number", ""))
            if not case_number:
                stats["errors"] += 1
                continue

            for recipient in self.recipient_resolver(case):
                if self.settings.dry_run:
                    result = self.slack.send_priority_dm(case, recipient.name, recipient.email)
                    stats["skipped" if result.skipped else "errors"] += 1
                    continue
                notification_key = f"{candidate.notification_type}:{recipient.email or recipient.name}"
                if not self.tracker.should_send(case_number, notification_key):
                    stats["skipped"] += 1
                    continue
                result = self.slack.send_priority_dm(case, recipient.name, recipient.email)
                if result.skipped:
                    stats["skipped"] += 1
                    continue
                self.tracker.record_result(
                    case_number, notification_key, recipient.email, result.sent,
                    result.slack_user_id, result.error,
                )
                stats["sent" if result.sent else "errors"] += 1
        return stats
