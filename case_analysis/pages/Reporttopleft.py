import streamlit as st
import pandas as pd
from services.case_service import CaseService
from datetime import datetime, timedelta
import pytz
import os
import snowflake.connector

# Initialize service and connection
service = CaseService()
sf = service.get_connection()

OWNER_REGION_MAP = {
    "Sakthi Devi SK": "APAC", "Mohamed Ramzin": "APAC", "Syeda Sajida": "APAC", "Yogesh R": "APAC", 
    "Ganesh Babu": "APAC", "Srinivas Aaguri": "APAC", "Sindhu M Y": "EMEA", "Payal Gupta": "EMEA", 
    "Poonam Pandey": "EMEA", "Mugilan Gowthaman": "EMEA", "Santosh Veduruvada": "EMEA", 
    "Sivagnana Bharathi Nagaraj": "EMEA", "Ullas Shenoy": "EMEA", "Vipul S G": "EMEA", 
    "Vilas Potadar": "EMEA", "Chethan Kumara P": "EMEA", "Chandra Sai Surya Santosh Veduruvada": "EMEA",
    "Aqsa Pandith": "NA EAST", "Prabu R": "NA EAST", "Vikas R": "NA EAST", "Tarun Buthala": "NA EAST", 
    "Gnanasiri Pechetti": "NA EAST", "Shivendra Yadav": "NA EAST", "Kaushik Patowary": "NA EAST", 
    "Shahrukh Shahzad": "NA EAST", "Amit Bhojak": "NA EAST", "Mohammed Usman": "NA EAST", 
    "Santi Sahoo": "NA EAST", "Nilanjan Roy": "NA EAST", "Nupur Rao": "NA EAST", 
    "Rohit Nargundkar": "NA EAST", "Prabu Rajendran": "NA EAST", "Palak Kharche": "NA EAST", 
    "Pooja Singh": "NA EAST", "Becca Lozano": "NA EAST", "Selvin Raja": "NA WEST", 
    "Shakti Prasad Pati": "NA WEST", "Sanjay Kademani": "NA WEST", "Shreyas G Nambiar": "NA WEST", 
    "Vishal Mavi": "NA WEST", "Infant Raj.": "NA WEST", "Pallavi M R": "NA WEST", 
    "Aniket Chinde": "NA WEST", "Kalyan Kumar": "NA WEST", "Amit Kumar": "NA WEST", 
    "Karthik Dosapati": "NA WEST", "Peter Kyller": "NA WEST", "ZAREENA BANO": "NA WEST", 
    "Karalie Murray": "NA WEST", "Sushmitha Rayalkeri": "P+", "Amith Gujjar": "P+", 
    "Monika Sihag": "P+", "Mohammad Raza": "P+", "Sumit Paul": "P+", "Imari Killikelly": "P+", 
    "Merlyn Pushparaj": "P+", "Naveen Kumar Surisetti": "P+", "Xactly Support Agent": "Agent"
}

def inject_custom_css():
    st.markdown("""
<style>
    [data-testid="stSidebar"] { display: none !important; }
    [data-testid="collapsedControl"] { display: none !important; }
    .main { padding-top:10px; }
    .block-container { padding-top:1rem; }
    h1 { font-size:42px !important; font-weight:800 !important; }
    [data-testid="stHorizontalBlock"] { gap:0.2rem; }
    p { font-size:12px !important; }
    button { font-size:11px !important; padding:0.1rem !important; }        
</style>
""", unsafe_allow_html=True)

@st.cache_resource
def get_sf_connection():
    service = CaseService()
    return service.get_connection()

@st.cache_data(ttl=3600)
def fetch_snowflake_sentiments():
    """Fetches CaseNumber -> Sentiment mapping from Snowflake. Cached for 1 hour."""
    try:
        conn = snowflake.connector.connect(
            user=os.getenv("SNOWFLAKE_USER"),
            password=os.getenv("SNOWFLAKE_PASSWORD"),
            account=os.getenv("SNOWFLAKE_ACCOUNT"),
            warehouse=os.getenv("SNOWFLAKE_WAREHOUSE", "GENERALBIZ_WAREHOUSE"),
            database=os.getenv("SNOWFLAKE_DATABASE", "CUSTOMER_SUPPORT_BOT_LOGS"),
            schema=os.getenv("SNOWFLAKE_SCHEMA", "CHAT_DATA")
        )
        cursor = conn.cursor()
        cursor.execute("SELECT CaseNumber, Sentiment FROM DBD_SENTIMENT_DATA")
        rows = cursor.fetchall()
        sentiments = {row[0]: row[1] for row in rows}
        cursor.close()
        conn.close()
        return sentiments
    except Exception as e:
        print(f"❌ Snowflake fetch failed: {e}")
        return {}

def calculate_score(sevone, severity, support_level, escalated):
    if sevone: return 14
    if escalated: return 13
    score_map = {
        ("S1", "Premium Plus"): 12, ("S1", "Premium (24x7)"): 12, ("S1", "Standard"): 10,
        ("S2", "Premium Plus"): 9, ("S2", "Premium (24x7)"): 8, ("S2", "Standard"): 7,
        ("S3", "Premium Plus"): 6, ("S3", "Premium (24x7)"): 5, ("S3", "Standard"): 4,
        ("S4", "Premium Plus"): 3, ("S4", "Premium (24x7)"): 2, ("S4", "Standard"): 1
    }
    return score_map.get((severity, support_level), 0)

def get_sla_hours(severity, support_level):
    if not severity or severity == "N/A": return None
    is_premium = "premium" in (support_level.lower() if support_level else "")
    sla_map = {"S1": {"premium": 0.5, "standard": 1.0}, "S2": {"premium": 1.0, "standard": 4.0}, 
               "S3": {"premium": 2.0, "standard": 6.0}, "S4": {"premium": 6.0, "standard": 8.0}}
    severity_key = severity.strip().upper()
    if severity_key.startswith("SEV") or severity_key == "SEVONE": severity_key = "S1"
    elif severity_key not in ["S1", "S2", "S3", "S4"]: return None
    tier = "premium" if is_premium else "standard"
    return sla_map[severity_key].get(tier)

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

@st.cache_data(ttl=3600)
def get_project_support(project_id):
    sf = get_sf_connection()
    acc_q = f"SELECT Name FROM Account WHERE Id='{project_id}' LIMIT 1"
    acc_res = sf.query(acc_q)
    if not acc_res["records"]: return None
    proj_name = acc_res["records"][0].get("Name")
    sup_q = f"SELECT Support_Level__c FROM Case WHERE Account.Name LIKE '%{proj_name}%' AND Support_Level__c != NULL LIMIT 1"
    sup_res = sf.query(sup_q)
    return sup_res["records"][0].get("Support_Level__c") if sup_res["records"] else None

def fetch_cases():
    sf = get_sf_connection()
    query = """
        SELECT Id, CaseNumber, Subject, Status, Owner.Name, Account.Name, AccountName__c,
            Support_Level__c, Severity__c, Sevone__c, IsEscalated, CreatedDate, ClosedDate,
            (select CommentBody, CreatedBy.Name, CreatedDate, IsPublished from CaseComments where IsPublished=true order by CreatedDate Desc)
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
            'Vilas Potadar', 'Vipul S G', 'Vishal Mavi', 'Yogesh R', 'Zareena Bano', 'Zareena')"""
    return sf.query_all(query)["records"]

def convert_to_ist(date_string):
    if not date_string or date_string == "N/A": return "N/A"
    try:
        date_string = date_string.replace("Z", "+0000")
        fmt = "%Y-%m-%dT%H:%M:%S.%f%z" if "." in date_string else "%Y-%m-%dT%H:%M:%S%z"
        utc_time = datetime.strptime(date_string, fmt)
        ist_time = utc_time.astimezone(pytz.timezone("Asia/Kolkata"))
        return ist_time.strftime("%d-%b %H:%M")
    except: return date_string

def calculate_sla_deadline(last_customer_comment_time, sla_hours_duration, support_level=None):
    if not last_customer_comment_time or last_customer_comment_time == "N/A" or not sla_hours_duration: return "N/A"
    try:
        ist = pytz.timezone("Asia/Kolkata")
        dt = datetime.strptime(f"{datetime.now().year}-{last_customer_comment_time}", "%Y-%d-%b %H:%M")
        dt_aware = ist.localize(dt)
        deadline_aware = add_sla_hours_with_weekend_skip(dt_aware, sla_hours_duration, support_level)
        return deadline_aware.strftime("%d-%b %H:%M")
    except: return "N/A"

def calculate_sla_variance(deadline_str):
    if not deadline_str or deadline_str == "N/A": return "N/A", float('inf')
    try:
        ist = pytz.timezone("Asia/Kolkata")
        now_ist = datetime.now(ist)
        deadline_dt = datetime.strptime(f"{now_ist.year}-{deadline_str}", "%Y-%d-%b %H:%M")
        deadline_dt = ist.localize(deadline_dt)
        diff = deadline_dt - now_ist
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
    except: return deadline_str, float('inf')

def get_breach_shift(deadline_str, sla_minutes):
    if not deadline_str or deadline_str == "N/A" or sla_minutes >= 0: return "N/A"
    try:
        ist = pytz.timezone("Asia/Kolkata")
        dt = datetime.strptime(f"{datetime.now().year}-{deadline_str}", "%Y-%d-%b %H:%M")
        dt_aware = ist.localize(dt)
        h = dt_aware.hour
        if 6 <= h < 14: return "APAC"
        elif 14 <= h < 20: return "EMEA"
        elif h >= 20 or h < 2: return "NA EAST"
        elif 2 <= h < 6: return "NA WEST"
        return "N/A"
    except: return "N/A"

def get_processed_data():
    with st.spinner("Fetching Salesforce Cases..."):
        cases = fetch_cases()
    sf_sentiments = fetch_snowflake_sentiments()
    dashboard = []

    for case in cases:
        if not case: continue
        owner_name = (case.get("Owner") or {}).get("Name", "UNKNOWN")
        customer_name = (case.get("Account") or {}).get("Name", "N/A")
        support_level = case.get("Support_Level__c") or "N/A"
        project_id = case.get("AccountName__c")
        if customer_name != "N/A" and "Xactly" in customer_name and project_id:
            try:
                cached = get_project_support(project_id)
                if cached: support_level = cached
            except: pass

        severity = case.get("Severity__c") or "N/A"
        sevone = case.get("SEVONE__c")
        escalated = case.get("IsEscalated") or False
        case_score = calculate_score(sevone, severity, support_level, escalated)  
        sla_hours = get_sla_hours(severity, support_level)      

        last_commenter = "Internal Comment"
        last_customer_comment_time = "N/A"
        comments = (case.get("CaseComments") or {}).get("records", [])
        if comments:
            latest = comments[0]
            created_by = (latest.get("CreatedBy") or {}).get("Name", "")
            last_commenter = "Support Comment" if created_by in OWNER_REGION_MAP else "Customer Comment"
            for comment in comments:
                if (comment.get("CreatedBy") or {}).get("Name") == 'Customer Support User':
                    last_customer_comment_time = convert_to_ist(comment.get("CreatedDate") or "N/A")
                    break
        
        sla_deadline = calculate_sla_deadline(last_customer_comment_time, sla_hours, support_level)
        if sla_deadline == "N/A":
            created_ist = convert_to_ist(case.get("CreatedDate"))
            sla_deadline = calculate_sla_deadline(created_ist, sla_hours, support_level)
                    
        sla_text, sla_mins = calculate_sla_variance(sla_deadline)
        breach_shift = get_breach_shift(sla_deadline, sla_mins)
        sentiment = sf_sentiments.get(case.get("CaseNumber"), "")

        dashboard.append({
            "Region": OWNER_REGION_MAP.get(owner_name, "UNKNOWN"),
            "Case Number": case.get("CaseNumber", "N/A"),
            "Customer Name": customer_name,
            "Case Owner": owner_name,
            "Support Level": support_level,
            "Severity": severity,
            "Status": case.get("Status", "N/A"),
            "Escalated": escalated,
            "Last Comment By": last_commenter,
            "Sentiment": sentiment,
            "Case Score": case_score,
            "Last Customer Comment": last_customer_comment_time,
            "SLA Response Time": sla_text,
            "SLA_Minutes": sla_mins,
            "SLA_Breach_Shift": breach_shift
        })
    return pd.DataFrame(dashboard), cases

def apply_filters_and_ranking(df):
    c1, c2, c3 = st.columns([1, 1, 1])
    with c1:
        regions = sorted(set(OWNER_REGION_MAP.values()) - {"Agent"})
        opts = ["ALL"] + regions
        default = st.session_state.get("selected_regions", ["ALL"])
        sel = st.multiselect(":earth_africa: Region", opts, default=default, key="region_filter")
        st.session_state.selected_regions = sel
    active_regions = regions if "ALL" in sel else sel
    temp_df = df[df["Region"].isin(active_regions)] if active_regions else df.iloc[:0]
    avail_owners = sorted(o for o, r in OWNER_REGION_MAP.items() if r in active_regions) if active_regions else []
        
    with c2:
        cur = st.session_state.get("selected_owners", [])
        if any(o not in avail_owners for o in cur):
            if "selected_owners" in st.session_state: del st.session_state.selected_owners
            st.rerun()
        sel_owners = st.multiselect(":bust_in_silhouette: Owner", avail_owners, default=cur, key="owner_filter")
        st.session_state.selected_owners = sel_owners

    with c3:
        cats = ["Need Immediate Attention", "Need Secondary Attention"]
        def_sla = st.session_state.get("selected_sla_status", [])
        sel_sla = st.multiselect(":hourglass_flowing_sand: SLA Prioritization", cats, default=def_sla, key="sla_filter")
        st.session_state.selected_sla_status = sel_sla

    if not active_regions: return temp_df, []
    filtered = temp_df[temp_df["Case Owner"].isin(sel_owners)] if sel_owners else temp_df

    if sel_sla:
        filtered = filtered.sort_values(by="SLA_Minutes", ascending=True)
        mask = pd.Series(False, index=filtered.index)
        if "Need Immediate Attention" in sel_sla: mask.loc[filtered.head(25).index] = True
        if "Need Secondary Attention" in sel_sla: mask.loc[filtered.iloc[25:50].index] = True
        filtered = filtered[mask]
        filtered["Sequential_Rank"] = range(1, len(filtered) + 1)
    elif not filtered.empty:
        filtered = filtered.sort_values(by=["Case Owner", "Case Score"], ascending=[True, False])
        filtered["Sequential_Rank"] = filtered.groupby("Case Owner").cumcount() + 1

    return filtered, sel_owners if sel_owners else avail_owners

def render_table(filtered_df, cases):
    st.subheader(":clipboard: Case Monitoring Dashboard")
    if "sort_column" not in st.session_state: st.session_state.sort_column = None
    if "sort_asc" not in st.session_state: st.session_state.sort_asc = True

    report_box = st.container(height=350)
    with report_box:
        col_widths = [0.8, 1.0, 2.5, 2.0, 1.8, 0.8, 1.0, 0.8, 1.3, 2.0, 1.8, 2.0, 2.0, 0.6]
        col_mapping = {"Region": "Region", "Case": "Case Number", "Customer": "Customer Name", "Owner": "Case Owner",
                       "Support Level": "Support Level", "Severity": "Severity", "Status": "Status", "Escalated": "Escalated",
                       "Sentiment": "Sentiment", "Last Comment": "Last Comment By", "LCC Time": "Last Customer Comment",
                       "SLA Deadline": "SLA Response Time", "SLA Breach Shift": "SLA_Breach_Shift", "Rank": "Sequential_Rank"}
        
        headers = st.columns(col_widths)
        for i, (d_name, df_col) in enumerate(col_mapping.items()):
            icon = " ▲" if st.session_state.sort_column == df_col and st.session_state.sort_asc else " ▼" if st.session_state.sort_column == df_col else ""
            if headers[i].button(f"{d_name}{icon}", key=f"sort_{df_col}"):
                if st.session_state.sort_column == df_col: st.session_state.sort_asc = not st.session_state.sort_asc
                else: st.session_state.sort_column, st.session_state.sort_asc = df_col, True
                st.rerun()
        st.markdown("---")
        
        display_df = filtered_df.copy()
        if st.session_state.sort_column and st.session_state.sort_column in display_df.columns:
            target = "SLA_Minutes" if st.session_state.sort_column == "SLA Response Time" else st.session_state.sort_column
            display_df = display_df.sort_values(by=target, ascending=st.session_state.sort_asc)
            
        for _, row in display_df.iterrows():
            cols = st.columns(col_widths)
            cols[0].write(row["Region"]); cols[1].write(row["Case Number"]); cols[2].write(row["Customer Name"])
            cols[3].write(row["Case Owner"]); cols[4].write(row["Support Level"]); cols[5].write(row["Severity"])
            cols[6].write(row["Status"]); cols[7].write("Yes" if row["Escalated"] else "No")

            sentiment = row["Sentiment"]
            if not sentiment or sentiment.strip() == "":
                cols[8].write("")
            else:
                s_low = sentiment.lower()
                if "positive" in s_low: cols[8].success(sentiment) 
                elif "neutral" in s_low or "medium" in s_low: cols[8].warning(sentiment) 
                elif "negative" in s_low or "critical" in s_low: cols[8].error(sentiment)   
                else: cols[8].info(sentiment)    

            cols[9].write(row["Last Comment By"]); cols[10].write(row["Last Customer Comment"])
            cols[11].write(row["SLA Response Time"]); cols[12].write(row["SLA_Breach_Shift"])
            cols[13].markdown(f"<div style='color: #FFFFFF; font-weight: 600; font-size: 14px;'>{row['Sequential_Rank']}</div>", unsafe_allow_html=True)

def main():
    inject_custom_css()
    st.title("🎯 Support Case Dashboard")
    df, raw_cases = get_processed_data()
    filtered_df, _ = apply_filters_and_ranking(df)
    render_table(filtered_df, raw_cases)

if __name__ == "__main__":
    main()