"""
AI Sentiment Analysis & Snowflake Ingestion Pipeline
Fetches open Salesforce cases, analyzes them using OpenAI,
and UPSERTS sentiment results into Snowflake table DBD_SENTIMENT_DATA.
"""
import json
import os
import time
import uuid
from datetime import datetime, timezone
from config.logging_setup import setup_daily_logging
from services.case_service import CaseService
from services.openai_service import OpenAIService
from services.snowflake_service import SnowflakeService
from pages.CasePriorityIndex import get_owner_region_map, build_owner_name_filter

LOG_DIR = setup_daily_logging()

# ---------------------------------------------------------------------------
# 🛠️ CONFIGURATION (Environment Variables)
# ---------------------------------------------------------------------------
TARGET_TABLE = "DBD_SENTIMENT_DATA"
USAGE_TABLE = "OPENAI_LLM_USAGE"
AGENT_NAME = "gcs_prioritization_index"
OPENAI_OPERATION = "chat.completions.sentiment"
OPENAI_MODEL = "gpt-4o-mini"
PRICING_TIER = "standard"
PRICE_SOURCE = "https://developers.openai.com/api/docs/pricing?latest-pricing=standard"
OPENAI_DELAY = 0.5
VALID_SENTIMENTS = {"Positive", "Neutral", "Negative", "Critical"}


class MissingBatchSentimentError(ValueError):
    pass


def get_int_env(name, default):
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


OPENAI_BATCH_SIZE = max(get_int_env("OPENAI_BATCH_SIZE", 25), 1)

MODEL_PRICING_PER_1M = {
    "gpt-4o-mini": {
        "input": 0.15,
        "cached_input": 0.075,
        "output": 0.60,
    }
}

# ---------------------------------------------------------------------------
# 📊 SNOWFLAKE HELPERS
# ---------------------------------------------------------------------------
def get_pipeline_snowflake_connection():
    sf_service = SnowflakeService()
    return sf_service.connect(
        warehouse=os.getenv("SNOWFLAKE_WAREHOUSE", "CS_BOT_WH"),
        database=os.getenv("SNOWFLAKE_DATABASE", "CUSTOMER_SUPPORT_BOT_LOGS"),
        schema=os.getenv("SNOWFLAKE_SCHEMA", "CHAT_DATA")
    )


def upsert_to_snowflake(data):
    if not data:
        print("⚠️ No data to upsert.")
        return
    
    print("🔌 Connecting to Snowflake...")
    conn = get_pipeline_snowflake_connection()
    
    cursor = conn.cursor()
    try:
        print(f"📤 Upserting {len(data)} records into {TARGET_TABLE}...")
        values_list = []
        for d in data:
            case_num = d['CaseNumber'].replace("'", "''")
            sentiment = d['Sentiment'].replace("'", "''")
            values_list.append(f"('{case_num}', '{sentiment}')")
        values_str = ", ".join(values_list)
        
        merge_query = f"""
        MERGE INTO {TARGET_TABLE} AS target
        USING (SELECT column1 AS CaseNumber, column2 AS Sentiment FROM VALUES {values_str}) AS source (CaseNumber, Sentiment)
        ON target.CaseNumber = source.CaseNumber
        WHEN MATCHED THEN UPDATE SET target.Sentiment = source.Sentiment
        WHEN NOT MATCHED THEN INSERT (CaseNumber, Sentiment) VALUES (source.CaseNumber, source.Sentiment)
        """
        cursor.execute(merge_query)
        conn.commit()
        print("✅ Successfully upserted records into Snowflake.")
    except Exception as e:
        print(f"❌ Snowflake upsert failed: {e}")
        conn.rollback()
    finally:
        cursor.close()
        conn.close()


def _as_dict(value):
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "to_dict"):
        return value.to_dict()
    return {}


def _usage_int(usage_dict, *keys):
    current = usage_dict
    for key in keys:
        if not isinstance(current, dict):
            return 0
        current = current.get(key)
    return int(current or 0)


def _pricing_for_model(model):
    env_input = os.getenv("OPENAI_INPUT_PRICE_PER_1M")
    env_cached = os.getenv("OPENAI_CACHED_INPUT_PRICE_PER_1M")
    env_output = os.getenv("OPENAI_OUTPUT_PRICE_PER_1M")
    if env_input and env_output:
        return {
            "input": float(env_input),
            "cached_input": float(env_cached or env_input),
            "output": float(env_output),
        }

    normalized = (model or "").lower()
    for model_prefix, pricing in MODEL_PRICING_PER_1M.items():
        if normalized.startswith(model_prefix):
            return pricing
    return None


def estimate_openai_cost_usd(model, input_tokens, cached_input_tokens, output_tokens):
    pricing = _pricing_for_model(model)
    if not pricing:
        return None

    uncached_input_tokens = max(input_tokens - cached_input_tokens, 0)
    cost = (
        (uncached_input_tokens * pricing["input"]) +
        (cached_input_tokens * pricing["cached_input"]) +
        (output_tokens * pricing["output"])
    ) / 1_000_000
    return round(cost, 8)


def insert_openai_usage_audit(conn, record):
    cursor = conn.cursor()
    try:
        cursor.execute(
            f"""
            INSERT INTO {USAGE_TABLE} (
                USAGE_ID, CREATED_AT, AGENT_NAME, OPERATION, STATUS, MODEL,
                RESPONSE_ID, LATENCY_MS, INPUT_TOKENS, CACHED_INPUT_TOKENS,
                OUTPUT_TOKENS, REASONING_TOKENS, TOTAL_TOKENS, ESTIMATED_COST_USD,
                PRICING_TIER, PRICE_SOURCE, RAW_USAGE_JSON, METADATA_JSON, ERROR_MESSAGE
            )
            SELECT
                %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, PARSE_JSON(%s), PARSE_JSON(%s), %s
            """,
            (
                record["usage_id"],
                record["created_at"],
                record["agent_name"],
                record["operation"],
                record["status"],
                record["model"],
                record["response_id"],
                record["latency_ms"],
                record["input_tokens"],
                record["cached_input_tokens"],
                record["output_tokens"],
                record["reasoning_tokens"],
                record["total_tokens"],
                record["estimated_cost_usd"],
                record["pricing_tier"],
                record["price_source"],
                json.dumps(record["raw_usage_json"]),
                json.dumps(record["metadata_json"]),
                record["error_message"],
            )
        )
        conn.commit()
    finally:
        cursor.close()


def audit_openai_usage(conn, status, model, response=None, latency_ms=None, metadata=None, error_message=None):
    if conn is None:
        return

    raw_usage = _as_dict(getattr(response, "usage", None))
    input_tokens = _usage_int(raw_usage, "prompt_tokens") or _usage_int(raw_usage, "input_tokens")
    cached_input_tokens = (
        _usage_int(raw_usage, "prompt_tokens_details", "cached_tokens")
        or _usage_int(raw_usage, "input_tokens_details", "cached_tokens")
        or _usage_int(raw_usage, "cached_input_tokens")
    )
    output_tokens = _usage_int(raw_usage, "completion_tokens") or _usage_int(raw_usage, "output_tokens")
    reasoning_tokens = (
        _usage_int(raw_usage, "completion_tokens_details", "reasoning_tokens")
        or _usage_int(raw_usage, "output_tokens_details", "reasoning_tokens")
        or _usage_int(raw_usage, "reasoning_tokens")
    )
    total_tokens = _usage_int(raw_usage, "total_tokens") or (input_tokens + output_tokens)

    record = {
        "usage_id": str(uuid.uuid4()),
        "created_at": datetime.now(timezone.utc).replace(tzinfo=None),
        "agent_name": AGENT_NAME,
        "operation": OPENAI_OPERATION,
        "status": status,
        "model": model,
        "response_id": getattr(response, "id", None),
        "latency_ms": latency_ms,
        "input_tokens": input_tokens,
        "cached_input_tokens": cached_input_tokens,
        "output_tokens": output_tokens,
        "reasoning_tokens": reasoning_tokens,
        "total_tokens": total_tokens,
        "estimated_cost_usd": estimate_openai_cost_usd(model, input_tokens, cached_input_tokens, output_tokens),
        "pricing_tier": PRICING_TIER,
        "price_source": PRICE_SOURCE,
        "raw_usage_json": raw_usage,
        "metadata_json": metadata or {},
        "error_message": str(error_message)[:16000] if error_message else None,
    }

    try:
        insert_openai_usage_audit(conn, record)
    except Exception as exc:
        print(f"  ⚠️ OpenAI usage audit insert failed: {exc}")


def chunked(items, size):
    size = max(int(size or 1), 1)
    for start in range(0, len(items), size):
        yield start, items[start:start + size]


def build_case_payload(case_record):
    comments_records = (case_record.get("CaseComments") or {}).get("records", [])
    comments = [
        {
            "created_by": c.get("CreatedBy", {}).get("Name", "Unknown"),
            "comment": c.get("CommentBody", ""),
        }
        for c in comments_records[:10]
    ]
    return {
        "case_number": case_record.get("CaseNumber", "UNKNOWN"),
        "subject": case_record.get("Subject"),
        "recent_comments": comments or [{"created_by": "N/A", "comment": "No published comments available."}],
    }


def normalize_sentiment(value):
    normalized = (value or "").strip().capitalize()
    return normalized if normalized in VALID_SENTIMENTS else "Analysis Error"


def parse_batch_sentiment_response(content):
    parsed = json.loads(content)
    results = parsed.get("results") if isinstance(parsed, dict) else parsed
    if not isinstance(results, list):
        raise ValueError("Batch sentiment response must contain a results array")

    sentiments = {}
    for item in results:
        if not isinstance(item, dict):
            continue
        case_number = str(item.get("case_number") or item.get("CaseNumber") or "").strip()
        sentiment = normalize_sentiment(item.get("sentiment") or item.get("Sentiment"))
        if case_number:
            sentiments[case_number] = sentiment
    return sentiments


def analyze_sentiment_batch(case_batch, openai_client, usage_conn=None, batch_number=None):
    payload = [build_case_payload(case_record) for case_record in case_batch]
    case_numbers = [item["case_number"] for item in payload]
    metadata = {
        "operation": "sentiment_analysis_batch",
        "api_type": "chat_completions",
        "batch_number": batch_number,
        "batch_size": len(payload),
        "case_numbers": case_numbers,
    }
    prompt = f"""Analyze each Salesforce support case and classify customer sentiment.
Return one sentiment per case.
Allowed sentiment values: Positive, Neutral, Negative, Critical.

Cases JSON:
{json.dumps(payload, ensure_ascii=False)}
"""

    response = None
    started_at = time.perf_counter()
    try:
        response = openai_client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": "You classify Salesforce support-case sentiment. Return only JSON matching the requested schema.",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "case_sentiment_batch",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "results": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "additionalProperties": False,
                                    "properties": {
                                        "case_number": {"type": "string"},
                                        "sentiment": {
                                            "type": "string",
                                            "enum": ["Positive", "Neutral", "Negative", "Critical"],
                                        },
                                    },
                                    "required": ["case_number", "sentiment"],
                                },
                            }
                        },
                        "required": ["results"],
                    },
                },
            },
        )
        latency_ms = int((time.perf_counter() - started_at) * 1000)
        content = response.choices[0].message.content
        sentiments = parse_batch_sentiment_response(content)
        missing = [case_number for case_number in case_numbers if case_number not in sentiments]
        if missing:
            raise MissingBatchSentimentError(f"Missing sentiment for case(s): {', '.join(missing)}")
        audit_openai_usage(
            usage_conn,
            status="completed",
            model=getattr(response, "model", OPENAI_MODEL),
            response=response,
            latency_ms=latency_ms,
            metadata=metadata,
        )
        return [{"CaseNumber": case_number, "Sentiment": sentiments[case_number]} for case_number in case_numbers]
    except MissingBatchSentimentError as e:
        print(f"  ⚠️ Batch OpenAI sentiment incomplete for cases {case_numbers}: {e}")
        return None
    except Exception as e:
        latency_ms = int((time.perf_counter() - started_at) * 1000)
        audit_openai_usage(
            usage_conn,
            status="failed",
            model=getattr(response, "model", OPENAI_MODEL) if response else OPENAI_MODEL,
            response=response,
            latency_ms=latency_ms,
            metadata=metadata,
            error_message=e,
        )
        print(f"  ⚠️ Batch OpenAI sentiment failed for cases {case_numbers}: {e}")
        return None

def fetch_salesforce_cases():
    print("🔌 Connecting to Salesforce...")
    service = CaseService()
    sf = service.get_connection()
    owner_names_str = build_owner_name_filter(get_owner_region_map().keys())
    query = f"""
    SELECT Id, CaseNumber, Subject, Status, Owner.Name, Account.Name,
    Severity__c, Support_Level__c, IsEscalated,
    (select CommentBody, CreatedBy.Name, CreatedDate from CaseComments where IsPublished=true order by CreatedDate Desc)
    FROM Case
    WHERE Status IN ('New', 'Open', 'Assigned') and Owner.Name IN ({owner_names_str})
    """
    print("📥 Fetching cases...")
    return sf.query_all(query)["records"]

def analyze_sentiment(case_record, openai_client, usage_conn=None):
    comments_records = (case_record.get("CaseComments") or {}).get("records", [])
    comments_text = " | ".join([f"{c.get('CreatedBy', {}).get('Name', 'Unknown')}: {c.get('CommentBody', '')}" for c in comments_records[:10]]) or "No published comments available."
    case_num = case_record.get("CaseNumber", "UNKNOWN")
    metadata = {
        "case_number": case_num,
        "case_id": case_record.get("Id"),
        "operation": "sentiment_analysis",
        "api_type": "chat_completions",
        "comments_count": len(comments_records),
    }
    
    prompt = f"""Analyze this Salesforce support case.
Case Number: {case_num}
Subject: {case_record.get("Subject")}
Recent Comments: {comments_text}
Return ONLY one word: Positive, Neutral, Negative, or Critical."""
    
    started_at = time.perf_counter()
    try:
        response = openai_client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[{"role": "user", "content": prompt}], 
            temperature=0
        )
        latency_ms = int((time.perf_counter() - started_at) * 1000)
        audit_openai_usage(
            usage_conn,
            status="completed",
            model=getattr(response, "model", OPENAI_MODEL),
            response=response,
            latency_ms=latency_ms,
            metadata=metadata,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        latency_ms = int((time.perf_counter() - started_at) * 1000)
        audit_openai_usage(
            usage_conn,
            status="failed",
            model=OPENAI_MODEL,
            response=None,
            latency_ms=latency_ms,
            metadata=metadata,
            error_message=e,
        )
        print(f"  ⚠️ OpenAI failed for {case_num}: {e}")
        return "Analysis Error"

def prepare_and_upsert(cases, openai_client):
    processed = []
    total = len(cases)
    usage_conn = None
    print(f"🧠 Starting AI analysis for {total} cases in batches of {OPENAI_BATCH_SIZE}...")
    try:
        usage_conn = get_pipeline_snowflake_connection()
    except Exception as e:
        print(f"⚠️ OpenAI usage audit disabled. Could not connect to Snowflake: {e}")
        usage_conn = None

    try:
        for start, case_batch in chunked(cases, OPENAI_BATCH_SIZE):
            end = start + len(case_batch)
            batch_number = (start // max(OPENAI_BATCH_SIZE, 1)) + 1
            print(f"  [{start + 1}-{end}/{total}] Analyzing batch of {len(case_batch)} cases...")
            batch_results = analyze_sentiment_batch(case_batch, openai_client, usage_conn, batch_number=batch_number)
            if batch_results is None:
                print("  ↪ Falling back to individual sentiment calls for this batch...")
                for i, case in enumerate(case_batch, start + 1):
                    case_num = case.get("CaseNumber", "UNKNOWN")
                    print(f"    [{i}/{total}] Analyzing {case_num}...")
                    sentiment = analyze_sentiment(case, openai_client, usage_conn)
                    processed.append({"CaseNumber": case_num, "Sentiment": sentiment})
            else:
                processed.extend(batch_results)
            time.sleep(OPENAI_DELAY)
    finally:
        if usage_conn:
            usage_conn.close()

    upsert_to_snowflake(processed)

def main():
    print("🚀 Starting Case Sentiment Analysis & Snowflake Ingestion")
    cases = fetch_salesforce_cases()
    print(f"✅ Fetched {len(cases)} open cases from Salesforce.")
    if not cases:
        print("ℹ️ No cases to process. Exiting.")
        return
    
    openai_svc = OpenAIService()
    openai_client = openai_svc.get_connection()
    prepare_and_upsert(cases, openai_client)
    print("🎉 Pipeline completed successfully.")

if __name__ == "__main__":
    main()
