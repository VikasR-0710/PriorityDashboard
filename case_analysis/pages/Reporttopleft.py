import streamlit as st
import pandas as pd
from services.case_service import CaseService
from services.case_service import SalesforceConnector
from datetime import datetime, timedelta
import pytz

service=CaseService()
sf=service.get_connection()

# ---------------------------------------------------
# CONFIGURATION & CSS
# ---------------------------------------------------

OWNER_REGION_MAP = {

    # APAC
    "Sakthi Devi SK": "APAC",
    "Mohamed Ramzin": "APAC",
    "Syeda Sajida": "APAC",
    "Yogesh R": "APAC",
    "Ganesh Babu": "APAC",
    "Srinivas Aaguri": "APAC",

    # EMEA
    "Sindhu M Y": "EMEA",
    "Payal Gupta": "EMEA",
    "Poonam Pandey": "EMEA",
    "Mugilan Gowthaman": "EMEA",
    "Santosh Veduruvada": "EMEA",
    "Sivagnana Bharathi Nagaraj": "EMEA",
    "Ullas Shenoy": "EMEA",
    "Vipul SG": "EMEA",
    "Vilas Potadar": "EMEA",
    "Chethan Kumar P.": "EMEA",
    "Chandra Sai Surya Santosh Veduruvada": "EMEA",

    # NA EAST
    "Aqsa Pandith": "NA EAST",
    "Prabu R": "NA EAST",
    "Vikas R": "NA EAST",
    "Tarun Buthala": "NA EAST",
    "Gnanasiri Pechetti": "NA EAST",
    "Shivendra Yadav": "NA EAST",
    "Kaushik Patowary": "NA EAST",
    "Shahrukh Shahzad": "NA EAST",
    "Amit Bhojak": "NA EAST",
    "Mohammed Usman": "NA EAST",
    "Santi Sahoo": "NA EAST",
    "Nilanjan Roy": "NA EAST",
    "Nupur Rao": "NA EAST",
    "Rohit Nargundkar": "NA EAST",
    "Prabu Rajendran": "NA EAST",
    "Palak Kharche": "NA EAST",
    "Pooja Singh": "NA EAST",
    "Becca Lozano": "NA EAST",


    # NA WEST
    "Selvin Raja": "NA WEST",
    "Shakti Prasad Pati": "NA WEST",
    "Sanjay Kademani": "NA WEST",
    "Shreyas G Nambiar": "NA WEST",
    "Vishal Mavi": "NA WEST",
    "Infant Raj.": "NA WEST",
    "Pallavi M R": "NA WEST",
    "Aniket Chinde": "NA WEST",
    "Kalyan Kumar": "NA WEST",
    "Amit Kumar": "NA WEST",
    "Karthik Dosapati": "NA WEST",
    "Peter Kyller": "NA WEST",
    "Anthony Pham": "NA WEST",
    "ZAREENA BANO": "NA WEST",
    "Karalie Murray": "NA WEST",

    #Premium Plus
    "Sushmitha Rayalkeri": "P+",
    "Amith Gujjar": "P+",
    "Monika Sihag": "P+",
    "Mohammad Raza": "P+",
    "Sumit Paul": "P+",
    "Imari Killikelly": "P+",
    "Merlyn Pushparaj": "P+",
    "Naveen Kumar Surisetti": "P+",
}



def inject_custom_css():

    st.markdown("""

<style>
    /* Nuke Streamlit's automatic multi-page nav sidebar elements completely */
    [data-testid="stSidebar"] { display: none !important; }
    [data-testid="collapsedControl"] { display: none !important; }
    
    .main { padding-top:10px; }
    .block-container { padding-top:1rem; }
    h1 { font-size:42px !important; font-weight:800 !important; }
    [data-testid="stHorizontalBlock"] { gap:0.2rem; }
    p { font-size:12px !important; }
    button { font-size:11px !important; padding:0.1rem !important; }        
    </style>

    """,unsafe_allow_html=True)


@st.cache_resource
def get_sf_connection():
    service=CaseService()
    return service.get_connection()

# ---------------------------------------------------
# BUSINESS LOGIC
# ---------------------------------------------------

def calculate_score(
    sevone,
    severity,
    support_level,
    escalated
):

    if sevone:
        return 14

    if escalated:
        return 13

    score_map={

        ("S1","Premium Plus"):12,
        ("S1","Premium (24x7)"):11,
        ("S1","Standard"):10,

        ("S2","Premium Plus"):9,
        ("S2","Premium (24x7)"):8,
        ("S2","Standard"):7,

        ("S3","Premium Plus"):6,
        ("S3","Premium (24x7)"):5,
        ("S3","Standard"):4,

        ("S4","Premium Plus"):3,
        ("S4","Premium (24x7)"):2,
        ("S4","Standard"):1
    }

    return score_map.get(
        (severity,support_level),
        0
    )

def get_sla_hours(severity, support_level):
    """
    Returns the SLA response time in HOURS (float) based on Severity and Support Level.
    """
    if not severity or severity == "N/A":
        return None
    
    # Normalize support level for matching
    sl_lower = support_level.lower() if support_level else ""
    
    # Check if Premium (covers 'Premium Plus' and 'Premium (24x7)')
    is_premium = "premium" in sl_lower
    
    # Mapping based on your table
    sla_map = {
        "S1": {"premium": 0.5, "standard": 1.0},   # 30 mins vs 60 mins
        "S2": {"premium": 1.0, "standard": 4.0},   # 1 hour vs 4 hours
        "S3": {"premium": 2.0, "standard": 6.0},   # 2 hours vs 6 hours
        "S4": {"premium": 6.0, "standard": 8.0},   # 6 hours vs 8 hours
    }
    
    severity_key = severity.strip().upper()
    
    # Handle variations of S1/SevOne
    if severity_key.startswith("SEV") or severity_key == "SEVONE":
         severity_key = "S1" 
    elif severity_key not in ["S1", "S2", "S3", "S4"]:
        return None

    tier = "premium" if is_premium else "standard"
    
    try:
        return sla_map[severity_key][tier]
    except KeyError:
        return None

def calculate_sla_deadline(last_comment_time_str, sla_hours):
    """
    Calculates the deadline timestamp in IST.
    Input: last_comment_time_str (format: "dd-Mon HH:MM" from convert_to_ist)
    Output: String deadline in IST "dd-Mon HH:MM" or "N/A"
    """
    if not last_comment_time_str or last_comment_time_str == "N/A" or sla_hours is None:
        return "N/A"
    
    try:
        # Parse the IST time string back to a datetime object
        ist = pytz.timezone("Asia/Kolkata")
        now_ist = datetime.now(ist)
        current_year = now_ist.year
        
        dt_comment = datetime.strptime(f"{current_year} {last_comment_time_str}", "%Y %d-%b %H:%M")
        dt_comment = ist.localize(dt_comment)
        
        # Add SLA hours
        deadline_dt = dt_comment + timedelta(hours=sla_hours)
        
        # Format back to string
        return deadline_dt.strftime("%d-%b %H:%M")
        
    except Exception as e:
        # Fallback if parsing fails
        return "N/A"


@st.cache_data(ttl=3600)
def get_project_support(project_id):
    sf=get_sf_connection()
    account_query = f"""
    SELECT Name
    FROM Account
    WHERE Id='{project_id}'
    LIMIT 1
    """

    account_result = sf.query(
        account_query
    )

    if not account_result["records"]:
        return None

    project_name = (
        account_result["records"][0]
        .get("Name")
    )

    support_query = f"""
    SELECT Support_Level__c
    FROM Case
    WHERE Account.Name LIKE '%{project_name}%'
    AND Support_Level__c != NULL
    LIMIT 1
    """

    support_result = sf.query(
        support_query
    )

    if support_result["records"]:

        return (
            support_result["records"][0]
            .get(
                "Support_Level__c"
            )
        )

    return None

def fetch_cases():
    sf=get_sf_connection()

    
      
    query = """
        SELECT
            Id,
            CaseNumber,
            Subject,
            Status,
            Owner.Name,
            Account.Name,
            AccountName__c,
            Support_Level__c,
            Severity__c,
            Sevone__c,
            IsEscalated,
            (select CreatedBy.Name,
            CreatedDate,
            IsPublished from CaseComments where IsPublished=true order by CreatedDate Desc)
            FROM Case
            WHERE Status IN ('New', 'Open', 'Assigned') and  Owner.Name IN (
            'Amit Bhojak', 'Amit Kumar', 'Amith Gujjar', 'Aniket Chinde',
            'Anthony Pham', 'Aqsa Pandith', 'Becca Lozano', 'Chethan Kumar P.', 'Ganesh Babu',
            'Gnanasiri Pechetti', 'Imari Killikelly', 'Infant Raj.', 'Ishaq Mathina', 
            'Kalyan Kumar', 'Karalie Murray', 'Karthik Dosapati', 'Kaushik Patowary', 'Mahesh P M',
            'Merlyn Pushparaj', 'Mohamed Ramzin', 'Mohammad Raza', 'Mohammed Usman', 'Monika Sihag',
            'Mugilan Gowthaman', 'Naveen Kumar Surisetti', 'Nilanjan Roy', 'Nupur Rao', 'Palak Kharche',
            'Pallavi M R', 'Payal Gupta', 'Peter Kyller', 'Pooja Singh', 'Poonam Pandey',
            'Prabu Rajendran', 'Prabu R', 'Rohit Nargundkar', 'Sakthi Devi SK', 'Sanjay Kademani',
            'Santosh Veduruvada', 'Santi Sahoo', 'Selvin Raja', 'Shahrukh Shahzad', 'Shakti Prasad Pati',
            'Shreyas G Nambiar', 'Shivendra Yadav', 'Sindhu M Y', 'Sivagnana Bharathi Nagaraj', 'Sivaji Koya',
            'Srinivas Aaguri', 'Sumit Paul', 'Sumit', 'Sushmitha Rayalkeri', 'Syeda Sajida',
            'Tarun Buthala', 'Ullas Shenoy', 'Vikas R', 'Vilas Potadar', 'Vipul SG',
            'Vishal Mavi', 'Yogesh R', 'Zareena Bano', 'Zareena')"""
    result=sf.query_all(query)
    return result["records"]





def convert_to_ist(date_string):

    if not date_string or date_string=="N/A":
        return "N/A"

    try:

        utc_time = datetime.strptime(
            date_string,
            "%Y-%m-%dT%H:%M:%S.000+0000"
        )

        utc_time = pytz.utc.localize(
            utc_time
        )

        ist = pytz.timezone(
            "Asia/Kolkata"
        )

        ist_time = utc_time.astimezone(
            ist
        )

        return ist_time.strftime(
            "%d-%b %H:%M"
        )

    except:
        return date_string


def get_processed_data():

    with st.spinner(
        "Fetching Salesforce Cases..."
    ):
    

        cases=fetch_cases()

    if "sentiments" not in st.session_state:

        st.session_state.sentiments={}

    dashboard=[]

    for case in cases:

        if case is None:
            continue

        owner_name=(
            case.get("Owner") or {}
        ).get(
            "Name",
            "UNKNOWN"
        )

        customer_name = (
            case.get("Account") or {}
        ).get(
            "Name",
            "N/A"
        )

        support_level = (
            case.get(
                "Support_Level__c"
            ) or "N/A"
        )

        # ---------------------------
        # Xactly account override logic
        # ---------------------------

        project_id = case.get(
            "AccountName__c"
        )

        if (
            customer_name != "N/A"
            and "Xactly" in customer_name
            and project_id
        ):

            try:
                

                cached_support = (
                    get_project_support(
                        project_id
                    )
                )

                if cached_support:

                    support_level = (
                        cached_support
                    )

            except Exception as e:

                print(
                    f"Xactly override failed: {e}"
                )

        severity=(
            case.get(
                 "Severity__c"
              )
              or "N/A"
        )

        sevone=(
            case.get(
                 "SEVONE__c"
              )
        )

        escalated=(
            case.get(
                "IsEscalated"
            ) or False
        )

        case_score=calculate_score(
          sevone,
          severity,
         support_level,
         escalated
        )  
        
        # 1. Get SLA Hours duration
        sla_hours_duration = get_sla_hours(severity, support_level)      



        last_commenter="Internal Comment"
        last_customer_comment_time="N/A"



        comments=(
            case.get(
                "CaseComments"
            ) or {}
        ).get(
            "records",
            []
        )



        if comments:

            latest=comments[0]

            created_by=(
                latest.get(
                    "CreatedBy"
                ) or {}
            ).get(
                "Name",
                ""
            )

            if created_by in OWNER_REGION_MAP:

                last_commenter="Support Comment"

            else:

                last_commenter="Customer Comment"

            for comment in comments:
                comment_user=(
                    comment.get(
                        "CreatedBy"
                    ) or {}
                ).get(
                    "Name",""
                )
                if comment_user == 'Customer Support User':
                    last_customer_comment_time=convert_to_ist(
                        comment.get(
                            "CreatedDate"
                        )
                        or "N/A"
                    )
                    break
        
        # 2. Calculate SLA Deadline Timestamp
        sla_deadline_time = calculate_sla_deadline(last_customer_comment_time, sla_hours_duration)


        dashboard.append({

            "Region":OWNER_REGION_MAP.get(
                owner_name,
                "UNKNOWN"
            ),

            "Case Number":case.get(
                "CaseNumber",
                "N/A"
            ),

            "Customer Name":customer_name,

            "Case Owner":owner_name,

            "Support Level":support_level,
            "Severity":severity,

            "Status":case.get(
                "Status",
                "N/A"
            ),

            "Escalated":escalated,

            "Last Comment By":last_commenter,

            "Sentiment":
            st.session_state.sentiments.get(
                case.get("CaseNumber"),
                "Not Analyzed"
            ),
            "Case Score":case_score,
            "Last Customer Comment":last_customer_comment_time,
            "SLA Response Time": sla_deadline_time
        })

    return pd.DataFrame(
        dashboard
    ),cases



def apply_filters_and_ranking(df):
    c1, c2 = st.columns(2)

    with c1:
        regions = sorted(df["Region"].dropna().unique())
        selected_regions = st.multiselect(
            ":earth_africa: Region", regions, default=[]
        )

    if selected_regions:
        temp_df = df[df["Region"].isin(selected_regions)]
        available_owners = sorted(temp_df["Case Owner"].dropna().unique())
    else:
        temp_df = df.iloc[:0]  # 👈 Empty DF but KEEPS all columns
        available_owners = []

    with c2:
        selected_owners = st.multiselect(
            ":bust_in_silhouette: Owner", available_owners, default=[]
        )

    # 👇 Return schema-safe empty DF if no region selected
    if not selected_regions:
        return temp_df

    if selected_owners:
        filtered_df = temp_df[temp_df["Case Owner"].isin(selected_owners)]
    else:
        filtered_df = temp_df

    if not filtered_df.empty:
        filtered_df = filtered_df.sort_values(
            by=["Case Owner", "Case Score"], ascending=[True, False]
        )
        filtered_df["Sequential_Rank"] = filtered_df.groupby("Case Owner").cumcount() + 1

    return filtered_df






# ---------------------------------------------------
# TABLE
# ---------------------------------------------------

def render_table(filtered_df, cases, openai_service):
    st.subheader(":clipboard: AI Case Monitoring")
    
    # 👈 Show a clean message when no filters are selected
    if filtered_df.empty:
        st.info("👈 Please select at least one **Region** to view cases.")
        return

    report_box = st.container(height=350)

    with report_box:

        # UPDATED WIDTHS: 

        col_widths = [1, 1.2, 2.8, 3.0, 2, 1.0, 1.0, 1.2, 1.5, 2.5, 2.0, 2.2, 0.8]
        
        headers = st.columns(col_widths)
        headers[0].write("**Region**")
        headers[1].write("**Case**")
        headers[2].write("**Customer**")
        headers[3].write("**Owner**")
        headers[4].write("**Support Level**")
        headers[5].write("**Severity**")
        headers[6].write("**Status**")
        headers[7].write("**Escalated**")
        headers[8].write("**Sentiment**")
        headers[9].write("**Last Comment**")
        headers[10].write("**LCC Time**")
        headers[11].write("**SLA Deadline**") # New Column Header
        headers[12].write("**Rank**")

        st.markdown("---")
        
        for index, row in filtered_df.iterrows():
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
            
            # New SLA Column - Shows the calculated deadline time
            cols[11].write(row["SLA Response Time"])
            
            cols[12].markdown(f"<div style='color: #FFFFFF; font-weight: 600; font-size: 14px;'>{row['Sequential_Rank']}</div>", unsafe_allow_html=True)