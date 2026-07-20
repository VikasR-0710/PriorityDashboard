import streamlit as st
import plotly.graph_objects as go
import pandas as pd
import time
from datetime import datetime, timedelta
import pytz

from pages.CasePriorityIndex import (
    get_sf_connection, get_owner_region_map, build_owner_name_filter, is_generalized_comment,
    get_sla_hours, convert_to_ist_dt, calculate_sla_deadline, calculate_sla_variance,
    get_case_due_date_field, apply_due_date_sla_gate, get_snowflake_connection,
)

SLA_BREACH_IMPACT_TABLE = "DBD_SLA_BREACH_IMPACT"
ACTIVE_CASE_STATUSES = {"New", "Open", "Assigned"}

@st.cache_data(ttl=3600)
def get_all_breach_records():
    sf = get_sf_connection()
    owner_region_map = get_owner_region_map()
    owner_names_str = build_owner_name_filter(owner_region_map.keys())
    due_date_field = get_case_due_date_field()
    due_date_select = f", {due_date_field}" if due_date_field else ""
    
    # UPDATED: Added Heal_Desk__c to the query
    query = f"""SELECT Id, CaseNumber, Subject, Status, Owner.Name, Account.Name, Support_Level__c, Severity__c, CreatedDate, Heal_Desk__c{due_date_select},
               (SELECT CommentBody, CreatedBy.Name, CreatedDate, IsPublished FROM CaseComments WHERE IsPublished=true ORDER BY CreatedDate DESC)
        FROM Case WHERE Owner.Name IN ({owner_names_str})
          AND Status IN ('New', 'Open', 'Assigned') AND Severity__c != null"""
    
    try:
        result = sf.query_all(query)
        records = result["records"]
    except Exception as e:
        print(f"❌ Chart Query Failed: {e}")
        return pd.DataFrame()

    if not records:
        return pd.DataFrame()

    df = pd.json_normalize(records)
    rename_map = {'Owner.Name': 'Case Owner', 'Account.Name': 'Customer Name', 'Support_Level__c': 'Support Level',
        'Severity__c': 'Severity', 'CreatedDate': 'Created Date', 'CaseComments.records': 'Comments', 'Subject': 'Subject'}
    df.rename(columns={k: rename_map[k] for k in rename_map.keys() if k in df.columns}, inplace=True)
    
    df['Support Level'] = df['Support Level'].fillna('Standard')
    df['Severity'] = df['Severity'].fillna('S4')
    df['Case Owner'] = df['Case Owner'].fillna('UNKNOWN')
    df['Customer Name'] = df['Customer Name'].fillna('N/A')
    df['Subject'] = df['Subject'].fillna('')
    df['Support Tier'] = df['Support Level'].apply(lambda s: 'Premium' if pd.notna(s) and any(x in str(s).lower() for x in ['premium','plus','p+']) else 'Standard')
    
    all_breaches = []
    for _, row in df.iterrows():
        try:
            severity = row.get('Severity', 'S4')
            support_level = row.get('Support Level', 'Standard')
            case_owner = row.get('Case Owner', 'UNKNOWN')
            case_number = row.get('CaseNumber', 'N/A')
            customer_name = row.get('Customer Name', 'N/A')
            status = row.get('Status', 'N/A')
            subject = row.get('Subject', '')
            comments = row.get('Comments', [])
            due_date_value = row.get(due_date_field) if due_date_field else None
            
            last_customer_comment_dt = None
            if comments and isinstance(comments, list):
                for comment in comments:
                    if isinstance(comment, dict) and isinstance(comment.get('CreatedBy'), dict) and comment['CreatedBy'].get('Name') == 'Customer Support User':
                        last_customer_comment_dt = convert_to_ist_dt(comment.get('CreatedDate'))
                        break

            sla_start_dt = None
            if comments and isinstance(comments, list):
                latest = comments[0]
                latest_author = (latest.get('CreatedBy') or {}).get('Name', '')
                
                latest_is_support = latest_author in owner_region_map
                latest_is_gen = is_generalized_comment(latest.get('CommentBody', ''))
                
                if latest_is_support and not latest_is_gen:
                    sla_start_dt = convert_to_ist_dt(latest.get('CreatedDate'))

            effective_start_dt = sla_start_dt if sla_start_dt else last_customer_comment_dt
            effective_start_dt = apply_due_date_sla_gate(effective_start_dt, due_date_value, support_level)
            if effective_start_dt is None:
                created_date = row.get('Created Date')
                if created_date: effective_start_dt = convert_to_ist_dt(created_date)
                effective_start_dt = apply_due_date_sla_gate(effective_start_dt, due_date_value, support_level)

            sla_hours = get_sla_hours(severity, support_level)
            if not sla_hours: continue
            
            sla_deadline_dt = calculate_sla_deadline(effective_start_dt, sla_hours, support_level)
            
            # UPDATED: Pass support_level to trigger the weekend pause logic!
            sla_text, sla_mins = calculate_sla_variance(sla_deadline_dt, support_level, effective_start_dt)
            is_breached = isinstance(sla_mins, (int, float)) and sla_mins < 0
            
            if is_breached:
                sla_deadline_str = sla_deadline_dt.strftime("%d-%b %H:%M") if sla_deadline_dt else "N/A"
                lcc_str = last_customer_comment_dt.strftime("%d-%b %H:%M") if last_customer_comment_dt else "N/A"
                ist = pytz.timezone('Asia/Kolkata')
                breach_month = pd.to_datetime(row['Created Date']).strftime('%Y-%m') if row['Created Date'] else datetime.now(ist).strftime('%Y-%m')
                
                all_breaches.append({
                    'Case Number': case_number, 'Customer Name': customer_name, 'Case Owner': case_owner,
                    'Support Level': support_level, 'Support Tier': df.loc[row.name, 'Support Tier'],
                    'Severity': severity, 'Subject': subject[:80] + '...' if len(subject) > 80 else subject,
                    'Last Customer Comment': lcc_str, 'SLA Deadline': sla_deadline_str,
                    'SLA Variance (mins)': int(sla_mins),
                    'SLA Status': f"🚨 Overdue: {sla_text.split(': ')[1] if ': ' in sla_text else sla_text}",
                    'Breach_Month': breach_month,
                    'Salesforce Status': status,
                    'Is_Heal_Desk': bool(row.get('Heal_Desk__c')) # Added Heal Desk flag
                })
        except Exception as e:
            print(f"⚠️ Chart SLA Calc Error: {e}")
            continue
            
    return pd.DataFrame(all_breaches) if all_breaches else pd.DataFrame()

def _clean_snowflake_value(value):
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    if hasattr(value, "item"):
        return value.item()
    if isinstance(value, (bool, int, float, str)):
        return value
    return str(value)

def _build_breach_rows(breaches_df, record_type, impact_status, impact_reason, now_ist):
    rows = []
    if breaches_df is None or breaches_df.empty:
        return rows

    for row in breaches_df.to_dict(orient="records"):
        rows.append((
            record_type,
            now_ist.date(),
            now_ist.replace(tzinfo=None),
            _clean_snowflake_value(row.get("Case Number")),
            _clean_snowflake_value(row.get("Customer Name")),
            _clean_snowflake_value(row.get("Case Owner")),
            _clean_snowflake_value(row.get("Severity")),
            _clean_snowflake_value(row.get("Support Level")),
            _clean_snowflake_value(row.get("Support Tier")),
            _clean_snowflake_value(row.get("Salesforce Status")),
            _clean_snowflake_value(row.get("SLA Status")),
            _clean_snowflake_value(row.get("SLA Deadline")),
            _clean_snowflake_value(row.get("Last Customer Comment")),
            _clean_snowflake_value(row.get("SLA Variance (mins)")),
            _clean_snowflake_value(row.get("Breach_Month")),
            _clean_snowflake_value(row.get("Is_Heal_Desk")),
            _clean_snowflake_value(row.get("Subject")),
            impact_status,
            impact_reason,
            None,
            None,
        ))
    return rows

def _dedupe_sla_breach_rows(rows):
    deduped = {}
    for row in rows:
        key = (row[0], row[1], row[3], row[17] or "")
        deduped[key] = row
    return list(deduped.values())

def _merge_sla_breach_rows(conn, rows):
    rows = _dedupe_sla_breach_rows(rows)
    if not rows:
        return 0

    cur = conn.cursor()
    temp_table_name = "TEMP_SLA_BREACH_IMPACT_" + str(int(time.time()))
    try:
        cur.execute(f"""
            CREATE OR REPLACE TEMPORARY TABLE {temp_table_name} (
                RECORD_TYPE STRING, SNAPSHOT_DATE DATE, SNAPSHOT_TIMESTAMP TIMESTAMP_NTZ,
                CASE_NUMBER STRING, CUSTOMER_NAME STRING, CASE_OWNER STRING, SEVERITY STRING,
                SUPPORT_LEVEL STRING, SUPPORT_TIER STRING, SALESFORCE_STATUS STRING,
                SLA_STATUS STRING, SLA_DEADLINE STRING, LAST_CUSTOMER_COMMENT STRING,
                SLA_VARIANCE_MINS NUMBER, BREACH_MONTH STRING, IS_HEAL_DESK BOOLEAN,
                SUBJECT STRING, IMPACT_STATUS STRING, IMPACT_REASON STRING,
                PREVIOUS_SLA_STATUS STRING, CURRENT_SLA_STATUS STRING
            )
        """)
        cur.executemany(
            f"""
            INSERT INTO {temp_table_name} (
                RECORD_TYPE, SNAPSHOT_DATE, SNAPSHOT_TIMESTAMP, CASE_NUMBER, CUSTOMER_NAME,
                CASE_OWNER, SEVERITY, SUPPORT_LEVEL, SUPPORT_TIER, SALESFORCE_STATUS,
                SLA_STATUS, SLA_DEADLINE, LAST_CUSTOMER_COMMENT, SLA_VARIANCE_MINS,
                BREACH_MONTH, IS_HEAL_DESK, SUBJECT, IMPACT_STATUS, IMPACT_REASON,
                PREVIOUS_SLA_STATUS, CURRENT_SLA_STATUS
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            rows
        )
        cur.execute(f"""
            MERGE INTO {SLA_BREACH_IMPACT_TABLE} target
            USING {temp_table_name} source
            ON target.RECORD_TYPE = source.RECORD_TYPE
               AND target.SNAPSHOT_DATE = source.SNAPSHOT_DATE
               AND target.CASE_NUMBER = source.CASE_NUMBER
               AND NVL(target.IMPACT_STATUS, '') = NVL(source.IMPACT_STATUS, '')
            WHEN MATCHED THEN UPDATE SET
                SNAPSHOT_TIMESTAMP = source.SNAPSHOT_TIMESTAMP,
                CUSTOMER_NAME = source.CUSTOMER_NAME,
                CASE_OWNER = source.CASE_OWNER,
                SEVERITY = source.SEVERITY,
                SUPPORT_LEVEL = source.SUPPORT_LEVEL,
                SUPPORT_TIER = source.SUPPORT_TIER,
                SALESFORCE_STATUS = source.SALESFORCE_STATUS,
                SLA_STATUS = source.SLA_STATUS,
                SLA_DEADLINE = source.SLA_DEADLINE,
                LAST_CUSTOMER_COMMENT = source.LAST_CUSTOMER_COMMENT,
                SLA_VARIANCE_MINS = source.SLA_VARIANCE_MINS,
                BREACH_MONTH = source.BREACH_MONTH,
                IS_HEAL_DESK = source.IS_HEAL_DESK,
                SUBJECT = source.SUBJECT,
                IMPACT_REASON = source.IMPACT_REASON,
                PREVIOUS_SLA_STATUS = source.PREVIOUS_SLA_STATUS,
                CURRENT_SLA_STATUS = source.CURRENT_SLA_STATUS,
                IST_TIMESTAMP = CONVERT_TIMEZONE('Asia/Kolkata', CURRENT_TIMESTAMP())::TIMESTAMP_NTZ
            WHEN NOT MATCHED THEN INSERT (
                RECORD_TYPE, SNAPSHOT_DATE, SNAPSHOT_TIMESTAMP, CASE_NUMBER, CUSTOMER_NAME,
                CASE_OWNER, SEVERITY, SUPPORT_LEVEL, SUPPORT_TIER, SALESFORCE_STATUS,
                SLA_STATUS, SLA_DEADLINE, LAST_CUSTOMER_COMMENT, SLA_VARIANCE_MINS,
                BREACH_MONTH, IS_HEAL_DESK, SUBJECT, IMPACT_STATUS, IMPACT_REASON,
                PREVIOUS_SLA_STATUS, CURRENT_SLA_STATUS, IST_TIMESTAMP
            ) VALUES (
                source.RECORD_TYPE, source.SNAPSHOT_DATE, source.SNAPSHOT_TIMESTAMP,
                source.CASE_NUMBER, source.CUSTOMER_NAME, source.CASE_OWNER,
                source.SEVERITY, source.SUPPORT_LEVEL, source.SUPPORT_TIER,
                source.SALESFORCE_STATUS, source.SLA_STATUS, source.SLA_DEADLINE,
                source.LAST_CUSTOMER_COMMENT, source.SLA_VARIANCE_MINS,
                source.BREACH_MONTH, source.IS_HEAL_DESK, source.SUBJECT,
                source.IMPACT_STATUS, source.IMPACT_REASON,
                source.PREVIOUS_SLA_STATUS, source.CURRENT_SLA_STATUS,
                CONVERT_TIMEZONE('Asia/Kolkata', CURRENT_TIMESTAMP())::TIMESTAMP_NTZ
            )
        """)
        conn.commit()
        return len(rows)
    except Exception:
        conn.rollback()
        raise
    finally:
        try:
            cur.execute(f"DROP TABLE IF EXISTS {temp_table_name}")
        except Exception:
            pass
        cur.close()

def _get_latest_active_breach_rows(conn):
    cur = conn.cursor()
    try:
        cur.execute(f"""
            SELECT CASE_NUMBER, CUSTOMER_NAME, CASE_OWNER, SEVERITY, SUPPORT_LEVEL,
                   SUPPORT_TIER, SLA_STATUS, SLA_DEADLINE, LAST_CUSTOMER_COMMENT,
                   SLA_VARIANCE_MINS, BREACH_MONTH, IS_HEAL_DESK, SUBJECT
            FROM {SLA_BREACH_IMPACT_TABLE}
            WHERE RECORD_TYPE = 'ACTIVE_BREACH'
            QUALIFY ROW_NUMBER() OVER (PARTITION BY CASE_NUMBER ORDER BY SNAPSHOT_TIMESTAMP DESC) = 1
        """)
        return cur.fetchall()
    finally:
        cur.close()

def _daily_impact_already_synced(conn, snapshot_date):
    cur = conn.cursor()
    try:
        cur.execute(
            f"SELECT COUNT(*) FROM {SLA_BREACH_IMPACT_TABLE} WHERE RECORD_TYPE = 'DAILY_IMPACT' AND SNAPSHOT_DATE = %s",
            (snapshot_date,)
        )
        return (cur.fetchone() or [0])[0] > 0
    finally:
        cur.close()

def _fetch_salesforce_case_statuses(case_numbers):
    if not case_numbers:
        return {}
    sf = get_sf_connection()
    statuses = {}
    for i in range(0, len(case_numbers), 100):
        chunk = case_numbers[i:i + 100]
        safe_numbers = [str(num).replace("\\", "\\\\").replace("'", "\\'") for num in chunk if num]
        if not safe_numbers:
            continue
        case_filter = "'" + "', '".join(safe_numbers) + "'"
        result = sf.query_all(f"SELECT CaseNumber, Status FROM Case WHERE CaseNumber IN ({case_filter})")
        for record in result.get("records", []):
            statuses[record.get("CaseNumber")] = record.get("Status")
    return statuses

def _build_daily_impact_rows(conn, current_priority_df, now_ist):
    if now_ist.hour < 18 or _daily_impact_already_synced(conn, now_ist.date()):
        return []

    latest_rows = _get_latest_active_breach_rows(conn)
    if not latest_rows:
        return []

    current_by_case = {}
    if current_priority_df is not None and not current_priority_df.empty:
        current_by_case = {
            row.get("Case Number"): row
            for row in current_priority_df.to_dict(orient="records")
            if row.get("Case Number")
        }

    case_numbers = [row[0] for row in latest_rows if row[0]]
    sf_statuses = _fetch_salesforce_case_statuses(case_numbers)
    impact_rows = []

    for row in latest_rows:
        (
            case_number, customer_name, case_owner, severity, support_level,
            support_tier, previous_sla_status, sla_deadline, last_customer_comment,
            sla_variance_mins, breach_month, is_heal_desk, subject
        ) = row

        current_status = sf_statuses.get(case_number)
        current_row = current_by_case.get(case_number, {})
        current_sla_status = current_row.get("SLA Response Time")
        impact_status = None
        impact_reason = None

        if current_status and current_status not in ACTIVE_CASE_STATUSES:
            impact_status = "STATUS_EXITED_ACTIVE"
            impact_reason = f"Case status changed to {current_status}"
        elif current_sla_status and "Due in" in str(current_sla_status):
            impact_status = "MOVED_TO_DUE_IN"
            impact_reason = "Case moved from overdue to due in"

        if not impact_status:
            continue

        impact_rows.append((
            "DAILY_IMPACT",
            now_ist.date(),
            now_ist.replace(tzinfo=None),
            case_number,
            customer_name,
            case_owner,
            severity,
            support_level,
            support_tier,
            current_status,
            current_sla_status or previous_sla_status,
            sla_deadline,
            last_customer_comment,
            sla_variance_mins,
            breach_month,
            is_heal_desk,
            subject,
            impact_status,
            impact_reason,
            previous_sla_status,
            current_sla_status,
        ))
    return impact_rows

def sync_sla_breach_impact_history(current_priority_df=None):
    ist = pytz.timezone("Asia/Kolkata")
    now_ist = datetime.now(ist)
    breaches_df = get_all_breach_records()
    conn = get_snowflake_connection()

    active_rows = _build_breach_rows(
        breaches_df,
        "ACTIVE_BREACH",
        "ACTIVE_OVERDUE",
        "Current active SLA breach snapshot",
        now_ist,
    )
    impact_rows = _build_daily_impact_rows(conn, current_priority_df, now_ist)
    total_rows = _merge_sla_breach_rows(conn, active_rows + impact_rows)
    if total_rows:
        print(f"✅ SLA breach impact sync: upserted {total_rows} rows.")
    return total_rows


def render_30_day_chart(active_owners, search_query="", is_heal_desk_filter=False):
    st.markdown("<h3 style='color: #F8FAFC; margin-top: 0; margin-bottom: 10px;'>📊 Ongoing SLA Breaches</h3>", unsafe_allow_html=True)
    
    all_breaches_df = get_all_breach_records()
    
    # Filter by active owners
    if active_owners:
        filtered_df = all_breaches_df[all_breaches_df['Case Owner'].isin(active_owners)]
    else:
        filtered_df = all_breaches_df.copy()
    
    #  Apply Heal Desk Filter
    if is_heal_desk_filter:
        filtered_df = filtered_df[filtered_df['Is_Heal_Desk'] == True].copy()
    
    # 🔍 Apply search filter if exists
    if search_query:
        search_terms = [term.strip() for term in search_query.split(",") if term.strip()]
        if search_terms:
            mask = pd.Series(False, index=filtered_df.index)
            for term in search_terms:
                mask = mask | filtered_df["Case Number"].astype(str).str.contains(term, case=False, na=False)
            filtered_df = filtered_df[mask]

    with st.container(border=True, height=350): 
        if filtered_df.empty:
            st.markdown("<div style='text-align:center; color:#94A3B8; padding:25px; font-size:14px;'>✨ No active SLA breaches for selected filters</div>", unsafe_allow_html=True)
        else:
            pivot_df = filtered_df.groupby(['Breach_Month', 'Support Tier']).size().unstack(fill_value=0)
            for tier in ['Standard', 'Premium']:
                if tier not in pivot_df.columns: pivot_df[tier] = 0
            pivot_df = pivot_df.sort_index().tail(6)
            
            months = pivot_df.index.tolist()
            formatted_months = [datetime.strptime(m, '%Y-%m').strftime("%b '%y") for m in months]
            
            fig = go.Figure()
            fig.add_trace(go.Bar(x=formatted_months, y=pivot_df['Standard'].astype(int).tolist(), name='Standard',
                marker_color='rgba(59, 130, 246, 0.95)', marker_line_color='rgba(37, 99, 235, 1)', width=0.35,
                hovertemplate='<b>Standard</b><br> %{x}<br>🔴 %{y}<extra></extra>'))
            fig.add_trace(go.Bar(x=formatted_months, y=pivot_df['Premium'].astype(int).tolist(), name='Premium',
                marker_color='rgba(16, 185, 129, 0.95)', marker_line_color='rgba(5, 150, 105, 1)', width=0.35,
                hovertemplate='<b>Premium</b><br>📅 %{x}<br> %{y}<extra></extra>'))
                
            fig.update_layout(barmode='group', bargap=0.15, bargroupgap=0.1, height=330,
                margin=dict(l=45, r=15, t=25, b=50), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                font=dict(color="#F8FAFC", family="Inter, sans-serif", size=11),
                xaxis=dict(tickangle=-45, gridcolor='#334155', tickfont=dict(size=10, color="#94A3B8")),
                yaxis=dict(title="Breached Cases", gridcolor='#334155', tickfont=dict(size=10, color="#94A3B8")),
                legend=dict(orientation="h", yanchor="top", y=-0.18, xanchor="center", x=0.5, font=dict(size=10, color="#E2E8F0")),
                annotations=[dict(x=0.5, y=1.02, xref="paper", yref="paper", 
                    text=f"Total Active Breaches: <b>{len(filtered_df)}</b>", 
                    showarrow=False, font=dict(size=11, color="#94A3B8"))])
            st.plotly_chart(fig, use_container_width=True, theme=None)

    if not filtered_df.empty:
        with st.expander(f"🔍 View {len(filtered_df)} Breached Case Details", expanded=False):
            display_cols = ['Case Number', 'Customer Name', 'Case Owner', 'Severity', 'Support Level', 'SLA Status', 'SLA Deadline', 'Last Customer Comment', 'Subject']
            st.dataframe(filtered_df[display_cols].style.map(lambda v: 'color: #F87171; font-weight: 600;' if 'Overdue' in str(v) else '', subset=['SLA Status']),
                use_container_width=True, height=200, hide_index=True,
                column_config={"Case Number": st.column_config.TextColumn("Case #", width="small"), "Customer Name": st.column_config.TextColumn("Customer", width="medium"),
                    "Case Owner": st.column_config.TextColumn("Owner", width="small"), "Severity": st.column_config.TextColumn("Sev", width="xsmall"),
                    "Support Level": st.column_config.TextColumn("Support", width="small"), "SLA Status": st.column_config.TextColumn("Status", width="medium"),
                    "SLA Deadline": st.column_config.TextColumn("Deadline", width="small"), 
                    "Subject": st.column_config.TextColumn("Subject", width="large")})
            p_count = (filtered_df['Support Tier'] == 'Premium').sum()
            st.markdown(f"<div style='text-align:right; font-size:11px; color:#94A3B8; margin-top:8px;'><b>{len(filtered_df)-p_count}</b> Standard • <b>{p_count}</b> Premium breached cases</div>", unsafe_allow_html=True)
    else:
        st.markdown("<div style='text-align:center; color:#64748B; padding:12px; font-size:12px; margin-top:8px; border:1px dashed #334155; border-radius:6px;'>📭 No breached case details to display</div>", unsafe_allow_html=True)
        
    st.markdown("<div style='text-align:center; font-size:11px; color:#64748B; margin-top:8px; opacity:0.9;'>Showing SLA breaches for New/Open/Assigned cases • Data refreshed hourly</div>", unsafe_allow_html=True)
