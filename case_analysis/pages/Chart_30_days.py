import streamlit as st
import plotly.graph_objects as go
import pandas as pd
from datetime import datetime, timedelta

# Import necessary functions and maps from your main logic file
from case_analysis.pages.Reporttopleft import (
    get_sf_connection,
    calculate_score,
    OWNER_REGION_MAP
)

# Define the owner list locally to avoid importing huge lists repeatedly if possible, 
# or keep using the imported map keys.
OWNER_LIST = [
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
    'Vishal Mavi', 'Yogesh R', 'Zareena Bano', 'Zareena'
]

@st.cache_data(ttl=3600)
@st.cache_data(ttl=3600)
def get_closed_cases_data():
    """
    Fetches CLOSED cases from the last 30 days.
    Optimized: Minimal fields, no nested loops for API calls.
    Robust handling of missing columns.
    """
    sf = get_sf_connection()
    
    # Format owner list for SOQL IN clause
    owner_names_str = "', '".join(OWNER_LIST)
    
    query = f"""
        SELECT
            Id,
            CaseNumber,
            Owner.Name,
            Account.Name,
            Support_Level__c,
            Severity__c,
            Sevone__c,
            IsEscalated,
            ClosedDate
        FROM Case
        WHERE Status = 'Closed' 
          AND ClosedDate = LAST_N_DAYS:30
          AND Owner.Name IN ('{owner_names_str}')
    """
    
    try:
        result = sf.query_all(query)
        records = result["records"]
    except Exception as e:
        st.error(f"Error fetching closed cases: {e}")
        return pd.DataFrame(columns=["Region", "Case Owner", "Case Score", "Closed Date"])

    if not records:
        return pd.DataFrame(columns=["Region", "Case Owner", "Case Score", "Closed Date"])

    # Convert to DataFrame immediately for vectorized processing
    df = pd.json_normalize(records)
    
    # Rename columns to match expected schema
    # Note: json_normalize flattens nested dicts like Owner.Name -> Owner.Name
    rename_map = {
        'Owner.Name': 'Case Owner',
        'Account.Name': 'Customer Name',
        'Support_Level__c': 'Support Level',
        'Severity__c': 'Severity',
        'Sevone__c': 'Sevone',
        'IsEscalated': 'Escalated',
        'ClosedDate': 'Closed Date'
    }
    
    # Only rename columns that actually exist in the dataframe to avoid KeyError
    existing_cols = [col for col in rename_map.keys() if col in df.columns]
    df.rename(columns={k: rename_map[k] for k in existing_cols}, inplace=True)

    # Ensure all required columns exist, even if they were dropped by pandas due to all-nulls
    required_cols = ['Case Owner', 'Support Level', 'Severity', 'Sevone', 'Escalated', 'Closed Date']
    for col in required_cols:
        if col not in df.columns:
            df[col] = None  # Create column with None/NaN if missing

    # Fill NaNs safely
    df['Support Level'] = df['Support Level'].fillna('Standard')
    df['Severity'] = df['Severity'].fillna('S4')
    
    # Handle Sevone: It might be boolean or string depending on SF setup. 
    # Ensure it's treated as boolean for calculate_score
    if 'Sevone' in df.columns:
        # If it's already boolean, fillna works. If it's object/string, convert first.
        if df['Sevone'].dtype == 'object':
             df['Sevone'] = df['Sevone'].apply(lambda x: True if x else False)
        else:
             df['Sevone'] = df['Sevone'].fillna(False)
    else:
        df['Sevone'] = False

    if 'Escalated' in df.columns:
         if df['Escalated'].dtype == 'object':
             df['Escalated'] = df['Escalated'].apply(lambda x: True if x else False)
         else:
             df['Escalated'] = df['Escalated'].fillna(False)
    else:
        df['Escalated'] = False
        
    df['Case Owner'] = df['Case Owner'].fillna('UNKNOWN')

    # Map Region
    df['Region'] = df['Case Owner'].map(OWNER_REGION_MAP).fillna('UNKNOWN')

    # Calculate Score Vectorially
    # Note: calculate_score expects individual values, so we apply it row-wise 
    # but this is still faster than the previous loop because we aren't making API calls.
    df['Case Score'] = df.apply(
        lambda row: calculate_score(
            row['Sevone'], 
            row['Severity'], 
            row['Support Level'], 
            row['Escalated']
        ), 
        axis=1
    )

    # Keep only necessary columns for the chart
    return df[['Region', 'Case Owner', 'Case Score', 'Closed Date']]


def render_30_day_chart(active_owners):
    """
    Renders the Gauge Chart (30-Day Utilization Meter).
    """
    st.markdown("<h3 style='color: #F8FAFC; margin-top: 0; margin-bottom: 10px;'>📊 30-Day Utilization (Closed)</h3>", unsafe_allow_html=True)

    # 1. Fetch the dedicated 30-day closed data
    # The cache handles the heavy lifting. If data is cached, this is instant.
    # If not, it runs the optimized query above.
    with st.spinner("Fetching Closed History..."):
        closed_df = get_closed_cases_data()

    # 2. Filter based on the dropdown selections passed from main.py
    if not active_owners:
        recent_df = pd.DataFrame()
    else:
        if not closed_df.empty:
            # Filter directly against the active_owners list
            recent_df = closed_df[closed_df["Case Owner"].isin(active_owners)]
        else:
            recent_df = pd.DataFrame()

    # 3. Calculate scores
    total_score = recent_df["Case Score"].sum() if not recent_df.empty else 0
    selected_regions_count = recent_df["Region"].nunique() if not recent_df.empty else 0
    selected_owners_count = len(active_owners) 

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