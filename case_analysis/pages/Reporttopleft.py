import streamlit as st
import pandas as pd
from services.case_service import CaseService
from services.case_service import SalesforceConnector
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import pytz

# Initialize service and connection
service = CaseService()
sf = service.get_connection()

# ---------------------------------------------------
# CONFIGURATION & CSS
# ---------------------------------------------------

OWNER_REGION_MAP = {
    # APAC
    "Sakthi Devi SK": "APAC", "Mohamed Ramzin": "APAC", "Syeda Sajida": "APAC",
    "Yogesh R": "APAC", "Ganesh Babu": "APAC", "Srinivas Aaguri": "APAC",
    # EMEA
    "Sindhu M Y": "EMEA", "Payal Gupta": "EMEA", "Poonam Pandey": "EMEA",
    "Mugilan Gowthaman": "EMEA", "Santosh Veduruvada": "EMEA", "Sivagnana Bharathi Nagaraj": "EMEA",
    "Ullas Shenoy": "EMEA", "Vipul S G": "EMEA", "Vilas Potadar": "EMEA",
    "Chethan Kumara P": "EMEA", "Chandra Sai Surya Santosh Veduruvada": "EMEA",
    # NA EAST
    "Aqsa Pandith": "NA EAST", "Prabu R": "NA EAST", "Vikas R": "NA EAST",
    "Tarun Buthala": "NA EAST", "Gnanasiri Pechetti": "NA EAST", "Shivendra Yadav": "NA EAST",
    "Kaushik Patowary": "NA EAST", "Shahrukh Shahzad": "NA EAST", "Amit Bhojak": "NA EAST",
    "Mohammed Usman": "NA EAST", "Santi Sahoo": "NA EAST", "Nilanjan Roy": "NA EAST",
    "Nupur Rao": "NA EAST", "Rohit Nargundkar": "NA EAST", "Prabu Rajendran": "NA EAST",
    "Palak Kharche": "NA EAST", "Pooja Singh": "NA EAST", "Becca Lozano": "NA EAST",
    # NA WEST
    "Selvin Raja": "NA WEST", "Shakti Prasad Pati": "NA WEST", "Sanjay Kademani": "NA WEST",
    "Shreyas G Nambiar": "NA WEST", "Vishal Mavi": "NA WEST", "Infant Raj.": "NA WEST",
    "Pallavi M R": "NA WEST", "Aniket Chinde": "NA WEST", "Kalyan Kumar": "NA WEST",
    "Amit Kumar": "NA WEST", "Karthik Dosapati": "NA WEST", "Peter Kyller": "NA WEST",
    "ZAREENA BANO": "NA WEST", "Karalie Murray": "NA WEST",
    # Premium Plus
    "Sushmitha Rayalkeri": "P+", "Amith Gujjar": "P+", "Monika Sihag": "P+",
    "Mohammad Raza": "P+", "Sumit Paul": "P+", "Imari Killikelly": "P+",
    "Merlyn Pushparaj": "P+", "Naveen Kumar Surisetti": "P+",
    # internal
    "Xactly Support Agent": "Agent"
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

# ---------------------------------------------------
#  LOGIC
# ---------------------------------------------------

def calculate_score(sevone, severity, support_level, escalated):
    if sevone:
        return 14
    if escalated:
        return 13

    score_map = {
        ("S1", "Premium Plus"): 12, ("S1", "Premium (24x7)"): 12, ("S1", "Standard"): 10,
        ("S2", "Premium Plus"): 9, ("S2", "Premium (24x7)"): 8, ("S2", "Standard"): 7,
        ("S3", "Premium Plus"): 6, ("S3", "Premium (24x7)"): 5, ("S3", "Standard"): 4,
        ("S4", "Premium Plus"): 3, ("S4", "Premium (24x7)"): 2, ("S4", "Standard"): 1
    }
    return score_map.get((severity, support_level), 0)

def get_sla_hours(severity, support_level):
    if not severity or severity == "N/A":
        return None
    
    sl_lower = support_level.lower() if support_level else ""
    is_premium = "premium" in sl_lower
    
    sla_map = {
        "S1": {"premium": 0.5, "standard": 1.0},
        "S2": {"premium": 1.0, "standard": 4.0},
        "S3": {"premium": 2.0, "standard": 6.0},
        "S4": {"premium": 6.0, "standard": 8.0},
    }
    
    severity_key = severity.strip().upper()
    if severity_key.startswith("SEV") or severity_key == "SEVONE":
         severity_key = "S1" 
    elif severity_key not in ["S1", "S2", "S3", "S4"]:
        return None

    tier = "premium" if is_premium else "standard"
    try:
        return sla_map[severity_key][tier]
    except KeyError:
        return None

# ---------------------------------------------------
# WEEKEND EXCLUSION HELPER FUNCTIONS
# ---------------------------------------------------
def is_in_weekend_window(dt):
    """Returns True if dt (IST aware) falls in Sat 5AM - Mon 5AM IST window."""
    wd = dt.weekday()
    if wd == 5:  # Saturday
        return dt.hour >= 5
    if wd == 6:  # Sunday
        return True
    if wd == 0:  # Monday
        return dt.hour < 5
    return False

def jump_to_next_business_time(dt):
    """If in weekend window, jumps to Monday 5 AM IST."""
    if not is_in_weekend_window(dt):
        return dt
    wd = dt.weekday()
    if wd == 0:  # Already Monday but before 5 AM
        return dt.replace(hour=5, minute=0, second=0, microsecond=0)
    # Saturday or Sunday: jump to next Monday
    days_ahead = (0 - wd) % 7
    next_mon = dt + timedelta(days=days_ahead)
    return next_mon.replace(hour=5, minute=0, second=0, microsecond=0)

def add_sla_hours_with_weekend_skip(start_dt, hours, support_level):
    """Adds SLA hours, pausing the clock for Standard support during weekends."""
    if not support_level or "standard" not in support_level.lower():
        return start_dt + timedelta(hours=hours)

    current = jump_to_next_business_time(start_dt)
    remaining = hours
    step = 0.5  # 30-minute precision for accurate SLA tracking

    while remaining > 0:
        add_amt = min(remaining, step)
        next_dt = current + timedelta(hours=add_amt)
        if is_in_weekend_window(next_dt):
            current = jump_to_next_business_time(next_dt)
            continue
        current = next_dt
        remaining -= add_amt
    return current

# ---------------------------------------------------
# SLA & DATA FETCHING
# ---------------------------------------------------

@st.cache_data(ttl=3600)
def get_project_support(project_id):
    sf = get_sf_connection()
    account_query = f"SELECT Name FROM Account WHERE Id='{project_id}' LIMIT 1"
    account_result = sf.query(account_query)
    if not account_result["records"]:
        return None
    project_name = account_result["records"][0].get("Name")
    support_query = f"SELECT Support_Level__c FROM Case WHERE Account.Name LIKE '%{project_name}%' AND Support_Level__c != NULL LIMIT 1"
    support_result = sf.query(support_query)
    if support_result["records"]:
        return support_result["records"][0].get("Support_Level__c")
    return None

def fetch_cases():
    sf = get_sf_connection()
    query = """
        SELECT
            Id, CaseNumber, Subject, Status, Owner.Name, Account.Name, AccountName__c,
            Support_Level__c, Severity__c, Sevone__c, IsEscalated, CreatedDate, ClosedDate,
            (select CreatedBy.Name, CreatedDate, IsPublished from CaseComments where IsPublished=true order by CreatedDate Desc)
        FROM Case
        WHERE Status IN ('New', 'Open', 'Assigned') and Owner.Name IN (
            'Amit Bhojak', 'Amit Kumar', 'Amith Gujjar', 'Aniket Chinde',
            'Aqsa Pandith', 'Becca Lozano', 'Chethan Kumara P', 'Ganesh Babu',
            'Gnanasiri Pechetti', 'Imari Killikelly', 'Infant Raj.', 'Ishaq Mathina', 
            'Kalyan Kumar', 'Karalie Murray', 'Karthik Dosapati', 'Kaushik Patowary', 'Mahesh P M',
            'Merlyn Pushparaj', 'Mohamed Ramzin', 'Mohammad Raza', 'Mohammed Usman', 'Monika Sihag',
            'Mugilan Gowthaman', 'Naveen Kumar Surisetti', 'Nilanjan Roy', 'Nupur Rao', 'Palak Kharche',
            'Pallavi M R', 'Payal Gupta', 'Peter Kyller', 'Pooja Singh', 'Poonam Pandey',
            'Prabu Rajendran', 'Prabu R', 'Rohit Nargundkar', 'Sakthi Devi SK', 'Sanjay Kademani',
            'Chandra Sai Surya Santosh Veduruvada', 'Santi Sahoo', 'Selvin Raja', 'Shahrukh Shahzad', 'Shakti Prasad Pati',
            'Shreyas G Nambiar', 'Shivendra Yadav', 'Sindhu M Y', 'Sivagnana Bharathi Nagaraj', 'Sivaji Koya',
            'Srinivas Aaguri', 'Sumit Paul', 'Sumit', 'Sushmitha Rayalkeri', 'Syeda Sajida',
            'Tarun Buthala', 'Ullas Shenoy', 'Vikas R', 'Vilas Potadar', 'Vipul S G',
            'Vishal Mavi', 'Yogesh R', 'Zareena Bano', 'Zareena')"""
    result = sf.query_all(query)
    return result["records"]

def convert_to_ist(date_string):
    if not date_string or date_string == "N/A":
        return "N/A"
    try:
        date_string = date_string.replace("Z", "+0000")
        if "." in date_string:
            utc_time = datetime.strptime(date_string, "%Y-%m-%dT%H:%M:%S.%f%z")
        else:
            utc_time = datetime.strptime(date_string, "%Y-%m-%dT%H:%M:%S%z")
        ist = pytz.timezone("Asia/Kolkata")
        ist_time = utc_time.astimezone(ist)
        return ist_time.strftime("%d-%b %H:%M")
    except Exception as e:
        return date_string

def calculate_sla_deadline(last_customer_comment_time, sla_hours_duration, support_level=None):
    if not last_customer_comment_time or last_customer_comment_time == "N/A" or not sla_hours_duration:
        return "N/A"
    try:
        current_year = datetime.now().year
        ist = pytz.timezone("Asia/Kolkata")
        dt = datetime.strptime(f"{current_year}-{last_customer_comment_time}", "%Y-%d-%b %H:%M")
        dt_aware = ist.localize(dt)

        # Apply weekend skip logic for Standard support
        deadline_aware = add_sla_hours_with_weekend_skip(dt_aware, sla_hours_duration, support_level)
        return deadline_aware.strftime("%d-%b %H:%M")
    except Exception:
        return "N/A"

def calculate_sla_variance(deadline_str):
    if not deadline_str or deadline_str == "N/A":
        return "N/A", float('inf')
    try:
        ist = pytz.timezone("Asia/Kolkata")
        now_ist = datetime.now(ist)
        deadline_dt = datetime.strptime(f"{now_ist.year}-{deadline_str}", "%Y-%d-%b %H:%M")
        deadline_dt = ist.localize(deadline_dt)
        diff = deadline_dt - now_ist
        total_minutes = int(diff.total_seconds() / 60)
        
        is_overdue = total_minutes < 0
        abs_mins = abs(total_minutes)
        
        days, remainder = divmod(abs_mins, 1440)
        hours, mins = divmod(remainder, 60)
        
        time_parts = []
        if days > 0:
            time_parts.append(f"{days}d")
        if hours > 0 or days > 0:
            time_parts.append(f"{hours}h")
        time_parts.append(f"{mins}m")
        
        formatted_time = " ".join(time_parts)
        
        if is_overdue:
            return f"🚨 Overdue: {formatted_time}", total_minutes
        else:
            return f"⏳ Due in: {formatted_time}", total_minutes
            
    except Exception:
        return deadline_str, float('inf')

def get_processed_data():
    with st.spinner("Fetching Salesforce Cases..."):
        cases = fetch_cases()

    if "sentiments" not in st.session_state:
        st.session_state.sentiments = {}

    dashboard = []

    for case in cases:
        if case is None:
            continue

        owner_name = (case.get("Owner") or {}).get("Name", "UNKNOWN")
        customer_name = (case.get("Account") or {}).get("Name", "N/A")
        support_level = (case.get("Support_Level__c") or "N/A")

        project_id = case.get("AccountName__c")
        if (customer_name != "N/A" and "Xactly" in customer_name and project_id):
            try:
                cached_support = get_project_support(project_id)
                if cached_support:
                    support_level = cached_support
            except Exception as e:
                print(f"Xactly override failed: {e}")

        severity = (case.get("Severity__c") or "N/A")
        sevone = (case.get("SEVONE__c"))
        escalated = (case.get("IsEscalated") or False)

        case_score = calculate_score(sevone, severity, support_level, escalated)  
        sla_hours_duration = get_sla_hours(severity, support_level)      

        last_commenter = "Internal Comment"
        last_customer_comment_time = "N/A"

        comments = (case.get("CaseComments") or {}).get("records", [])

        if comments:
            latest = comments[0]
            created_by = (latest.get("CreatedBy") or {}).get("Name", "")
            if created_by in OWNER_REGION_MAP:
                last_commenter = "Support Comment"
            else:
                last_commenter = "Customer Comment"

            for comment in comments:
                comment_user = (comment.get("CreatedBy") or {}).get("Name", "")
                if comment_user == 'Customer Support User':
                    last_customer_comment_time = convert_to_ist(comment.get("CreatedDate") or "N/A")
                    break
        
        # Pass support_level to enable weekend exclusion logic
        sla_deadline_time = calculate_sla_deadline(last_customer_comment_time, sla_hours_duration, support_level)
                
        # Fallback: If no customer comment, calculate deadline using the creation date
        if sla_deadline_time == "N/A" or not sla_deadline_time:
            case_created_date = case.get("CreatedDate")
            created_ist_str = convert_to_ist(case_created_date) if case_created_date else "N/A"
            sla_deadline_time = calculate_sla_deadline(created_ist_str, sla_hours_duration, support_level)
                    
        relative_sla_time, sla_minutes = calculate_sla_variance(sla_deadline_time)
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
            "Sentiment": st.session_state.sentiments.get(case.get("CaseNumber"), "Not Analyzed"),
            "Case Score": case_score,
            "Last Customer Comment": last_customer_comment_time,
            "SLA Response Time": relative_sla_time,
            "SLA_Minutes": sla_minutes
        })

    return pd.DataFrame(dashboard), cases

def apply_filters_and_ranking(df):
    c1, c2, c3 = st.columns([1, 1, 1])

    with c1:
        all_regions = sorted(list(set(OWNER_REGION_MAP.values())))
        all_regions = [region for region in all_regions if region != "Agent"]
        region_options = ["ALL"] + all_regions
        default_region = st.session_state.get("selected_regions", ["ALL"])
        selected_regions = st.multiselect(":earth_africa: Region", region_options, default=default_region, key="region_filter")
        st.session_state.selected_regions = selected_regions

    active_regions = all_regions if "ALL" in selected_regions else selected_regions

    if active_regions:
        temp_df = df[df["Region"].isin(active_regions)]
        available_owners = sorted([owner for owner, region in OWNER_REGION_MAP.items() if region in active_regions])
    else:
        temp_df = df.iloc[:0]
        available_owners = []
        
    with c2:
        current_selected_owners = st.session_state.get("selected_owners", [])
        invalid_owners = [owner for owner in current_selected_owners if owner not in available_owners]
        if invalid_owners:
            if "selected_owners" in st.session_state:
                del st.session_state.selected_owners
            st.rerun()
        selected_owners = st.multiselect(
            ":bust_in_silhouette: Owner", 
            available_owners, 
            default=current_selected_owners if not invalid_owners else [],
            key="owner_filter"
        )
        st.session_state.selected_owners = selected_owners

    with c3:
        sla_categories = ["Need Immediate Attention", "Need Secondary Attention"]
        default_sla = st.session_state.get("selected_sla_status", [])
        selected_sla_status = st.multiselect(
            ":hourglass_flowing_sand: SLA Prioritization", 
            sla_categories, 
            default=default_sla,
            key="sla_filter"
        )
        st.session_state.selected_sla_status = selected_sla_status

    active_owner_filter = selected_owners if selected_owners else available_owners
    if not active_regions:
        return temp_df, []

    if selected_owners:
        filtered_df = temp_df[temp_df["Case Owner"].isin(selected_owners)]
    else:
        filtered_df = temp_df

    if selected_sla_status:
        filtered_df = filtered_df.sort_values(by="SLA_Minutes", ascending=True)
        mask = pd.Series(False, index=filtered_df.index)
        if "Need Immediate Attention" in selected_sla_status:
            mask.loc[filtered_df.head(25).index] = True
        if "Need Secondary Attention" in selected_sla_status:
            mask.loc[filtered_df.iloc[25:50].index] = True
        filtered_df = filtered_df[mask]
        filtered_df["Sequential_Rank"] = range(1, len(filtered_df) + 1)
    else:
        if not filtered_df.empty:
            filtered_df = filtered_df.sort_values(by=["Case Owner", "Case Score"], ascending=[True, False])
            filtered_df["Sequential_Rank"] = filtered_df.groupby("Case Owner").cumcount() + 1

    return filtered_df, active_owner_filter

def render_table(filtered_df, cases, openai_service):
    st.subheader(":clipboard: AI Case Monitoring")
    
    if "sort_column" not in st.session_state:
        st.session_state.sort_column = None
    if "sort_asc" not in st.session_state:
        st.session_state.sort_asc = True

    report_box = st.container(height=350)

    with report_box:
        col_widths = [1, 1.2, 2.8, 3.0, 2, 1.0, 1.0, 1.2, 1.5, 2.5, 2.0, 2.2, 0.8]
        col_mapping = {
            "Region": "Region", "Case": "Case Number", "Customer": "Customer Name",
            "Owner": "Case Owner", "Support Level": "Support Level", "Severity": "Severity",
            "Status": "Status", "Escalated": "Escalated", "Sentiment": "Sentiment",
            "Last Comment": "Last Comment By", "LCC Time": "Last Customer Comment",
            "SLA Deadline": "SLA Response Time", "Rank": "Sequential_Rank"
        }
        
        headers = st.columns(col_widths)
        for i, (display_name, df_col) in enumerate(col_mapping.items()):
            icon = ""
            if st.session_state.sort_column == df_col:
                icon = " ▲" if st.session_state.sort_asc else " ▼"
            if headers[i].button(f"{display_name}{icon}", key=f"sort_{df_col}", help=f"Sort by {display_name}"):
                if st.session_state.sort_column == df_col:
                    st.session_state.sort_asc = not st.session_state.sort_asc
                else:
                    st.session_state.sort_column = df_col
                    st.session_state.sort_asc = True
                st.rerun()

        st.markdown("---")
        
        display_df = filtered_df.copy()
        if st.session_state.sort_column and st.session_state.sort_column in display_df.columns:
            sort_target = st.session_state.sort_column
            if sort_target == "SLA Response Time":
                sort_target = "SLA_Minutes"
            display_df = display_df.sort_values(by=sort_target, ascending=st.session_state.sort_asc)
            
        for index, row in display_df.iterrows():
            cols = st.columns(col_widths)
            cols[0].write(row["Region"])
            cols[1].write(row["Case Number"])
            cols[2].write(row["Customer Name"])
            cols[3].write(row["Case Owner"])
            cols[4].write(row["Support Level"])
            cols[5].write(row["Severity"])
            cols[6].write(row["Status"])
            cols[7].write("Yes" if row["Escalated"] else "No")

            sentiment = row["Sentiment"]
            if sentiment == "Not Analyzed":
                if cols[8].button(":brain: Analyze", key=f"analyze_{row['Case Number']}"):
                    with st.spinner(f"Analyzing {row['Case Number']}..."):
                        matching_case = next(c for c in cases if c["CaseNumber"] == row["Case Number"])
                        client = openai_service.get_connection()
                        prompt = f"""
                            Analyze this Salesforce support case.
                            Case Number: {matching_case.get("CaseNumber")}
                            Subject: {matching_case.get("Subject")}
                            Status: {matching_case.get("Status")}
                            Customer: {(matching_case.get("Account") or {}).get("Name","")}
                            Escalated: {matching_case.get("IsEscalated")}
                            Return ONLY one word: Positive, Neutral, Negative, or Critical.
                        """
                        response = client.chat.completions.create(
                            model="gpt-4o-mini",
                            messages=[{"role": "user", "content": prompt}],
                            temperature=0
                        )
                        sentiment = response.choices[0].message.content.strip()
                        st.session_state.sentiments[row["Case Number"]] = sentiment
                        st.rerun()
            else:
                sentiment_lower = sentiment.lower()
                if "positive" in sentiment_lower:
                    cols[8].success(sentiment) 
                elif "medium" in sentiment_lower or "neutral" in sentiment_lower:
                    cols[8].warning(sentiment) 
                elif "negative" in sentiment_lower or "critical" in sentiment_lower:
                    cols[8].error(sentiment)   
                else:
                    cols[8].info(sentiment)    

            cols[9].write(row["Last Comment By"])
            cols[10].write(row["Last Customer Comment"])
            cols[11].write(row["SLA Response Time"])
            cols[12].markdown(f"<div style='color: #FFFFFF; font-weight: 600; font-size: 14px;'>{row['Sequential_Rank']}</div>", unsafe_allow_html=True)

def main():
    inject_custom_css()
    st.title("🎯 Support Case Dashboard")
    
    from services.openai_service import OpenAIService
    openai_service = OpenAIService()
    
    df, raw_cases = get_processed_data()
    filtered_df, active_owners = apply_filters_and_ranking(df)
    render_table(filtered_df, raw_cases, openai_service)

if __name__ == "__main__":
    main()