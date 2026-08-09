import pandas as pd
import hashlib
import json
import time
import math
import numpy as np
import pytz
import os
from datetime import datetime, timedelta
from services.case_service import CaseService
from services.snowflake_service import SnowflakeService # <-- ADDED IMPORT
from services.cache import singleton, ttl_cache

ALL_REGIONS_OPTION = "ALL"
ALL_PRIORITY_OPTION = "All priority"
ALL_SUPPORT_LEVELS_OPTION = "All support levels"
LOW_PRIORITY_RECORD_TYPES = {
    "Decommission Request",
    "Customer Communication",
}

# ---------------------------------------------------------------------------
# 🔑 CONNECTIONS & CACHING
# ---------------------------------------------------------------------------
@singleton
def get_sf_connection():
    service = CaseService()
    return service.get_connection()

@singleton
def get_snowflake_connection():
    # UPDATED: Now uses the centralized SnowflakeService which handles Delinea
    sf_service = SnowflakeService()
    return sf_service.connect(
        warehouse=os.getenv("SNOWFLAKE_WAREHOUSE", "CS_BOT_WH"),
        database=os.getenv("SNOWFLAKE_DATABASE", "CUSTOMER_SUPPORT_BOT_LOGS"),
        schema=os.getenv("SNOWFLAKE_SCHEMA", "CHAT_DATA")
    )


def close_cached_connections():
    """Close process-wide HTTP/database resources during application shutdown."""
    for sf in get_sf_connection.cache_values():
        session = getattr(sf, "session", None)
        if session and hasattr(session, "close"):
            session.close()
    for conn in get_snowflake_connection.cache_values():
        try:
            conn.close()
        except Exception:
            pass
    get_sf_connection.clear()
    get_snowflake_connection.clear()


def ensure_audit_table_exists():
    cur = None
    try:
        conn = get_snowflake_connection()
        cur = conn.cursor()
        cur.execute("""CREATE TABLE IF NOT EXISTS DBD_CASE_AUDIT_HISTORY (
            AUDIT_ID STRING DEFAULT UUID_STRING() PRIMARY KEY, CASE_NUMBER STRING NOT NULL,
            SNAPSHOT_TIMESTAMP TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(), CHANGE_TYPE STRING, 
            CHANGED_COLUMNS VARIANT, OLD_STATE VARIANT, NEW_STATE VARIANT, DATA_HASH STRING,
            IST_TIMESTAMP TIMESTAMP_NTZ DEFAULT
                CONVERT_TIMEZONE('Asia/Kolkata', CURRENT_TIMESTAMP())::TIMESTAMP_NTZ)""")
        cur.execute("ALTER TABLE DBD_CASE_AUDIT_HISTORY SET DATA_RETENTION_TIME_IN_DAYS = 2")
        cur.execute("ALTER TABLE DBD_CASE_AUDIT_HISTORY CLUSTER BY (SNAPSHOT_TIMESTAMP, CASE_NUMBER)")
    except Exception:
        pass
    finally:
        if cur is not None:
            cur.close()

@ttl_cache(ttl=3600)
def fetch_owner_config():
    cursor = None
    try:
        conn = get_snowflake_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT name, COALESCE(region, 'UNKNOWN') AS region
            FROM DBD_OWNER_DATA
            WHERE name IS NOT NULL
            ORDER BY id, name
        """)
        rows = cursor.fetchall()
        return {name: region for name, region in rows if name}
    except Exception as e:
        print(f"❌ Owner data fetch failed: {e}")
        return {}
    finally:
        if cursor is not None:
            cursor.close()

def get_owner_region_map():
    return fetch_owner_config()

def build_owner_name_filter(owner_names):
    safe_names = [name.replace("\\", "\\\\").replace("'", "\\'") for name in owner_names if name]
    if not safe_names:
        raise ValueError("No owner names found in DBD_OWNER_DATA.")
    return "'" + "', '".join(safe_names) + "'"

def fetch_snowflake_sentiments(refresh_token=None):
    # Deliberately uncached: each processed snapshot must read current data.
    cursor = None
    try:
        conn = get_snowflake_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT CaseNumber, Sentiment FROM DBD_SENTIMENT_DATA")
        sentiments = {row[0]: row[1] for row in cursor.fetchall()}
        return sentiments
    except Exception as e:
        print(f"❌ Snowflake fetch failed: {e}")
        return {}
    finally:
        if cursor is not None:
            cursor.close()

def is_low_priority_record_type_case(case):
    record_type_id = (case.get("RecordTypeId") or "").strip().lower()
    record_type_name = ((case.get("RecordType") or {}).get("Name") or "").strip().lower()
    record_type_developer_name = ((case.get("RecordType") or {}).get("DeveloperName") or "").strip().lower()
    low_priority_types = {record_type.lower() for record_type in LOW_PRIORITY_RECORD_TYPES}
    low_priority_developer_names = {record_type.replace(" ", "_").lower() for record_type in LOW_PRIORITY_RECORD_TYPES}

    return (
        record_type_id in low_priority_types
        or record_type_name in low_priority_types
        or record_type_developer_name in low_priority_developer_names
    )

def calculate_score(sevone, severity, support_level, escalated, sentiment="", sla_mins=None, is_low_priority_record_type=False):
    if escalated: return 30
    if is_low_priority_record_type: return 0.25
    if sevone: return 35
    
    is_overdue = isinstance(sla_mins, (int, float)) and sla_mins < 0
    sentiment_lower = (sentiment or "").lower().strip()
    
    if not sentiment_lower or sentiment_lower in ["n/a", "none", "null", "sentiment not available yet"]:
        sentiment_category = "not_available"
    elif "negative" in sentiment_lower or "critical" in sentiment_lower: 
        sentiment_category = "negative"
    elif "positive" in sentiment_lower: 
        sentiment_category = "positive"
    else: 
        sentiment_category = "neutral"
        
    severity_norm = (severity or "").strip().upper()
    if severity_norm.startswith("SEV") or severity_norm == "SEVONE": 
        severity_norm = "S1"
    if severity_norm not in ["S1", "S2", "S3", "S4"]: 
        severity_norm = "S4"
        
    is_premium = "premium" in (support_level or "").lower() or "plus" in (support_level or "").lower()
    
    score_map = {
        ("S1", True, "negative", True): 28, ("S1", True, "positive", True): 27, ("S1", True, "neutral", True): 27, ("S1", True, "not_available", True): 27,
        ("S1", True, "negative", False): 26, ("S1", True, "positive", False): 25, ("S1", True, "neutral", False): 25, ("S1", True, "not_available", False): 25,
        ("S2", True, "negative", True): 23, ("S2", True, "positive", True): 22, ("S2", True, "neutral", True): 22, ("S2", True, "not_available", True): 22,
        ("S2", True, "negative", False): 21, ("S2", True, "positive", False): 20, ("S2", True, "neutral", False): 20, ("S2", True, "not_available", False): 20,
        ("S1", False, "negative", True): 23, ("S1", False, "positive", True): 22, ("S1", False, "neutral", True): 22, ("S1", False, "not_available", True): 22,
        ("S1", False, "negative", False): 21, ("S1", False, "positive", False): 20, ("S1", False, "neutral", False): 20, ("S1", False, "not_available", False): 20,
        ("S3", True, "negative", True): 16, ("S3", True, "positive", True): 15, ("S3", True, "neutral", True): 15, ("S3", True, "not_available", True): 15,
        ("S3", True, "negative", False): 14, ("S3", True, "positive", False): 13, ("S3", True, "neutral", False): 13, ("S3", True, "not_available", False): 13,
        ("S2", False, "negative", True): 12, ("S2", False, "positive", True): 11, ("S2", False, "neutral", True): 11, ("S2", False, "not_available", True): 11,
        ("S2", False, "negative", False): 10, ("S2", False, "positive", False): 9, ("S2", False, "neutral", False): 9, ("S2", False, "not_available", False): 9,
        ("S4", True, "negative", True): 8, ("S4", True, "positive", True): 7, ("S4", True, "neutral", True): 7, ("S4", True, "not_available", True): 7,
        ("S4", True, "negative", False): 6, ("S4", True, "positive", False): 5, ("S4", True, "neutral", False): 5, ("S4", True, "not_available", False): 5,
        ("S3", False, "negative", True): 8, ("S3", False, "positive", True): 7, ("S3", False, "neutral", True): 7, ("S3", False, "not_available", True): 7,
        ("S3", False, "negative", False): 6, ("S3", False, "positive", False): 5, ("S3", False, "neutral", False): 5, ("S3", False, "not_available", False): 5,
        ("S4", False, "negative", True): 4, ("S4", False, "positive", True): 3, ("S4", False, "neutral", True): 3, ("S4", False, "not_available", True): 3,
        ("S4", False, "negative", False): 2, ("S4", False, "positive", False): 1, ("S4", False, "neutral", False): 1, ("S4", False, "not_available", False): 1,
    }
    
    base_score = score_map.get((severity_norm, is_premium, sentiment_category, is_overdue), 0)
    
    # 🎯 FIX: Use minute decimal bonuses. 
    # Max bonus is 0.5, ensuring it NEVER overrides base severity differences.
    # S2 (Base 20) will always beat S3 Overdue (Base 15 + Max 0.5 = 15.5).
    overdue_bonus = 0.0
    if is_overdue:
        abs_mins = abs(sla_mins)
        if abs_mins > 2880:      # Overdue by more than 2 days
            overdue_bonus = 0.5
        elif abs_mins > 1440:    # Overdue by more than 1 day
            overdue_bonus = 0.4
        elif abs_mins > 720:     # Overdue by more than 12 hours
            overdue_bonus = 0.3
        elif abs_mins > 360:     # Overdue by more than 6 hours
            overdue_bonus = 0.2
        elif abs_mins > 60:      # Overdue by more than 1 hour
            overdue_bonus = 0.1
            
    final_score = base_score + overdue_bonus
    return min(final_score, 35)

def get_sla_hours(severity, support_level):
    if not severity or severity == "N/A": return None
    is_premium = "premium" in (support_level.lower() if support_level else "")
    sla_map = {"S1": {"premium": 0.5, "standard": 1.0}, "S2": {"premium": 1.0, "standard": 4.0}, 
               "S3": {"premium": 2.0, "standard": 6.0}, "S4": {"premium": 6.0, "standard": 8.0}}
    severity_key = severity.strip().upper()
    if severity_key.startswith("SEV") or severity_key == "SEVONE": severity_key = "S1"
    elif severity_key not in ["S1", "S2", "S3", "S4"]: return None
    return sla_map[severity_key].get("premium" if is_premium else "standard")

def is_in_weekend_window(dt):
    wd = dt.weekday()
    if wd == 5: return dt.hour >= 5
    if wd == 6: return True
    if wd == 0: return dt.hour < 5
    return False

def jump_to_next_business_time(dt):
    if not is_in_weekend_window(dt): return dt
    wd = dt.weekday()
    if wd == 0: return dt.replace(hour=5, minute=0, second=0, microsecond=0)
    days_ahead = (0 - wd) % 7
    next_mon = dt + timedelta(days=days_ahead)
    return next_mon.replace(hour=5, minute=0, second=0, microsecond=0)

def get_standard_business_minutes(dt1, dt2):
    if dt1 > dt2:
        return -get_standard_business_minutes(dt2, dt1)
        
    current = dt1
    business_mins = 0
    
    while current < dt2:
        if is_in_weekend_window(current):
            # If we land in a weekend, jump straight to Monday 5:00 AM IST
            current = jump_to_next_business_time(current)
            if current > dt2:
                break
        else:
            # We are in business hours. Find the start of the next weekend.
            wd = current.weekday()
            days_ahead = 5 - wd
            if days_ahead < 0:
                days_ahead += 7
                
            next_weekend_start = current.replace(hour=5, minute=0, second=0, microsecond=0) + timedelta(days=days_ahead)
            
            # Catch edge case: If it's Saturday but before 5:00 AM
            if wd == 5 and current.hour < 5:
                next_weekend_start = current.replace(hour=5, minute=0, second=0, microsecond=0)
            
            step_end = min(dt2, next_weekend_start)
            business_mins += int((step_end - current).total_seconds() / 60)
            current = step_end
            
    return business_mins

def add_sla_hours_with_weekend_skip(start_dt, hours, support_level):
    if not support_level or "standard" not in support_level.lower():
        return start_dt + timedelta(hours=hours)
    current = jump_to_next_business_time(start_dt)
    remaining = hours
    step = 0.5
    while remaining > 0:
        add_amt = min(remaining, step)
        next_dt = current + timedelta(hours=add_amt)
        if is_in_weekend_window(next_dt):
            current = jump_to_next_business_time(next_dt)
            continue
        current = next_dt
        remaining -= add_amt
    return current

@ttl_cache(ttl=3600)
def get_case_due_date_field():
    try:
        sf = get_sf_connection()
        fields = sf.Case.describe().get("fields", [])
        field_names = {field.get("name") for field in fields}
        for candidate in ("Due_Date__c", "DueDate__c", "Due_Date_Time__c", "DueDateTime__c", "DueDate"):
            if candidate in field_names:
                return candidate
        for field in fields:
            label = (field.get("label") or "").strip().lower()
            if label in ("due date", "due date/time", "due datetime"):
                return field.get("name")
    except Exception as e:
        print(f"⚠️ Case due date field lookup failed: {e}")
    return None

def get_due_date_sla_start_dt(due_date_value, support_level=None):
    if not due_date_value or due_date_value == "N/A":
        return None

    ist = pytz.timezone("Asia/Kolkata")
    due_date_ist = None

    if isinstance(due_date_value, datetime):
        due_date_ist = due_date_value.astimezone(ist) if due_date_value.tzinfo else ist.localize(due_date_value)
    else:
        due_date_text = str(due_date_value).strip()
        due_date_ist = convert_to_ist_dt(due_date_text)

        if due_date_ist is None:
            try:
                parsed_date = datetime.strptime(due_date_text, "%Y-%m-%d")
                due_date_ist = ist.localize(parsed_date)
            except Exception:
                return None

    return (due_date_ist + timedelta(days=1)).replace(hour=6, minute=0, second=0, microsecond=0)

def apply_due_date_sla_gate(start_dt, due_date_value, support_level=None):
    due_date_sla_start = get_due_date_sla_start_dt(due_date_value, support_level)
    if not due_date_sla_start:
        return start_dt
    if not start_dt:
        return due_date_sla_start
    return max(start_dt, due_date_sla_start)

@ttl_cache(ttl=3600)
def get_project_support(project_id):
    sf = get_sf_connection()
    acc_res = sf.query(f"SELECT Name FROM Account WHERE Id='{project_id}' LIMIT 1")
    if not acc_res["records"]: return None
    proj_name = acc_res["records"][0].get("Name")
    sup_res = sf.query(f"SELECT Support_Level__c FROM Case WHERE Account.Name LIKE '%{proj_name}%' AND Support_Level__c != NULL LIMIT 1")
    return sup_res["records"][0].get("Support_Level__c") if sup_res["records"] else None

def fetch_cases(refresh_token=None):
    # Deliberately uncached: snapshots own their data and old fetches must be releasable.
    sf = get_sf_connection()
    owner_names_str = build_owner_name_filter(get_owner_region_map().keys())
    due_date_field = get_case_due_date_field()
    due_date_select = f", {due_date_field}" if due_date_field else ""
    query = f"""
        SELECT Id, CaseNumber, Subject, Status, Owner.Name, Account.Name, AccountName__c, RecordTypeId, RecordType.Name, RecordType.DeveloperName,
            Support_Level__c, Severity__c, Sevone__c, IsEscalated, CreatedDate, ClosedDate, Heal_Desk__c{due_date_select},
            (select CommentBody, CreatedBy.Name, CreatedDate, IsPublished from CaseComments order by CreatedDate Desc)
        FROM Case
        WHERE Status IN ('New', 'Open', 'Assigned') and Owner.Name IN ({owner_names_str})"""
    return sf.query_all(query)["records"]

def convert_to_ist(date_string):
    if not date_string or date_string == "N/A": return "N/A"
    try:
        date_string = date_string.replace("Z", "+0000")
        fmt = "%Y-%m-%dT%H:%M:%S.%f%z" if "." in date_string else "%Y-%m-%dT%H:%M:%S%z"
        utc_time = datetime.strptime(date_string, fmt)
        return utc_time.astimezone(pytz.timezone("Asia/Kolkata")).strftime("%d-%b %H:%M")
    except: return date_string

def convert_to_ist_dt(date_string):
    if not date_string or date_string == "N/A": return None
    try:
        date_string = date_string.replace("Z", "+0000")
        fmt = "%Y-%m-%dT%H:%M:%S.%f%z" if "." in date_string else "%Y-%m-%dT%H:%M:%S%z"
        utc_time = datetime.strptime(date_string, fmt)
        return utc_time.astimezone(pytz.timezone("Asia/Kolkata"))
    except: return None

def calculate_sla_deadline(start_time, sla_hours_duration, support_level=None):
    if not start_time or not sla_hours_duration: return None
    start_dt = start_time if isinstance(start_time, datetime) else convert_to_ist_dt(start_time)
    if not start_dt: return None
    return add_sla_hours_with_weekend_skip(start_dt, sla_hours_duration, support_level)

def calculate_sla_variance(deadline, support_level=None, sla_start_time=None):
    if not deadline: return "N/A", float('inf')
    try:
        if isinstance(deadline, str):
            ist = pytz.timezone("Asia/Kolkata")
            now_ist = datetime.now(ist)
            parsed = datetime.strptime(deadline, "%d-%b %H:%M")
            candidates = [parsed.replace(year=now_ist.year - 1), parsed.replace(year=now_ist.year), parsed.replace(year=now_ist.year + 1)]
            deadline_dt = min([ist.localize(c) for c in candidates], key=lambda d: abs((d - now_ist).total_seconds()))
        else: deadline_dt = deadline
        
        ist = pytz.timezone("Asia/Kolkata")
        now_dt = datetime.now(ist)
        start_dt = sla_start_time if isinstance(sla_start_time, datetime) else convert_to_ist_dt(sla_start_time)
        
        if start_dt and now_dt < start_dt:
            total_minutes = int((deadline_dt - now_dt).total_seconds() / 60)
        elif support_level and "standard" in support_level.lower():
            total_minutes = get_standard_business_minutes(now_dt, deadline_dt)
        else:
            diff = deadline_dt - now_dt
            total_minutes = int(diff.total_seconds() / 60)
            
        is_overdue = total_minutes < 0
        abs_mins = abs(total_minutes)
        days, rem = divmod(abs_mins, 1440)
        hours, mins = divmod(rem, 60)
        parts = []
        if days > 0: parts.append(f"{days}d")
        if hours > 0 or days > 0: parts.append(f"{hours}h")
        parts.append(f"{mins}m")
        formatted = " ".join(parts)
        return f"🚨 Overdue: {formatted}" if is_overdue else f"⏳ Due in: {formatted}", total_minutes
    except Exception as e: 
        return "N/A", float('inf')

def get_breach_shift(deadline, sla_minutes):
    if not deadline or (isinstance(sla_minutes, (int, float)) and sla_minutes >= 0): return "N/A"
    try:
        if isinstance(deadline, str):
            ist = pytz.timezone("Asia/Kolkata")
            now_ist = datetime.now(ist)
            parsed = datetime.strptime(deadline, "%d-%b %H:%M")
            candidates = [parsed.replace(year=now_ist.year - 1), parsed.replace(year=now_ist.year), parsed.replace(year=now_ist.year + 1)]
            deadline_dt = min([ist.localize(c) for c in candidates], key=lambda d: abs((d - now_ist).total_seconds()))
        else: deadline_dt = deadline
        h = deadline_dt.hour
        if 6 <= h < 14: return "APAC"
        elif 14 <= h < 20: return "EMEA"
        elif h >= 20 or h < 2: return "NA EAST"
        elif 2 <= h < 6: return "NA WEST"
        return "N/A"
    except: return "N/A"

def is_generalized_comment(comment_body):
    if not comment_body: return True
    body_lower = comment_body.lower().strip()
    if len(body_lower.split()) < 5: return True
    generic_phrases = ["looking into this", "working on this", "will get back to you",
        "checking with the team", "checking internally", "investigating the issue",
        "thank you for your patience", "update you shortly", "will update shortly",
        "checking the issue", "update shortly", "out of office"]
    return any(phrase in body_lower for phrase in generic_phrases)

def get_processed_data(progress_callback=None, refresh_token=None):
    if progress_callback:
        progress_callback(5, "Initializing connections...")
        
    cases = fetch_cases(refresh_token=refresh_token)
    if progress_callback:
        progress_callback(20, f"Fetched {len(cases)} cases from Salesforce...")
        
    sf_sentiments = fetch_snowflake_sentiments(refresh_token=refresh_token)
    if progress_callback:
        progress_callback(35, "Fetching sentiment data from Snowflake...")
        
    dashboard = []
    total_cases = len(cases)
    owner_region_map = get_owner_region_map()
    due_date_field = get_case_due_date_field()

    for i, case in enumerate(cases):
        if not case: continue
        
        if progress_callback and i % 5 == 0:
            pct = 35 + int((i / max(total_cases, 1)) * 50)
            progress_callback(pct, f"Calculating priorities... ({i}/{total_cases})")

        owner_name = (case.get("Owner") or {}).get("Name", "UNKNOWN")
        customer_name = (case.get("Account") or {}).get("Name", "N/A")
        support_level = case.get("Support_Level__c") or "N/A"
        project_id = case.get("AccountName__c")
        due_date_value = case.get(due_date_field) if due_date_field else None
        
        if customer_name != "N/A" and "Xactly" in customer_name and project_id:
            try:
                cached = get_project_support(project_id)
                if cached: support_level = cached
            except: pass

        severity = case.get("Severity__c") or "N/A"
        sevone = case.get("Sevone__c", case.get("SEVONE__c")) or False
        escalated = case.get("IsEscalated") or False
        sla_hours = get_sla_hours(severity, support_level)      

        last_customer_comment_dt = None
        comments = (case.get("CaseComments") or {}).get("records", [])
        published_comments = [
            comment for comment in comments if comment.get("IsPublished") is True
        ]
        latest_comment_is_internal = bool(
            comments and comments[0].get("IsPublished") is False
        )
        last_commenter = "Internal Comment"
        
        if published_comments:
            latest = published_comments[0]
            created_by = (latest.get("CreatedBy") or {}).get("Name", "")
            last_commenter = "Support Comment" if created_by in owner_region_map else "Customer Comment"
            if last_commenter == "Support Comment":
                if is_generalized_comment(latest.get("CommentBody", "")):
                    last_commenter = "Support Comment (Generalized)"
            for comment in published_comments:
                if (comment.get("CreatedBy") or {}).get("Name") == 'Customer Support User':
                    last_customer_comment_dt = convert_to_ist_dt(comment.get("CreatedDate"))
                    break
        
        sla_start_dt = None
        if published_comments:
            latest = published_comments[0]
            latest_author = (latest.get("CreatedBy") or {}).get("Name", "")
            
            latest_is_support = latest_author in owner_region_map
            latest_is_gen = is_generalized_comment(latest.get("CommentBody", ""))

            if latest_is_support and not latest_is_gen:
                sla_start_dt = convert_to_ist_dt(latest.get("CreatedDate"))

        effective_start_dt = sla_start_dt if sla_start_dt else last_customer_comment_dt
        effective_start_dt = apply_due_date_sla_gate(effective_start_dt, due_date_value, support_level)
        sla_deadline_dt = calculate_sla_deadline(effective_start_dt, sla_hours, support_level)
        if sla_deadline_dt is None:
            created_dt = convert_to_ist_dt(case.get("CreatedDate"))
            created_dt = apply_due_date_sla_gate(created_dt, due_date_value, support_level)
            sla_deadline_dt = calculate_sla_deadline(created_dt, sla_hours, support_level)
                    
        if sla_deadline_dt:
            sla_text, sla_mins = calculate_sla_variance(sla_deadline_dt, support_level, effective_start_dt)
            breach_shift = get_breach_shift(sla_deadline_dt, sla_mins)
        else:
            sla_text, sla_mins = "N/A", float('inf')
            breach_shift = "N/A"
            
        lcc_display = last_customer_comment_dt.strftime("%d-%b %H:%M") if last_customer_comment_dt else "N/A"
        if lcc_display == "N/A" and case.get("CreatedDate"):
            lcc_display = convert_to_ist(case.get("CreatedDate"))
        
        sentiment_raw = sf_sentiments.get(case.get("CaseNumber"), "")
        sentiment = "sentiment not available yet" if not sentiment_raw or not sentiment_raw.strip() else sentiment_raw
        is_low_priority_record_type = is_low_priority_record_type_case(case)
        case_score = calculate_score(sevone, severity, support_level, escalated, sentiment, sla_mins, is_low_priority_record_type)
        case_score_display = case_score if is_low_priority_record_type and not escalated else int(case_score)
        
        is_heal_desk = bool(case.get("Heal_Desk__c"))

        dashboard.append({
            "Region": owner_region_map.get(owner_name, "UNKNOWN"), "Case Id": case.get("Id"),
            "Case Number": case.get("CaseNumber", "N/A"), "Subject": case.get("Subject", "No subject"),
            "Customer Name": customer_name, "Case Owner": owner_name, "Support Level": support_level,
            "Severity": severity, "Status": case.get("Status", "N/A"), "Escalated": escalated,
            "Last Comment By": last_commenter, "Sentiment": sentiment, "Case Score": case_score,
            "Latest Comment Is Internal": latest_comment_is_internal,
            "Case Score Display": case_score_display,
            "Last Customer Comment": lcc_display, "SLA Response Time": sla_text,
            "SLA_Minutes": sla_mins, "SLA_Breach_Shift": breach_shift,
            "Sevone": bool(sevone), "Is_Heal_Desk": is_heal_desk
        })
        
    if progress_callback:
        progress_callback(88, "Finalizing dashboard data...")
        
    return pd.DataFrame(dashboard), cases

def _make_serializable(obj):
    if isinstance(obj, float) and (math.isinf(obj) or math.isnan(obj)): return None
    if isinstance(obj, (np.integer,)): return int(obj)
    if isinstance(obj, (np.floating,)): return float(obj)
    if isinstance(obj, (np.bool_,)): return bool(obj)
    if isinstance(obj, pd.Timestamp): return obj.isoformat()
    if pd.isna(obj): return None
    return obj

def _compute_hash(row_dict: dict) -> str:
    clean = {k: _make_serializable(v) for k, v in row_dict.items()}
    return hashlib.sha256(json.dumps(clean, sort_keys=True).encode()).hexdigest()

def _get_latest_states(sf_conn, case_numbers: list) -> dict:
    if not case_numbers: return {}
    placeholders = ",".join(["%s"] * len(case_numbers))
    query = f"SELECT CASE_NUMBER, DATA_HASH, NEW_STATE FROM DBD_CASE_AUDIT_HISTORY WHERE CASE_NUMBER IN ({placeholders}) QUALIFY ROW_NUMBER() OVER (PARTITION BY CASE_NUMBER ORDER BY SNAPSHOT_TIMESTAMP DESC) = 1"
    cur = sf_conn.cursor()
    try:
        cur.execute(query, case_numbers)
        rows = cur.fetchall()
    finally:
        cur.close()
    return {row[0]: {"hash": row[1], "state": json.loads(row[2]) if row[2] else {}} for row in rows}

def sync_audit_history(df: pd.DataFrame):
    if df.empty: return
    ensure_audit_table_exists()
    df = df.drop(columns=["Latest Comment Is Internal"], errors="ignore").copy()
    df["Escalated"] = df["Escalated"].astype(bool)
    df["SLA_Minutes"] = pd.to_numeric(df["SLA_Minutes"], errors="coerce")
    df["Case Score"] = pd.to_numeric(df["Case Score"], errors="coerce")
    if "Case Score Display" in df.columns:
        df["Case Score Display"] = pd.to_numeric(df["Case Score Display"], errors="coerce")
    records = df.to_dict(orient="records")
    current_states = {}
    for r in records:
        case_num = r["Case Number"]
        clean_r = {k: _make_serializable(v) for k, v in r.items()}
        current_states[case_num] = {"hash": _compute_hash(clean_r), "state": clean_r}
    conn = get_snowflake_connection()
    prev_states = _get_latest_states(conn, list(current_states.keys()))
    now_utc = datetime.now(pytz.utc)
    audit_rows = []
    for case_num, curr in current_states.items():
        prev = prev_states.get(case_num)
        if not prev:
            audit_rows.append((case_num, now_utc, "NEW", json.dumps(list(curr["state"].keys())), None, json.dumps(curr["state"]), curr["hash"]))
        elif prev["hash"] != curr["hash"]:
            old_s, new_s = prev["state"], curr["state"]
            changed_cols = [k for k in new_s if str(new_s.get(k)) != str(old_s.get(k))]
            audit_rows.append((case_num, now_utc, "UPDATED", json.dumps(changed_cols), json.dumps(old_s), json.dumps(new_s), curr["hash"]))
    if not audit_rows: return
    cur = conn.cursor()
    temp_table_name = "TEMP_AUDIT_STAGE_" + str(int(time.time()))
    try:
        cur.execute(f"CREATE OR REPLACE TEMPORARY TABLE {temp_table_name} (CASE_NUMBER STRING, SNAPSHOT_TIMESTAMP TIMESTAMP_NTZ, CHANGE_TYPE STRING, CHANGED_COLUMNS_STR STRING, OLD_STATE_STR STRING, NEW_STATE_STR STRING, DATA_HASH STRING)")
        cur.executemany(f"INSERT INTO {temp_table_name} (CASE_NUMBER, SNAPSHOT_TIMESTAMP, CHANGE_TYPE, CHANGED_COLUMNS_STR, OLD_STATE_STR, NEW_STATE_STR, DATA_HASH) VALUES (%s, %s, %s, %s, %s, %s, %s)", audit_rows)
        cur.execute(f"""INSERT INTO DBD_CASE_AUDIT_HISTORY
            (CASE_NUMBER, SNAPSHOT_TIMESTAMP, CHANGE_TYPE, CHANGED_COLUMNS,
             OLD_STATE, NEW_STATE, DATA_HASH, IST_TIMESTAMP)
            SELECT CASE_NUMBER, SNAPSHOT_TIMESTAMP, CHANGE_TYPE,
                   PARSE_JSON(CHANGED_COLUMNS_STR), PARSE_JSON(OLD_STATE_STR),
                   PARSE_JSON(NEW_STATE_STR), DATA_HASH,
                   CONVERT_TIMEZONE('Asia/Kolkata', CURRENT_TIMESTAMP())::TIMESTAMP_NTZ
            FROM {temp_table_name}""")
        conn.commit()
        print(f"✅ Audit Sync: Successfully inserted {len(audit_rows)} records via staging table.")
    except Exception as e:
        conn.rollback()
        print(f"❌ Audit Insert Failed: {e}")
        raise e
    finally:
        try: cur.execute(f"DROP TABLE IF EXISTS {temp_table_name}")
        except: pass
        cur.close()

def apply_filters_and_ranking(
    df, selected_regions=None, selected_owners=None, selected_support_levels=None,
    selected_priorities=None, search_query="", heal_desk_only=False,
):
    """Apply the original dashboard filtering and ranking rules without UI state."""
    owner_region_map = get_owner_region_map()
    regions = sorted(set(owner_region_map.values()) - {"Agent"})
    selected_regions = selected_regions or [ALL_REGIONS_OPTION]
    active_regions = regions if ALL_REGIONS_OPTION in selected_regions else selected_regions
    avail_owners = sorted(o for o, r in owner_region_map.items() if r in active_regions) if active_regions else []
    selected_owners = [owner for owner in (selected_owners or []) if owner in avail_owners]
    selected_support_levels = selected_support_levels or [ALL_SUPPORT_LEVELS_OPTION]
    selected_priorities = selected_priorities or [ALL_PRIORITY_OPTION]
    
    # 🔍 Apply Case Number Search Filter FIRST (before other filters)
    search_terms = []
    if search_query:
        search_terms = [term.strip() for term in search_query.split(",") if term.strip()]
    
    if search_terms:
        # Filter the original df first by search terms
        mask = pd.Series(False, index=df.index)
        for term in search_terms:
            mask = mask | df["Case Number"].astype(str).str.contains(term, case=False, na=False)
        df = df[mask].copy()
        
    # 🎯 FIX: APPLY REGION FILTER ALWAYS (Moved outside the `if search_terms:` block)
    if active_regions:
        df = df[df["Region"].isin(active_regions)].copy()
        
    if not active_regions: 
        return df.iloc[:0], [], search_query, heal_desk_only
    
    filtered = df[df["Case Owner"].isin(selected_owners)] if selected_owners else df

    if selected_support_levels and ALL_SUPPORT_LEVELS_OPTION not in selected_support_levels:
        filtered = filtered[
            filtered["Support Level"].astype(str).str.strip().isin(selected_support_levels)
        ].copy()
    
    # 🎯 Apply Heal Desk Filter
    if heal_desk_only:
        filtered = filtered[filtered["Is_Heal_Desk"] == True].copy()
    
    # 🎯 Apply Prioritization ONLY if no specific case search is active.
    if selected_priorities and not search_query:
        filtered = filtered.sort_values(by=["Case Score", "SLA_Minutes"], ascending=[False, True]).reset_index(drop=True)
        if ALL_PRIORITY_OPTION in selected_priorities:
            filtered["Sequential_Rank"] = range(1, len(filtered) + 1)
        else:
            rows_to_keep = []
            if "Need Immediate Attention" in selected_priorities: rows_to_keep.extend(range(0, min(25, len(filtered))))
            if "Need Secondary Attention" in selected_priorities: rows_to_keep.extend(range(25, min(50, len(filtered))))
            rows_to_keep = sorted(set(rows_to_keep))
            filtered = filtered.iloc[rows_to_keep].reset_index(drop=True)
            filtered["Sequential_Rank"] = [i + 1 for i in rows_to_keep] if len(selected_priorities) == 2 else range(1, len(filtered) + 1)
    elif not filtered.empty:
        filtered = filtered.sort_values(by=["Case Owner", "Case Score"], ascending=[True, False])
        filtered["Sequential_Rank"] = filtered.groupby("Case Owner").cumcount() + 1

    # Re-rank after all filters if search was applied
    if search_terms and not filtered.empty:
        filtered = filtered.reset_index(drop=True)
        filtered["Sequential_Rank"] = range(1, len(filtered) + 1)
            
    return filtered, selected_owners if selected_owners else avail_owners, search_query, heal_desk_only
