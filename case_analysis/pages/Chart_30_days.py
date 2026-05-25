import streamlit as st
import plotly.graph_objects as go
import pandas as pd

# Import necessary functions and maps from your main logic file
from case_analysis.pages.Reporttopleft import (
    get_sf_connection,
    calculate_score,
    get_project_support,
    OWNER_REGION_MAP
)

@st.cache_data(ttl=3600)
def get_closed_cases_data():
    """
    Fetches and processes exclusively CLOSED cases from the last 30 days.
    Uses LAST_N_DAYS:30 in SOQL to let Salesforce handle the date filtering efficiently.
    """
    sf = get_sf_connection()
    
    # We do not pull CaseComments here to drastically speed up the query
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
            CreatedDate,
            ClosedDate
        FROM Case
        WHERE Status = 'Closed' 
          AND ClosedDate = LAST_N_DAYS:30
          AND Owner.Name IN (
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
            'Vishal Mavi', 'Yogesh R', 'Zareena Bano', 'Zareena'
        )
    """
    result = sf.query_all(query)
    cases = result["records"]
    
    dashboard = []
    for case in cases:
        if case is None:
            continue
            
        owner_name = (case.get("Owner") or {}).get("Name", "UNKNOWN")
        customer_name = (case.get("Account") or {}).get("Name", "N/A")
        support_level = (case.get("Support_Level__c") or "N/A")
        
        # Override support logic for specific accounts
        project_id = case.get("AccountName__c")
        if (customer_name != "N/A" and "Xactly" in customer_name and project_id):
            try:
                cached_support = get_project_support(project_id)
                if cached_support:
                    support_level = cached_support
            except Exception as e:
                pass

        severity = (case.get("Severity__c") or "N/A")
        sevone = (case.get("SEVONE__c"))
        escalated = (case.get("IsEscalated") or False)

        # Calculate Priority Score
        case_score = calculate_score(sevone, severity, support_level, escalated)  
        
        dashboard.append({
            "Region": OWNER_REGION_MAP.get(owner_name, "UNKNOWN"),
            "Case Owner": owner_name,
            "Case Score": case_score,
            "Closed Date": case.get("ClosedDate")
        })

    return pd.DataFrame(dashboard)


def render_30_day_chart(active_owners):
    """
    Renders the Gauge Chart (30-Day Utilization Meter).
    Cross-references the active_owners list to sync UI filters (Region/Owner).
    """
    st.markdown("<h3 style='color: #F8FAFC; margin-top: 0; margin-bottom: 10px;'>📊 30-Day Utilization (Closed)</h3>", unsafe_allow_html=True)

    # 1. Fetch the dedicated 30-day closed data
    with st.spinner("Fetching Closed History..."):
        closed_df = get_closed_cases_data()

    # 2. Filter based on the dropdown selections
    if not active_owners:
        # If no regions/owners are selected, show empty chart
        recent_df = pd.DataFrame()
    else:
        if not closed_df.empty:
            # 👇 NEW: Filter directly against the active_owners list passed from main.py
            recent_df = closed_df[closed_df["Case Owner"].isin(active_owners)]
        else:
            recent_df = pd.DataFrame()

    # 3. Calculate scores
    total_score = recent_df["Case Score"].sum() if not recent_df.empty else 0
    selected_regions_count = recent_df["Region"].nunique() if not recent_df.empty else 0
    selected_owners_count = len(active_owners) # Show count based on selection, not just who has cases

    # Dynamic max scale
    max_score = max(total_score + 50, 100)

    with st.container(border=True, height=350): 
        st.markdown(
            f"""
            <div style='text-align:center;
                        font-size:18px;
                        font-weight:600;
                        color:#F8FAFC; 
                        margin-bottom:-15px'>
            {selected_regions_count} Region(s) | {selected_owners_count} Owner(s)
            </div>
            """,
            unsafe_allow_html=True
        )

        fig = go.Figure(go.Indicator(
            mode="gauge+number",
            value=total_score,
            domain={'x':[0,1], 'y':[0.15,0.9]}, 
            number={"font":{"size":50, "color": "#F8FAFC"}},
            gauge={
                'axis':{
                    'range':[0,max_score],
                    'tickwidth':1,
                    'tickcolor': "#F8FAFC",
                    'tickfont': dict(color="#F8FAFC", size=12)
                },
                'bar':{'color':'rgba(0, 150, 255, 0.85)', 'thickness':0.35},
                'steps':[
                    {'range':[0,max_score*0.4],'color':'rgba(173, 216, 230, 0.3)'},
                    {'range':[max_score*0.4,max_score*0.75],'color':'rgba(135, 206, 250, 0.4)'},
                    {'range':[max_score*0.75,max_score],'color':'rgba(70, 130, 180, 0.5)'}
                ],
                'threshold':{
                    'line':{'color':'#FFFFFF', 'width':5},
                    'thickness':0.9,
                    'value':total_score
                }
            }
        ))

        fig.update_layout(
            height=330,   
            margin=dict(l=15, r=15, t=40, b=15),
            paper_bgcolor="rgba(0,0,0,0)", 
            plot_bgcolor="rgba(0,0,0,0)",  
            font=dict(color="#F8FAFC")     
        )
        st.plotly_chart(fig, use_container_width=True, theme=None)

        if selected_owners_count == 1 and active_owners:
            owner = active_owners[0]
            st.markdown(
                f"""
                <div style='text-align:center;
                            font-size:15px;
                            font-weight:bold;
                            color:#94A3B8;
                            margin-top: -10px;'>
                 {owner} (Last 30 Days)
                </div>
                """,
                unsafe_allow_html=True
            )