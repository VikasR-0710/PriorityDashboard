import streamlit as st
import plotly.graph_objects as go
import pandas as pd
from datetime import datetime, timedelta
import pytz

from case_analysis.pages.CasePriorityIndex import (
    get_sf_connection, OWNER_REGION_MAP, is_generalized_comment,
    get_sla_hours, convert_to_ist_dt, calculate_sla_deadline, calculate_sla_variance,
)

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
    'Vishal Mavi', 'Yogesh R', 'Zareena Bano', 'Zareena','Joshua Halle'
]

@st.cache_data(ttl=3600)
def get_all_breach_records():
    sf = get_sf_connection()
    owner_names_str = "', '".join(OWNER_LIST)
    
    # UPDATED: Added Heal_Desk__c to the query
    query = f"""SELECT Id, CaseNumber, Subject, Owner.Name, Account.Name, Support_Level__c, Severity__c, CreatedDate, Heal_Desk__c,
               (SELECT CommentBody, CreatedBy.Name, CreatedDate, IsPublished FROM CaseComments WHERE IsPublished=true ORDER BY CreatedDate DESC)
        FROM Case WHERE Owner.Name IN ('{owner_names_str}')
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
            subject = row.get('Subject', '')
            comments = row.get('Comments', [])
            
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
                
                latest_is_support = latest_author in OWNER_REGION_MAP
                latest_is_gen = is_generalized_comment(latest.get('CommentBody', ''))
                
                if latest_is_support and not latest_is_gen:
                    sla_start_dt = convert_to_ist_dt(latest.get('CreatedDate'))

            effective_start_dt = sla_start_dt if sla_start_dt else last_customer_comment_dt
            if effective_start_dt is None:
                created_date = row.get('Created Date')
                if created_date: effective_start_dt = convert_to_ist_dt(created_date)

            sla_hours = get_sla_hours(severity, support_level)
            if not sla_hours: continue
            
            sla_deadline_dt = calculate_sla_deadline(effective_start_dt, sla_hours, support_level)
            
            # UPDATED: Pass support_level to trigger the weekend pause logic!
            sla_text, sla_mins = calculate_sla_variance(sla_deadline_dt, support_level)
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
                    'Is_Heal_Desk': bool(row.get('Heal_Desk__c')) # Added Heal Desk flag
                })
        except Exception as e:
            print(f"⚠️ Chart SLA Calc Error: {e}")
            continue
            
    return pd.DataFrame(all_breaches) if all_breaches else pd.DataFrame()


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
