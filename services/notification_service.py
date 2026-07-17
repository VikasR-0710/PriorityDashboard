from __future__ import annotations

import json
import logging
import re
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping

import pytz

from config.delinea_loader import fetch_slack_credentials
from config.settings import GCSNotificationSettings, gcs_notification_settings
from services.snowflake_service import SnowflakeService

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SlackDeliveryResult:
    sent: bool
    skipped: bool = False
    slack_user_id: str | None = None
    error: str | None = None


class SlackNotificationService:
    """Sends GCS priority DMs. Disabled and dry-run by default."""

    def __init__(self, settings: GCSNotificationSettings = gcs_notification_settings):
        self.settings = settings
        self.client = None
        if not settings.enabled or settings.dry_run:
            return

        credentials = fetch_slack_credentials()
        token = credentials.get("bot_token") if credentials else None
        if not token:
            raise RuntimeError("Slack bot token is unavailable from Delinea")
        if not token.startswith("xoxb-"):
            raise RuntimeError(
                "Slack credential is not a bot token. Expected a token starting "
                "with 'xoxb-' from Delinea secret 'Agentic Support Slack Bot'."
            )

        from slack_sdk import WebClient

        self.client = WebClient(token=token)

    def send_priority_dm(
        self,
        case: Mapping[str, Any],
        recipient_name: str,
        recipient_email: str | None,
    ) -> SlackDeliveryResult:
        if not self.settings.enabled:
            return SlackDeliveryResult(False, skipped=True, error="Slack notifications disabled")
        if self.settings.dry_run:
            logger.info(
                "Dry run: would notify %s for case %s",
                recipient_name,
                case.get("Case Number"),
            )
            return SlackDeliveryResult(False, skipped=True)
        if not self.client:
            return SlackDeliveryResult(False, error="Slack client not initialized")

        try:
            user_id = self._find_user(recipient_email, recipient_name)
            if not user_id:
                return SlackDeliveryResult(False, error=f"Slack user not found: {recipient_name}")

            case_number = str(case.get("Case Number", "Unknown"))
            subject = str(case.get("Subject", "No subject"))
            score = case.get("Case Score Display", case.get("Case Score", "Unknown"))
            owner = str(case.get("Case Owner", "Unknown"))
            customer = str(case.get("Customer Name", "Unknown"))
            region = str(case.get("Region", "Unknown"))
            blocks = [
                {"type": "header", "text": {"type": "plain_text", "text": f"📊 GCS Priority Alert: {case_number}", "emoji": True}},
                {"type": "section", "text": {"type": "mrkdwn", "text": f"Hi {recipient_name},\n\nThis case meets the configured GCS notification criteria."}},
                {"type": "section", "fields": [
                    {"type": "mrkdwn", "text": f"*Case:*\n{case_number}"},
                    {"type": "mrkdwn", "text": f"*GCS Score:*\n{score}"},
                    {"type": "mrkdwn", "text": f"*Owner:*\n{owner}"},
                    {"type": "mrkdwn", "text": f"*Customer:*\n{customer}"},
                    {"type": "mrkdwn", "text": f"*Region:*\n{region}"},
                ]},
                {"type": "section", "text": {"type": "mrkdwn", "text": f"*Subject:*\n{subject}"}},
                {"type": "context", "elements": [{"type": "mrkdwn", "text": "Automated notification from GCS Prioritisation Index."}]},
            ]
            channel = self.client.conversations_open(users=[user_id])["channel"]["id"]
            response = self.client.chat_postMessage(
                channel=channel,
                text=f"GCS Priority Alert: {case_number}",
                blocks=blocks,
            )
            if response.get("ok"):
                return SlackDeliveryResult(True, slack_user_id=user_id)
            return SlackDeliveryResult(False, slack_user_id=user_id, error="Slack rejected message")
        except Exception as exc:
            logger.exception("Slack notification failed")
            return SlackDeliveryResult(False, error=str(exc))

    def send_shift_digest(
        self,
        cases: list[Mapping[str, Any]],
        recipient_name: str,
        recipient_email: str | None,
        shift_name: str,
        shift_start: str,
        snapshot_timestamp: float | datetime,
    ) -> SlackDeliveryResult:
        """Send one compact, ranked digest to a shift owner."""
        if not self.settings.enabled:
            return SlackDeliveryResult(False, skipped=True, error="Slack notifications disabled")
        if self.settings.dry_run:
            logger.info(
                "Dry run: would send %s digest with %s cases to %s",
                shift_name, len(cases), recipient_name,
            )
            return SlackDeliveryResult(False, skipped=True)
        if not self.client:
            return SlackDeliveryResult(False, error="Slack client not initialized")
        if not cases:
            return SlackDeliveryResult(False, skipped=True, error="No priority cases")

        try:
            user_id = self._find_user(recipient_email, recipient_name)
            if not user_id:
                return SlackDeliveryResult(False, error=f"Slack user not found: {recipient_name}")

            if isinstance(snapshot_timestamp, datetime):
                snapshot_dt = snapshot_timestamp
            else:
                snapshot_dt = datetime.fromtimestamp(snapshot_timestamp, tz=pytz.utc)
            if snapshot_dt.tzinfo is None:
                snapshot_dt = pytz.utc.localize(snapshot_dt)
            snapshot_text = snapshot_dt.astimezone(
                pytz.timezone("Asia/Kolkata")
            ).strftime("%d-%b-%Y %I:%M %p IST")

            def numeric(value: Any, default: float) -> float:
                try:
                    return float(value)
                except (TypeError, ValueError):
                    return default

            ranked_cases = sorted(
                cases,
                key=lambda case: (
                    numeric(
                        case.get("Priority", case.get("Sequential_Rank")),
                        float("inf"),
                    ),
                    -numeric(case.get("Case Score"), 0),
                    numeric(case.get("SLA_Minutes"), float("inf")),
                ),
            )
            channel = self.client.conversations_open(users=[user_id])["channel"]["id"]
            page_size = max(1, min(self.settings.digest_cases_per_message, 20))
            pages = [
                ranked_cases[index:index + page_size]
                for index in range(0, len(ranked_cases), page_size)
            ]
            total_pages = len(pages)
            for page_index, page_cases in enumerate(pages, start=1):
                page_label = f" • Part {page_index}/{total_pages}" if total_pages > 1 else ""
                blocks = [
                    {
                        "type": "header",
                        "text": {"type": "plain_text", "text": f"Good day !! Here is your priority for the day !!{page_label}", "emoji": True},
                    },
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": (
                                f"*{shift_name.upper()}* • Shift starting {shift_start} IST\n"
                                f"*Owner:* {recipient_name}"
                            ),
                        },
                    },
                    {"type": "divider"},
                    self._digest_table_block(page_cases),
                ]

                footer = "Please review these cases in priority order."
                if self.settings.dashboard_url:
                    footer += f"\n<{self.settings.dashboard_url}|Open GCS Prioritization Dashboard>"
                blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": footer}]})

                response = self.client.chat_postMessage(
                    channel=channel,
                    text=(
                        f"GCS {shift_name} shift priority digest: "
                        f"{len(ranked_cases)} cases{page_label}"
                    ),
                    blocks=blocks,
                )
                if not response.get("ok"):
                    return SlackDeliveryResult(
                        False, slack_user_id=user_id,
                        error=f"Slack rejected digest part {page_index}/{total_pages}",
                    )
            return SlackDeliveryResult(True, slack_user_id=user_id)
        except Exception as exc:
            logger.exception("Slack shift digest failed")
            return SlackDeliveryResult(False, error=str(exc))

    def _digest_table_block(
        self,
        cases: list[Mapping[str, Any]],
        highlighted_case_number: str | None = None,
        highlighted_case_numbers: set[str] | None = None,
    ) -> dict:
        """Build a native Slack table matching the Case Priority Index columns."""
        columns = [
            ("Case", "Case Number"),
            ("Customer", "Customer Name"),
            ("Support Level", "Support Level"),
            ("Severity", "Severity"),
            ("Status", "Status"),
            ("Escalated", "Escalated"),
            ("Sentiment", "Sentiment"),
            ("Last Comment", "Last Comment By"),
            ("SLA Deadline", "SLA Response Time"),
            ("Sevone", "Sevone"),
            ("Priority", "Priority"),
        ]

        def cell(value: Any, bold: bool = False) -> dict:
            if value is None or str(value).strip().lower() in {"", "nan", "none"}:
                text = "N/A"
            elif isinstance(value, bool):
                text = "Yes" if value else "No"
            elif isinstance(value, float) and value.is_integer():
                text = str(int(value))
            else:
                text = str(value)
            if bold:
                return {
                    "type": "rich_text",
                    "elements": [{
                        "type": "rich_text_section",
                        "elements": [{"type": "text", "text": text, "style": {"bold": True}}],
                    }],
                }
            return {"type": "raw_text", "text": text}

        highlighted = {str(number).strip() for number in (highlighted_case_numbers or set())}
        if highlighted_case_number is not None:
            highlighted.add(highlighted_case_number.strip())

        rows = [[cell(header) for header, _ in columns]]
        for case in cases:
            is_highlighted = str(case.get("Case Number", "")).strip() in highlighted
            row = []
            for _, key in columns:
                value = case.get(key)
                if key == "Priority":
                    value = case.get("Priority", case.get("Sequential_Rank", "N/A"))
                row.append(cell(value, bold=is_highlighted))
            rows.append(row)

        return {
            "type": "table",
            "column_settings": [
                {"align": "center" if key in {"Severity", "Escalated", "Sevone", "Priority"} else "left"}
                for _, key in columns
            ],
            "rows": rows,
        }

    def send_case_change_alert(
        self,
        case: Mapping[str, Any],
        recipient_name: str,
        recipient_email: str | None,
        change_type: str,
        previous_priority: int | float | None = None,
        current_priority: int | float | None = None,
        owner_cases: list[Mapping[str, Any]] | None = None,
        highlighted_case_numbers: set[str] | None = None,
    ) -> SlackDeliveryResult:
        if not self.settings.enabled:
            return SlackDeliveryResult(False, skipped=True, error="Slack notifications disabled")
        if self.settings.dry_run:
            logger.info(
                "Dry run: would send %s alert for case %s to %s",
                change_type, case.get("Case Number"), recipient_name,
            )
            return SlackDeliveryResult(False, skipped=True)
        if not self.client:
            return SlackDeliveryResult(False, error="Slack client not initialized")

        try:
            user_id = self._find_user(recipient_email, recipient_name)
            if not user_id:
                return SlackDeliveryResult(False, error=f"Slack user not found: {recipient_name}")

            case_number = str(case.get("Case Number", "Unknown"))
            case_id = str(case.get("Case Id") or "")
            case_label = case_number
            if self.settings.salesforce_case_url and case_id:
                case_url = self.settings.salesforce_case_url.format(
                    case_id=case_id,
                    case_number=case_number,
                )
                case_label = f"<{case_url}|{case_number}>"

            dashboard_text = "Please look into Priority dashboard."
            if self.settings.dashboard_url:
                dashboard_text = f"Please look into <{self.settings.dashboard_url}|Priority dashboard>."

            priority_text = f"Priority: {current_priority if current_priority is not None else 'N/A'}"
            if change_type == "priority_changed" and previous_priority is not None:
                priority_text = f"Priority changed: {previous_priority} -> {current_priority}"

            title = (
                "New case / Follow-up repsonse recieved !!!"
                if change_type == "new_assignment"
                else "Case priority elevation happened"
            )
            message = (
                "Please check the new follow-up response/case. Your prioritization order is mentioned below!"
                if change_type == "new_assignment"
                else "Case priority changed. Please look into Priority order."
            )
            blocks = [
                {
                    "type": "header",
                    "text": {"type": "plain_text", "text": f"GCS Alert: {title}", "emoji": True},
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"Hi {recipient_name},\n\n{message}",
                    },
                },
            ]
            if owner_cases:
                ranked_owner_cases = sorted(
                    owner_cases,
                    key=lambda item: self._numeric_priority(item),
                )
                blocks.append(self._digest_table_block(
                    ranked_owner_cases,
                    highlighted_case_numbers=(
                        highlighted_case_numbers
                        if highlighted_case_numbers is not None
                        else {case_number}
                    ),
                ))
            channel = self.client.conversations_open(users=[user_id])["channel"]["id"]
            response = self.client.chat_postMessage(
                channel=channel,
                text=f"GCS Alert: {title} - {case_number}",
                blocks=blocks,
            )
            if response.get("ok"):
                return SlackDeliveryResult(True, slack_user_id=user_id)
            return SlackDeliveryResult(False, slack_user_id=user_id, error="Slack rejected message")
        except Exception as exc:
            logger.exception("Slack case change alert failed")
            return SlackDeliveryResult(False, error=str(exc))

    @staticmethod
    def _numeric_priority(case: Mapping[str, Any]) -> float:
        value = case.get("Priority", case.get("Sequential_Rank"))
        try:
            return float(value)
        except (TypeError, ValueError):
            return float("inf")

    def _digest_case_blocks(self, case: Mapping[str, Any], rank: int) -> list[dict]:
        case_number = str(case.get("Case Number", "Unknown"))
        case_id = str(case.get("Case Id") or "")
        case_label = case_number
        if self.settings.salesforce_case_url and case_id:
            case_url = self.settings.salesforce_case_url.format(case_id=case_id, case_number=case_number)
            case_label = f"<{case_url}|{case_number}>"

        severity = str(case.get("Severity", "N/A"))
        support = str(case.get("Support Level", "N/A"))
        sla_text = str(case.get("SLA Response Time", "N/A"))
        icon = "🔴" if rank == 1 else "🟠" if rank == 2 else "🟡"
        text = (
            f"{icon} *Priority {rank} — Case {case_label}*\n"
            f"*Customer:* {case.get('Customer Name', 'N/A')}\n"
            f"*Severity:* {severity} • *Support:* {support}\n"
            f"*Status:* {case.get('Status', 'N/A')} • *Sentiment:* {case.get('Sentiment', 'N/A')}\n"
            f"*SLA:* {sla_text}\n"
            f"*Latest activity:* {case.get('Last Comment By', 'N/A')}\n"
            f"*Escalated:* {'Yes' if case.get('Escalated') else 'No'} • "
            f"*SEV1:* {'Yes' if case.get('Sevone') else 'No'}"
        )
        return [
            {"type": "section", "text": {"type": "mrkdwn", "text": text}},
            {"type": "divider"},
        ]

    def _find_user(self, email: str | None, name: str) -> str | None:
        if email:
            try:
                response = self.client.users_lookupByEmail(email=email)
                if response.get("ok"):
                    return response["user"]["id"]
            except Exception as exc:
                logger.info("Slack email lookup failed for %s; trying name: %s", email, exc)

        cursor = None
        while True:
            response = self.client.users_list(limit=200, cursor=cursor) if cursor else self.client.users_list(limit=200)
            for member in response.get("members", []):
                profile = member.get("profile", {})
                names = {member.get("real_name"), profile.get("real_name"), profile.get("display_name")}
                if any(candidate and candidate.strip().lower() == name.strip().lower() for candidate in names):
                    return member.get("id")
            cursor = response.get("response_metadata", {}).get("next_cursor")
            if not cursor:
                return None


@dataclass(frozen=True)
class NotificationCandidate:
    case: Mapping[str, Any]
    notification_type: str = "GCS_PRIORITY"


class NotificationRuleService:
    """Evaluates notification eligibility without performing any I/O."""

    def __init__(self, settings: GCSNotificationSettings = gcs_notification_settings):
        self.settings = settings

    def evaluate(self, case: Mapping[str, Any]) -> NotificationCandidate | None:
        score = case.get("Case Score")
        if self.settings.score_threshold is not None:
            try:
                if score is None or float(score) < self.settings.score_threshold:
                    return None
            except (TypeError, ValueError):
                return None

        if self.settings.immediate_attention_only:
            priority = str(
                case.get("Prioritization")
                or case.get("Priority Category")
                or case.get("Priority")
                or ""
            ).strip().lower()
            if priority != "need immediate attention":
                return None

        if self.settings.score_threshold is None and not self.settings.immediate_attention_only:
            return None
        return NotificationCandidate(case=case)


def _safe_identifier(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$.]*", value):
        raise ValueError(f"Invalid Snowflake identifier: {value!r}")
    return value


class NotificationRunService:
    """Claims deterministic shift runs so restarts cannot send duplicate digests."""

    def __init__(
        self,
        settings: GCSNotificationSettings = gcs_notification_settings,
        snowflake: SnowflakeService | None = None,
    ):
        self.table = _safe_identifier(settings.runs_table)
        self.snowflake = snowflake or SnowflakeService()

    def _ensure_table(self, cursor) -> None:
        cursor.execute(
            f"""CREATE TABLE IF NOT EXISTS {self.table} (
                RUN_ID VARCHAR PRIMARY KEY,
                STARTED_AT TIMESTAMP_TZ DEFAULT CURRENT_TIMESTAMP(),
                COMPLETED_AT TIMESTAMP_TZ,
                STATUS VARCHAR,
                STATS VARIANT,
                ERROR_MESSAGE VARCHAR
            )"""
        )

    def try_start(self, run_id: str) -> bool:
        conn = self.snowflake.connect(
            warehouse="CS_BOT_WH",
            database="CUSTOMER_SUPPORT_BOT_LOGS",
            schema="CHAT_DATA",
        )
        cursor = conn.cursor()
        try:
            self._ensure_table(cursor)
            cursor.execute(f"SELECT 1 FROM {self.table} WHERE RUN_ID = %s", (run_id,))
            if cursor.fetchone():
                return False
            try:
                cursor.execute(
                    f"INSERT INTO {self.table} (RUN_ID, STATUS) VALUES (%s, 'RUNNING')",
                    (run_id,),
                )
                conn.commit()
                return True
            except Exception:
                conn.rollback()
                return False
        finally:
            cursor.close()
            conn.close()

    def finish(self, run_id: str, status: str, stats=None, error: str | None = None) -> None:
        conn = self.snowflake.connect(
            warehouse="CS_BOT_WH",
            database="CUSTOMER_SUPPORT_BOT_LOGS",
            schema="CHAT_DATA",
        )
        cursor = conn.cursor()
        try:
            self._ensure_table(cursor)
            cursor.execute(
                f"""UPDATE {self.table}
                SET COMPLETED_AT = CURRENT_TIMESTAMP(), STATUS = %s,
                    STATS = PARSE_JSON(%s), ERROR_MESSAGE = %s
                WHERE RUN_ID = %s""",
                (status, json.dumps(stats or {}), error[:1000] if error else None, run_id),
            )
            conn.commit()
        finally:
            cursor.close()
            conn.close()


class NotificationTrackingService:
    """Provides throttling and atomic notification result tracking in Snowflake."""

    def __init__(
        self,
        settings: GCSNotificationSettings = gcs_notification_settings,
        snowflake: SnowflakeService | None = None,
    ):
        self.settings = settings
        self.snowflake = snowflake or SnowflakeService()
        self.table = _safe_identifier(settings.notifications_table)

    def should_send(self, case_number: str, notification_type: str) -> bool:
        conn = self.snowflake.connect()
        cursor = conn.cursor()
        try:
            cursor.execute(
                f"SELECT LAST_NOTIFIED_AT FROM {self.table} "
                "WHERE CASE_NUMBER = %s AND NOTIFICATION_TYPE = %s",
                (case_number, notification_type),
            )
            row = cursor.fetchone()
            if not row or row[0] is None:
                return True
            last_notified = row[0]
            if last_notified.tzinfo is not None:
                last_notified = last_notified.astimezone(timezone.utc).replace(tzinfo=None)
            elapsed_hours = (
                datetime.now(timezone.utc).replace(tzinfo=None) - last_notified
            ).total_seconds() / 3600
            return elapsed_hours >= self.settings.reminder_hours
        finally:
            cursor.close()
            conn.close()

    def record_result(
        self,
        case_number: str,
        notification_type: str,
        recipient_email: str | None,
        sent: bool,
        slack_user_id: str | None = None,
        error: str | None = None,
    ) -> None:
        conn = self.snowflake.connect()
        cursor = conn.cursor()
        try:
            cursor.execute(
                f"""MERGE INTO {self.table} t
                USING (SELECT %s CASE_NUMBER, %s NOTIFICATION_TYPE) s
                ON t.CASE_NUMBER = s.CASE_NUMBER AND t.NOTIFICATION_TYPE = s.NOTIFICATION_TYPE
                WHEN MATCHED THEN UPDATE SET
                    RECIPIENT_EMAIL = %s, NOTIFICATION_SENT = %s, SLACK_USER_ID = %s,
                    ERROR_MESSAGE = %s, LAST_ATTEMPT_AT = CURRENT_TIMESTAMP(),
                    LAST_NOTIFIED_AT = IFF(%s, CURRENT_TIMESTAMP(), t.LAST_NOTIFIED_AT)
                WHEN NOT MATCHED THEN INSERT
                    (CASE_NUMBER, NOTIFICATION_TYPE, RECIPIENT_EMAIL, NOTIFICATION_SENT,
                     SLACK_USER_ID, ERROR_MESSAGE, LAST_ATTEMPT_AT, LAST_NOTIFIED_AT)
                VALUES (%s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP(),
                        IFF(%s, CURRENT_TIMESTAMP(), NULL))""",
                (
                    case_number, notification_type, recipient_email, sent, slack_user_id,
                    error[:1000] if error else None, sent, case_number, notification_type,
                    recipient_email, sent, slack_user_id, error[:1000] if error else None, sent,
                ),
            )
            conn.commit()
        finally:
            cursor.close()
            conn.close()


SHIFT_SCHEDULE_IST = {
    "APAC": (6, 0),
    "EMEA": (14, 0),
    "NA EAST": (18, 0),
    "NA WEST": (21, 0),
}


class ShiftNotificationScheduler:
    """Runs shift digests on weekdays in one daemon thread."""

    def __init__(
        self,
        snapshot_loader: Callable,
        settings: GCSNotificationSettings = gcs_notification_settings,
        job=None,
        runs: NotificationRunService | None = None,
    ):
        self.snapshot_loader = snapshot_loader
        self.settings = settings
        self.job = job
        self.runs = runs
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if not self.settings.enabled:
            logger.info("Slack shift scheduler disabled by GCS_SLACK_ENABLED")
            return
        if self.settings.test_only:
            logger.info("Slack shift scheduler disabled by GCS_SLACK_TEST_ONLY")
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._run, name="gcs-shift-notifications", daemon=True
        )
        self._thread.start()

    def _next_run(self) -> tuple[str, datetime]:
        ist = pytz.timezone("Asia/Kolkata")
        now = datetime.now(ist)
        candidates = []
        for shift, (hour, minute) in SHIFT_SCHEDULE_IST.items():
            target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if target <= now:
                target += timedelta(days=1)
            while target.weekday() >= 5:
                target += timedelta(days=1)
            candidates.append((shift, target))
        return min(candidates, key=lambda item: item[1])

    def _execute_shift_run(self, job, runs: NotificationRunService, shift: str, target: datetime) -> None:
        run_id = (
            f"GCS_SHIFT_{target.strftime('%Y%m%d_%H%M')}_{shift.replace(' ', '_')}"
        )
        if not runs.try_start(run_id):
            logger.info("Slack shift digest already claimed: %s", run_id)
            return
        dataframe, _cases = self.snapshot_loader(
            refresh_token=f"slack-{shift}-{target.isoformat()}"
        )
        stats = job.run(dataframe, shift, target.timestamp())
        runs.finish(run_id, "COMPLETED", stats=stats)
        logger.info("Slack %s shift digest completed: %s", shift, stats)

    def _run(self) -> None:
        from jobs.shift_digest_notification_job import ShiftDigestNotificationJob

        job = self.job or ShiftDigestNotificationJob(self.settings)
        runs = self.runs or NotificationRunService(self.settings)
        while not self._stop.is_set():
            shift, target = self._next_run()
            wait_seconds = max(1, (target - datetime.now(target.tzinfo)).total_seconds())
            if self._stop.wait(wait_seconds):
                return
            try:
                self._execute_shift_run(job, runs, shift, target)
            except Exception as exc:
                run_id = (
                    f"GCS_SHIFT_{target.strftime('%Y%m%d_%H%M')}_{shift.replace(' ', '_')}"
                )
                try:
                    runs.finish(run_id, "FAILED", error=str(exc))
                except Exception:
                    logger.exception("Could not record failed Slack run %s", run_id)
                logger.exception("Slack %s shift digest failed", shift)
