from __future__ import annotations

import math
import re
import uuid
from datetime import datetime
from typing import Any

import pandas as pd

from services.snowflake_service import SnowflakeService


def _safe_identifier(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$.]*", value):
        raise ValueError(f"Invalid Snowflake identifier: {value!r}")
    return value


def _clean(value: Any):
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if hasattr(value, "item"):
        value = value.item()
    if pd.isna(value):
        return None
    return value


class CasePrioritySnapshotService:
    """Maintains the current Case Priority Index snapshot for downstream systems."""

    COLUMNS = (
        "CASE_NUMBER",
        "CASE_ID",
        "REGION",
        "CUSTOMER_NAME",
        "CASE_OWNER",
        "SUPPORT_LEVEL",
        "SEVERITY",
        "STATUS",
        "ESCALATED",
        "SENTIMENT",
        "LAST_COMMENT_BY",
        "SLA_RESPONSE_TIME",
        "SLA_MINUTES",
        "SEVONE",
        "PRIORITY",
        "CASE_SCORE",
        "SUBJECT",
        "IS_HEAL_DESK",
        "SNAPSHOT_AT",
    )

    def __init__(
        self,
        snowflake: SnowflakeService | None = None,
        table: str = "DBD_GCS_CASE_PRIORITY_SNAPSHOT",
    ):
        self.snowflake = snowflake or SnowflakeService()
        self.table = _safe_identifier(table)

    @staticmethod
    def _rank(dataframe: pd.DataFrame) -> pd.DataFrame:
        ranked = dataframe.copy()
        if "Region" in ranked.columns:
            ranked = ranked[
                ranked["Region"].astype(str).str.strip().str.casefold() != "agent"
            ].copy()
        if "Case Score" not in ranked.columns:
            ranked["Case Score"] = 0
        if "SLA_Minutes" not in ranked.columns:
            ranked["SLA_Minutes"] = float("inf")
        ranked["Case Score"] = pd.to_numeric(
            ranked["Case Score"], errors="coerce"
        ).fillna(0)
        ranked["SLA_Minutes"] = pd.to_numeric(
            ranked["SLA_Minutes"], errors="coerce"
        ).fillna(float("inf"))
        ranked = ranked.sort_values(
            by=["Case Score", "SLA_Minutes"],
            ascending=[False, True],
            kind="stable",
        ).reset_index(drop=True)
        ranked["Priority"] = range(1, len(ranked) + 1)
        return ranked

    def sync(self, dataframe: pd.DataFrame, snapshot_at: datetime) -> dict[str, int]:
        if dataframe is None or dataframe.empty:
            return {"upserted": 0, "deleted": 0}

        ranked = self._rank(dataframe)
        ranked = ranked.drop_duplicates(subset=["Case Number"], keep="first")
        rows = []
        for record in ranked.to_dict(orient="records"):
            case_number = str(record.get("Case Number") or "").strip()
            if not case_number:
                continue
            rows.append(tuple(_clean(value) for value in (
                case_number,
                record.get("Case Id"),
                record.get("Region"),
                record.get("Customer Name"),
                record.get("Case Owner"),
                record.get("Support Level"),
                record.get("Severity"),
                record.get("Status"),
                record.get("Escalated"),
                record.get("Sentiment"),
                record.get("Last Comment By"),
                record.get("SLA Response Time"),
                record.get("SLA_Minutes"),
                record.get("Sevone"),
                record.get("Priority"),
                record.get("Case Score"),
                record.get("Subject"),
                record.get("Is_Heal_Desk"),
                snapshot_at,
            )))
        if not rows:
            return {"upserted": 0, "deleted": 0}

        stage = _safe_identifier(f"TMP_GCS_PRIORITY_{uuid.uuid4().hex.upper()}")
        conn = self.snowflake.connect(
            warehouse="CS_BOT_WH",
            database="CUSTOMER_SUPPORT_BOT_LOGS",
            schema="CHAT_DATA",
        )
        cursor = conn.cursor()
        try:
            column_list = ", ".join(self.COLUMNS)
            cursor.execute(
                f"CREATE TEMPORARY TABLE {stage} AS "
                f"SELECT {column_list} FROM {self.table} WHERE 1 = 0"
            )
            placeholders = ", ".join(["%s"] * len(self.COLUMNS))
            cursor.executemany(
                f"INSERT INTO {stage} ({column_list}) VALUES ({placeholders})",
                rows,
            )
            update_columns = [
                column for column in self.COLUMNS if column != "CASE_NUMBER"
            ]
            update_clause = ", ".join(
                f"target.{column} = source.{column}" for column in update_columns
            )
            insert_values = ", ".join(f"source.{column}" for column in self.COLUMNS)
            cursor.execute(
                f"""MERGE INTO {self.table} target
                USING {stage} source
                ON target.CASE_NUMBER = source.CASE_NUMBER
                WHEN MATCHED THEN UPDATE SET
                    {update_clause}, target.UPDATED_AT = CURRENT_TIMESTAMP(),
                    target.IST_TIMESTAMP = CONVERT_TIMEZONE('Asia/Kolkata', CURRENT_TIMESTAMP())::TIMESTAMP_NTZ
                WHEN NOT MATCHED THEN INSERT
                    ({column_list}, CREATED_AT, UPDATED_AT, IST_TIMESTAMP)
                VALUES
                    ({insert_values}, CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP(),
                     CONVERT_TIMEZONE('Asia/Kolkata', CURRENT_TIMESTAMP())::TIMESTAMP_NTZ)"""
            )
            cursor.execute(
                f"""DELETE FROM {self.table} target
                WHERE NOT EXISTS (
                    SELECT 1 FROM {stage} source
                    WHERE source.CASE_NUMBER = target.CASE_NUMBER
                )"""
            )
            deleted = max(cursor.rowcount or 0, 0)
            conn.commit()
            return {"upserted": len(rows), "deleted": deleted}
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.close()
            conn.close()
