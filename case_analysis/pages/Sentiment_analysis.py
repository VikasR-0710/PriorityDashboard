"""
AI Sentiment Analysis & Snowflake Ingestion Pipeline
----------------------------------------------------
Fetches open Salesforce cases, analyzes them using OpenAI, 
and UPSERTS sentiment results into Snowflake table DBD_SENTIMENT_DATA.
"""
import os
import time
from datetime import datetime, timezone
import snowflake.connector
from case_analysis.services.case_service import CaseService
from case_analysis.services.openai_service import OpenAIService

# -------------------------------------------------------
# 🛠️ CONFIGURATION (Environment Variables)
# -------------------------------------------------------
SNOWFLAKE_USER = os.getenv("SNOWFLAKE_USER")
SNOWFLAKE_PASSWORD = os.getenv("SNOWFLAKE_PASSWORD")
SNOWFLAKE_ACCOUNT = os.getenv("SNOWFLAKE_ACCOUNT")
SNOWFLAKE_WAREHOUSE = os.getenv("SNOWFLAKE_WAREHOUSE", "GENERALBIZ_WAREHOUSE")
SNOWFLAKE_DATABASE = os.getenv("SNOWFLAKE_DATABASE", "CUSTOMER_SUPPORT_BOT_LOGS")
SNOWFLAKE_SCHEMA = os.getenv("SNOWFLAKE_SCHEMA", "CHAT_DATA")
TARGET_TABLE = "DBD_SENTIMENT_DATA"
OPENAI_DELAY = 0.5

# -------------------------------------------------------
# 📊 SNOWFLAKE HELPERS
# -------------------------------------------------------
def get_snowflake_connection():
    if not all([SNOWFLAKE_USER, SNOWFLAKE_PASSWORD, SNOWFLAKE_ACCOUNT]):
        raise EnvironmentError("Missing Snowflake environment variables.")
    return snowflake.connector.connect(
        user=SNOWFLAKE_USER, password=SNOWFLAKE_PASSWORD, account=SNOWFLAKE_ACCOUNT,
        warehouse=SNOWFLAKE_WAREHOUSE, database=SNOWFLAKE_DATABASE, schema=SNOWFLAKE_SCHEMA
    )

def upsert_to_snowflake(data):
    if not data:
        print("⚠️ No data to upsert.")
        return
    print("🔌 Connecting to Snowflake...")
    conn = get_snowflake_connection()
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

def fetch_salesforce_cases():
    print("🔌 Connecting to Salesforce...")
    service = CaseService()
    sf = service.get_connection()
    query = """
        SELECT Id, CaseNumber, Subject, Status, Owner.Name, Account.Name, 
            Severity__c, Support_Level__c, IsEscalated,
            (select CommentBody, CreatedBy.Name, CreatedDate from CaseComments where IsPublished=true order by CreatedDate Desc)
        FROM Case
        WHERE Status IN ('New', 'Open', 'Assigned') and Owner.Name IN (
            'Amit Bhojak', 'Amit Kumar', 'Amith Gujjar', 'Aniket Chinde', 'Aqsa Pandith', 'Becca Lozano',
            'Chethan Kumara P', 'Ganesh Babu', 'Gnanasiri Pechetti', 'Imari Killikelly', 'Infant Raj.', 
            'Ishaq Mathina', 'Kalyan Kumar', 'Karalie Murray', 'Karthik Dosapati', 'Kaushik Patowary', 
            'Mahesh P M', 'Merlyn Pushparaj', 'Mohamed Ramzin', 'Mohammad Raza', 'Mohammed Usman', 
            'Monika Sihag', 'Mugilan Gowthaman', 'Naveen Kumar Surisetti', 'Nilanjan Roy', 'Nupur Rao', 
            'Palak Kharche', 'Pallavi M R', 'Payal Gupta', 'Peter Kyller', 'Pooja Singh', 'Poonam Pandey',
            'Prabu Rajendran', 'Prabu R', 'Rohit Nargundkar', 'Sakthi Devi SK', 'Sanjay Kademani',
            'Chandra Sai Surya Santosh Veduruvada', 'Santi Sahoo', 'Selvin Raja', 'Shahrukh Shahzad', 
            'Shakti Prasad Pati', 'Shreyas G Nambiar', 'Shivendra Yadav', 'Sindhu M Y', 
            'Sivagnana Bharathi Nagaraj', 'Sivaji Koya', 'Srinivas Aaguri', 'Sumit Paul', 'Sumit', 
            'Sushmitha Rayalkeri', 'Syeda Sajida', 'Tarun Buthala', 'Ullas Shenoy', 'Vikas R', 
            'Vilas Potadar', 'Vipul S G', 'Vishal Mavi', 'Yogesh R', 'Zareena Bano', 'Zareena','Joshua Halle'
        )
    """
    print("📥 Fetching cases...")
    return sf.query_all(query)["records"]

def analyze_sentiment(case_record, openai_client):
    comments_records = (case_record.get("CaseComments") or {}).get("records", [])
    comments_text = " | ".join([f"{c.get('CreatedBy', {}).get('Name', 'Unknown')}: {c.get('CommentBody', '')}" for c in comments_records[:10]]) or "No published comments available."
    case_num = case_record.get("CaseNumber", "UNKNOWN")
    prompt = f"""Analyze this Salesforce support case.
        Case Number: {case_num}
        Subject: {case_record.get("Subject")}
        Recent Comments: {comments_text}
        Return ONLY one word: Positive, Neutral, Negative, or Critical."""
    try:
        response = openai_client.chat.completions.create(model="gpt-4o-mini", messages=[{"role": "user", "content": prompt}], temperature=0)
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"  ⚠️ OpenAI failed for {case_num}: {e}")
        return "Analysis Error"

def prepare_and_upsert(cases, openai_client):
    processed = []
    total = len(cases)
    print(f"🧠 Starting AI analysis for {total} cases...")
    for i, case in enumerate(cases, 1):
        case_num = case.get("CaseNumber", "UNKNOWN")
        print(f"  [{i}/{total}] Analyzing {case_num}...")
        sentiment = analyze_sentiment(case, openai_client)
        processed.append({"CaseNumber": case_num, "Sentiment": sentiment})
        time.sleep(OPENAI_DELAY)
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