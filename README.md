# GCS Prioritization Index

Streamlit dashboard for prioritizing open Salesforce support cases. The app pulls active cases from Salesforce, calculates priority and SLA information, reads AI sentiment from Snowflake, writes audit snapshots and SLA breach impact snapshots to Snowflake, and runs background pipelines that update Snowflake on a schedule.

## What This App Does

- Pulls Salesforce cases with status `New`, `Open`, or `Assigned` for owners configured in Snowflake table `DBD_OWNER_DATA`.
- Calculates a case priority score from severity, support tier, escalation state, SLA state, SEV1 flags, and sentiment.
- Displays the priority table with region, owner, customer, SLA, sentiment, and ranking fields.
- Supports dashboard filters for region, owner, prioritization tier, case-number search, and Heal Desk cases.
- Shows a weightage meter for visible cases.
- Shows ongoing SLA breach trends by support tier.
- Reads AI sentiment from Snowflake table `DBD_SENTIMENT_DATA`.
- Writes case audit snapshots into Snowflake table `DBD_CASE_AUDIT_HISTORY`.
- Writes active SLA breach details and SLA reduction impact rows into Snowflake table `DBD_SLA_BREACH_IMPACT`.
- Runs a background sentiment pipeline from `case_analysis/pages/Sentiment_analysis.py`.
- Runs a background SLA breach impact sync every day at `6 PM IST`.

## Project Structure

```text
.
├── README.md
├── requirements.txt
├── .env
├── .env.local
├── case_analysis
│   ├── main.py
│   ├── pages
│   │   ├── CasePriorityIndex.py
│   │   ├── WeightageMeter.py
│   │   ├── OngoingSLABreaches.py
│   │   └── Sentiment_analysis.py
│   ├── archive
│   │   └── Reporttopleft.py
│   ├── services
│   │   ├── case_service.py
│   │   ├── snowflake_service.py
│   │   ├── openai_service.py
│   │   ├── geminiai_service.py
│   │   └── googlesheet_service.py
│   └── config
│       ├── settings.py
│       └── delinea_loader.py
└── venv
```

## Main Entry Point

The app entry point is:

```text
case_analysis/main.py
```

This is a Streamlit app. Do not run it with:

```bash
python case_analysis/main.py
```

Run it with Streamlit:

```bash
python3 -m streamlit run case_analysis/main.py --server.fileWatcherType none
```

If you want to use the virtualenv Python directly:

```bash
venv/bin/python -m streamlit run case_analysis/main.py --server.fileWatcherType none
```

If port `8501` is already in use:

```bash
python3 -m streamlit run case_analysis/main.py --server.fileWatcherType none --server.port 8505
```

Then open:

```text
http://localhost:8501
```

or the custom port you selected.

## Local Setup

Create and activate a virtual environment:

```bash
cd /Users/vr/Documents/Automation/v
python3 -m venv venv
source venv/bin/activate
```

Install dependencies:

```bash
python3 -m pip install -r requirements.txt
```

Run the app:

```bash
python3 -m streamlit run case_analysis/main.py --server.fileWatcherType none
```

The `--server.fileWatcherType none` flag avoids macOS watchdog/FSEvents startup failures such as:

```text
Cannot start fsevents stream. Use a kqueue or polling observer instead.
```

## Credentials

The app supports two credential sources:

1. Delinea Secret Server
2. Local `.env` fallback

Delinea is attempted first for Salesforce, Snowflake, and OpenAI. If Delinea does not return usable credentials, the app falls back to local environment variables.

Never commit `.env`, `.env.local`, client secrets, private keys, or credential JSON files.

## Delinea Credential Loading

Delinea logic is implemented in:

```text
case_analysis/config/delinea_loader.py
```

It uses:

```text
DELINEA_CLIENT_ID
DELINEA_CLIENT_SECRET
DELINEA_CLIENT_SECRET_FILE
```

Default Delinea client ID:

```text
agenticsupportsa1@xactlycorp.com
```

Default client-secret file path:

```text
~/.config/xactly_support/delinea_client_secret
```

Token cache:

```text
/tmp/delinea_token_shared.json
```

Delinea fetches these shared secrets:

```text
Agentic Support Salesforce Account
Agentic Support Snowflake Account
Agentic Support API Key
```

The loader returns:

- Salesforce username, password, and optional security token.
- Snowflake account, user, and password.
- OpenAI API key.

## Environment Variables

These variables are used when Delinea is unavailable or when non-secret defaults are still needed.

Salesforce:

```text
SALESFORCE_USERNAME
SALESFORCE_COMBINED
SALESFORCE_SECURITY_TOKEN
SALESFORCE_DOMAIN
```

`SALESFORCE_COMBINED` supports the older format where password and security token are stored together. If it is at least 24 characters, the code treats the last 24 characters as the Salesforce security token.

Snowflake:

```text
SNOWFLAKE_USER
SNOWFLAKE_PASSWORD
SNOWFLAKE_ACCOUNT
SNOWFLAKE_WAREHOUSE
SNOWFLAKE_DATABASE
SNOWFLAKE_SCHEMA
```

Defaults used by the app:

```text
SNOWFLAKE_WAREHOUSE=CS_BOT_WH
SNOWFLAKE_DATABASE=CUSTOMER_SUPPORT_BOT_LOGS
SNOWFLAKE_SCHEMA=CHAT_DATA
```

OpenAI:

```text
OPENAI_API_KEY
```

Other currently loaded settings:

```text
GEMINI_API_KEY
APTEDGE_API_KEY
APTEDGE_BASE_URL
APTEDGE_MODEL
```

## Example `.env`

Use placeholder values only. Do not commit real credentials.

```env
SALESFORCE_USERNAME=your_salesforce_user
SALESFORCE_COMBINED=your_password_plus_token
SALESFORCE_DOMAIN=login

SNOWFLAKE_USER=your_snowflake_user
SNOWFLAKE_PASSWORD=your_snowflake_password
SNOWFLAKE_ACCOUNT=your_snowflake_account
SNOWFLAKE_WAREHOUSE=CS_BOT_WH
SNOWFLAKE_DATABASE=CUSTOMER_SUPPORT_BOT_LOGS
SNOWFLAKE_SCHEMA=CHAT_DATA

OPENAI_API_KEY=your_openai_key
```

## Salesforce Case Pull

The main case pull happens in:

```text
case_analysis/pages/CasePriorityIndex.py
```

Function:

```text
fetch_cases()
```

The dashboard query pulls:

- Case ID
- Case number
- Subject
- Status
- Owner name
- Account name
- Account lookup field
- Support level
- Severity
- SEV1 flag
- Escalation flag
- Created and closed dates
- Due Date field, when present in Salesforce
- Heal Desk flag
- Published case comments

The query filters cases by:

```sql
Status IN ('New', 'Open', 'Assigned')
AND Owner.Name IN (...)
```

The owner list and region mapping come from Snowflake table `DBD_OWNER_DATA`, not from hardcoded Python lists.

Expected table shape:

```text
DBD_OWNER_DATA
├── id
├── name
└── region
```

Owner config is loaded in `fetch_owner_config()`:

```sql
SELECT name, COALESCE(region, 'UNKNOWN') AS region
FROM DBD_OWNER_DATA
WHERE name IS NOT NULL
ORDER BY id, name
```

The returned mapping is used for:

- Salesforce `Owner.Name IN (...)` filters.
- Dashboard `Region` column.
- Region dropdown.
- Owner dropdown.
- Detecting whether a latest comment was made by a support owner.

The same owner table is used by:

- `case_analysis/pages/CasePriorityIndex.py`
- `case_analysis/pages/Sentiment_analysis.py`
- `case_analysis/pages/OngoingSLABreaches.py`

## Heal Desk Cases

Heal Desk cases are not pulled with a separate query.

The main Salesforce query includes:

```sql
Heal_Desk__c
```

Each case is converted into:

```python
Is_Heal_Desk = bool(case.get("Heal_Desk__c"))
```

The Streamlit toggle filters already-loaded rows:

```python
filtered = filtered[filtered["Is_Heal_Desk"] == True].copy()
```

This means:

- All matching open cases are fetched first.
- Heal Desk filtering happens inside the dashboard.
- There is no Salesforce `AND Heal_Desk__c = true` condition in the main query.

## Priority Scoring

Priority scoring is implemented in:

```text
calculate_score()
```

Inputs:

- `sevone`
- `severity`
- `support_level`
- `escalated`
- `sentiment`
- `sla_mins`

High-level scoring rules:

- SEV1 flag gets the highest score.
- Escalated cases are prioritized next.
- Severity is normalized to `S1`, `S2`, `S3`, or `S4`.
- Premium and Plus support levels get different weighting.
- Negative or critical sentiment increases priority.
- Overdue SLA state affects the score.

The final score is stored as:

```text
Case Score
```

`Case Score` keeps the decimal overdue bonus for ranking. The Weightage Meter uses `Case Score Display`, which removes those decimal-only overdue bonus points from the visible total.

## SLA Logic

SLA functions live in:

```text
case_analysis/pages/CasePriorityIndex.py
```

Key functions:

```text
get_sla_hours()
calculate_sla_deadline()
calculate_sla_variance()
get_standard_business_minutes()
add_sla_hours_with_weekend_skip()
get_breach_shift()
```

Important behavior:

- SLA duration depends on severity and support level.
- Standard support skips the configured weekend window.
- Premium support uses raw elapsed time.
- SLA deadline is calculated from the latest meaningful support response, last customer comment, or case created date.
- Generic support comments can be ignored for SLA start logic.
- Breach shift is derived from the SLA deadline hour in IST.
- If Salesforce has a non-empty Due Date field, SLA start is gated until the next day at `06:00 IST`. Example: Due Date `02 October` starts SLA from `03 October 06:00 IST`.
- For Standard support, the Due Date gate can land in the weekend window, but SLA time does not burn during the weekend. Example: Friday Due Date starts at Saturday `06:00 IST`; S4 Standard still has 8 SLA hours and reaches deadline on Monday after weekend pause.
- If the gated SLA start is still in the future, the displayed `Due in` time uses real calendar time until the SLA deadline, so it can show values such as `2d 3h 15m` instead of only the remaining SLA business hours.

Due Date field detection checks common API names and the Salesforce field label:

```text
Due_Date__c
DueDate__c
Due_Date_Time__c
DueDateTime__c
DueDate
Field label: Due Date
```

The Due Date gate is applied in:

- `case_analysis/pages/CasePriorityIndex.py`
- `case_analysis/pages/OngoingSLABreaches.py`

## AI Sentiment Pipeline

Sentiment logic is implemented in:

```text
case_analysis/pages/Sentiment_analysis.py
```

The pipeline:

1. Pulls active Salesforce cases.
2. Reads up to the latest 10 published comments.
3. Builds a sentiment prompt.
4. Calls OpenAI.
5. Upserts results into Snowflake table `DBD_SENTIMENT_DATA`.

The OpenAI call uses Chat Completions:

```python
openai_client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[{"role": "user", "content": prompt}],
    temperature=0
)
```

It does not currently use the Responses API:

```python
openai_client.responses.create(...)
```

Expected model output:

```text
Positive
Neutral
Negative
Critical
```

The dashboard reads sentiment from Snowflake:

```sql
SELECT CaseNumber, Sentiment FROM DBD_SENTIMENT_DATA
```

## Background Scheduler

The sentiment scheduler is in:

```text
case_analysis/main.py
```

Current values:

```python
INITIAL_DELAY_MINUTES = 0.5
INTERVAL_MINUTES = 60
```

Behavior:

- Starts once per Streamlit session.
- Waits `INITIAL_DELAY_MINUTES`.
- Loads `case_analysis/pages/Sentiment_analysis.py`.
- Calls its `main()` function.
- Repeats every `INTERVAL_MINUTES`.

The scheduler runs in a daemon thread, so it stops when the Streamlit process stops.

## SLA Breach Impact Sync

SLA breach impact sync is implemented in:

```text
case_analysis/pages/OngoingSLABreaches.py
```

It is started from:

```text
case_analysis/main.py
```

Current behavior:

```python
SLA_IMPACT_RUN_HOUR_IST = 18
```

This means the app runs SLA breach impact sync every day at `6 PM IST` while the Streamlit process is running.

The sync uses the same source data shown under:

```text
View x Breached Case Details
```

It writes two record types into `DBD_SLA_BREACH_IMPACT`:

- `ACTIVE_BREACH`: current active overdue rows from the breach-detail view.
- `DAILY_IMPACT`: impact rows for cases that were previously active overdue and have now improved.

Impact status values:

```text
MOVED_TO_DUE_IN
STATUS_EXITED_ACTIVE
```

Impact rules:

- `MOVED_TO_DUE_IN`: a previously overdue case is now calculated as `Due in`.
- `STATUS_EXITED_ACTIVE`: a previously overdue case is no longer in Salesforce status `New`, `Open`, or `Assigned`.

The sync uses Snowflake `MERGE`, so reruns update/upsert the same case/date/impact type instead of continuously appending duplicates.

## Snowflake Tables

Owner config table:

```text
DBD_OWNER_DATA
```

Expected columns:

```text
id
name
region
```

This table controls which Salesforce owners are queried and how each owner maps to a dashboard region.

Sentiment table:

```text
DBD_SENTIMENT_DATA
```

Expected columns:

```text
CaseNumber
Sentiment
```

Audit table:

```text
DBD_CASE_AUDIT_HISTORY
```

Created automatically if missing:

```text
AUDIT_ID
CASE_NUMBER
SNAPSHOT_TIMESTAMP
CHANGE_TYPE
CHANGED_COLUMNS
OLD_STATE
NEW_STATE
DATA_HASH
```

The audit table retention is configured to 2 days:

```sql
ALTER TABLE DBD_CASE_AUDIT_HISTORY SET DATA_RETENTION_TIME_IN_DAYS = 2
```

SLA breach impact table:

```text
DBD_SLA_BREACH_IMPACT
```

Create it manually in Snowflake:

```sql
CREATE TABLE IF NOT EXISTS DBD_SLA_BREACH_IMPACT (
    SLA_IMPACT_ID STRING DEFAULT UUID_STRING(),
    RECORD_TYPE STRING NOT NULL,
    SNAPSHOT_DATE DATE NOT NULL,
    SNAPSHOT_TIMESTAMP TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),

    CASE_NUMBER STRING NOT NULL,
    CUSTOMER_NAME STRING,
    CASE_OWNER STRING,
    SEVERITY STRING,
    SUPPORT_LEVEL STRING,
    SUPPORT_TIER STRING,
    SALESFORCE_STATUS STRING,

    SLA_STATUS STRING,
    SLA_DEADLINE STRING,
    LAST_CUSTOMER_COMMENT STRING,
    SLA_VARIANCE_MINS NUMBER,
    BREACH_MONTH STRING,
    IS_HEAL_DESK BOOLEAN,
    SUBJECT STRING,

    IMPACT_STATUS STRING,
    IMPACT_REASON STRING,
    PREVIOUS_SLA_STATUS STRING,
    CURRENT_SLA_STATUS STRING,

    CREATED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);
```

Daily impact summary query:

```sql

SELECT
    d.SNAPSHOT_DATE,
    COUNT_IF(d.IMPACT_STATUS = 'MOVED_TO_DUE_IN') AS BACK_TO_SLA_COMPLIANCE,
    COUNT_IF(d.IMPACT_STATUS = 'STATUS_EXITED_ACTIVE') AS CURRENTLY_OUT_OF_SCOPE_SUPPORT,
    COUNT(*) AS TOTAL_IMPACT_COUNT,
    t.TOTAL_RECORDS_FOR_DATE,
    (TOTAL_IMPACT_COUNT/t.TOTAL_RECORDS_FOR_DATE) * 100 as Percentage
FROM DBD_SLA_BREACH_IMPACT d
JOIN (
    SELECT
        SNAPSHOT_DATE,
        COUNT(*) AS TOTAL_RECORDS_FOR_DATE
    FROM DBD_SLA_BREACH_IMPACT
    GROUP BY SNAPSHOT_DATE
) t
    ON d.SNAPSHOT_DATE = t.SNAPSHOT_DATE
WHERE d.RECORD_TYPE = 'DAILY_IMPACT'
GROUP BY d.SNAPSHOT_DATE, t.TOTAL_RECORDS_FOR_DATE
ORDER BY d.SNAPSHOT_DATE ASC;

```

Active breach snapshot query:

```sql
SELECT
    SNAPSHOT_DATE,
    COUNT(DISTINCT CASE_NUMBER) AS ACTIVE_BREACH_COUNT
FROM DBD_SLA_BREACH_IMPACT
WHERE RECORD_TYPE = 'ACTIVE_BREACH'
GROUP BY SNAPSHOT_DATE
ORDER BY SNAPSHOT_DATE DESC;
```

## Dashboard Filters

Filters are implemented in:

```text
apply_filters_and_ranking()
```

Available filters:

- Region
- Owner
- Prioritization
- Case-number search
- Heal Desk only

Prioritization filters:

```text
Need Immediate Attention
Need Secondary Attention
```

When prioritization is selected and there is no specific case search:

- Immediate attention keeps rank 1 through 25.
- Secondary attention keeps rank 26 through 50.

When case search is active, prioritization slicing is skipped and matching cases are re-ranked from 1.

## Charts

Weightage meter:

```text
case_analysis/pages/WeightageMeter.py
```

This chart sums `Case Score` for currently visible cases.

SLA breach chart:

```text
case_analysis/pages/OngoingSLABreaches.py
```

This chart:

- Pulls active Salesforce cases.
- Recalculates SLA breach state.
- Groups breached cases by month and support tier.
- Applies owner, search, and Heal Desk filters from the main dashboard.
- Provides the breach-detail rows used by the SLA breach impact Snowflake sync.

## Running Sentiment Pipeline Manually

You can run the sentiment pipeline outside the dashboard:

```bash
cd /Users/vr/Documents/Automation/v
source venv/bin/activate
python3 -m case_analysis.pages.Sentiment_analysis
```

This requires working Salesforce, OpenAI, and Snowflake credentials.

## Common Commands

Activate virtualenv:

```bash
source venv/bin/activate
```

Install dependencies:

```bash
python3 -m pip install -r requirements.txt
```

Run app:

```bash
python3 -m streamlit run case_analysis/main.py --server.fileWatcherType none
```

Run app on a specific port:

```bash
python3 -m streamlit run case_analysis/main.py --server.fileWatcherType none --server.port 8505
```

Check installed packages:

```bash
python3 -m pip check
```

## Troubleshooting

### `zsh: command not found: python`

Use `python3`:

```bash
python3 -m streamlit run case_analysis/main.py --server.fileWatcherType none
```

or call the venv binary:

```bash
venv/bin/python -m streamlit run case_analysis/main.py --server.fileWatcherType none
```

### `missing ScriptRunContext`

This happens when a Streamlit app is run as a normal Python script.

Wrong:

```bash
python3 case_analysis/main.py
```

Correct:

```bash
python3 -m streamlit run case_analysis/main.py --server.fileWatcherType none
```

### `Cannot start fsevents stream`

Run with file watching disabled:

```bash
python3 -m streamlit run case_analysis/main.py --server.fileWatcherType none
```

### `ModuleNotFoundError`

Install dependencies:

```bash
python3 -m pip install -r requirements.txt
```

Then verify:

```bash
python3 -m pip check
```

### Salesforce Credential Errors

Check:

- Delinea client secret is available.
- `DELINEA_CLIENT_SECRET` or `DELINEA_CLIENT_SECRET_FILE` is configured.
- Salesforce fallback variables exist in `.env`.
- `SALESFORCE_DOMAIN` is set to the expected domain, usually `login`.

### Snowflake Credential Errors

Check:

- Delinea Snowflake secret is accessible.
- Fallback variables exist in `.env`.
- Warehouse, database, and schema are correct.
- User has access to `DBD_OWNER_DATA`, `DBD_SENTIMENT_DATA`, `DBD_CASE_AUDIT_HISTORY`, and `DBD_SLA_BREACH_IMPACT`.

### OpenAI Sentiment Errors

Check:

- Delinea OpenAI API key secret is accessible.
- `OPENAI_API_KEY` exists in `.env` if Delinea is unavailable.
- The app can reach the OpenAI API.
- The model name `gpt-4o-mini` is available for the configured key.

## Security Notes

- `.env`, `.env.local`, and credential files are ignored by git.
- Do not print secrets in logs.
- Do not commit Delinea client secret files.
- Do not commit Snowflake, Salesforce, or OpenAI credentials.
- Prefer Delinea for shared service-account credentials.

## Current Known Implementation Notes

- Salesforce owner names and regions are loaded from `DBD_OWNER_DATA`.
- `case_analysis/archive/Reporttopleft.py` is archived legacy code and is not imported by the active app.
- Due Date SLA gating starts SLA the next day at `06:00 IST`.
- Sentiment uses Chat Completions, not the Responses API.
- The dashboard reads sentiment from Snowflake; it does not call OpenAI directly.
- The sentiment scheduler runs per Streamlit session.
- SLA breach impact sync runs daily at `6 PM IST`.
- Heal Desk filtering is applied after cases are pulled from Salesforce.
- Some Streamlit APIs use `use_container_width`, which Streamlit warns will be replaced by `width` in newer versions.
