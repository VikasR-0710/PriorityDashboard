import streamlit as st
import plotly.graph_objects as go
import pandas as pd
from datetime import datetime, timedelta
import pytz

# Import existing SLA logic from your main file
from case_analysis.pages.Reporttopleft import (
    get_sf_connection,
    OWNER_REGION_MAP,
    get_sla_hours,
    add_sla_hours_with_weekend_skip,
    convert_to_ist,
    calculate_sla_deadline,
    calculate_sla_variance,
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
    'Vishal Mavi', 'Yogesh R', 'Zareena Bano', 'Zareena'
]

@st.cache_data(ttl=3600)
def get_active_sla_breach_data():
    """
    Fetches ACTIVE cases (New, Open, Assigned) from last 6 months.
    Reuses existing SLA logic from reporttopleft.py to determine breach status.
    Returns: (breached_df_for_chart, breached_records_for_table)
    """
    sf = get_sf_connection()
    
    owner_names_str = "', '".join(OWNER_LIST)
    
    # Fetch ACTIVE cases from last 6 months with CaseComments subquery
    query = f"""
        SELECT
            Id,
            CaseNumber,
            Subject,
            Owner.Name,
            Account.Name,
            Support_Level__c,
            Severity__c,
            CreatedDate,
            (SELECT CommentBody, CreatedBy.Name, CreatedDate, IsPublished 
             FROM CaseComments 
             WHERE IsPublished=true 
             ORDER BY CreatedDate DESC)
        FROM Case
        WHERE Owner.Name IN ('{owner_names_str}')
          AND CreatedDate = LAST_N_MONTHS:6
          AND Status IN ('New', 'Open', 'Assigned')
          AND Severity__c != null
    """
    
    try:
        result = sf.query_all(query)
        records = result["records"]
    except Exception as e:
        print(f"Error fetching active cases: {e}")
        return pd.DataFrame(), []

    if not records:
        return pd.DataFrame(), []

    df = pd.json_normalize(records)
    
    # Rename columns
    rename_map = {
        'Owner.Name': 'Case Owner',
        'Account.Name': 'Customer Name',
        'Support_Level__c': 'Support Level',
        'Severity__c': 'Severity',
        'CreatedDate': 'Created Date',
        'CaseComments.records': 'Comments',
        'Subject': 'Subject'
    }
    existing_cols = [col for col in rename_map.keys() if col in df.columns]
    df.rename(columns={k: rename_map[k] for k in existing_cols}, inplace=True)

    # Fill defaults
    df['Support Level'] = df['Support Level'].fillna('Standard')
    df['Severity'] = df['Severity'].fillna('S4')
    df['Case Owner'] = df['Case Owner'].fillna('UNKNOWN')
    df['Customer Name'] = df['Customer Name'].fillna('N/A')
    df['Subject'] = df['Subject'].fillna('')
    
    # Normalize support tier
    def normalize_support_level(support):
        if pd.isna(support):
            return 'Standard'
        support_lower = str(support).lower().strip()
        if 'premium' in support_lower or 'plus' in support_lower or 'p+' in support_lower:
            return 'Premium'
        return 'Standard'
    
    df['Support Tier'] = df['Support Level'].apply(normalize_support_level)
    
    # Collect breached cases for both chart aggregation AND detail table
    breached_chart_rows = []  # For stacked bar chart (aggregated)
    breached_table_rows = []  # For detail table (individual records)
    
    for _, row in df.iterrows():
        try:
            severity = row.get('Severity', 'S4')
            support_level = row.get('Support Level', 'Standard')
            case_owner = row.get('Case Owner', 'UNKNOWN')
            case_number = row.get('CaseNumber', 'N/A')
            customer_name = row.get('Customer Name', 'N/A')
            subject = row.get('Subject', '')
            comments = row.get('Comments', [])
            
            # Find last customer comment time (matching your get_processed_data logic)
            last_customer_comment_time = "N/A"
            if comments and isinstance(comments, list):
                for comment in comments:
                    if isinstance(comment, dict):
                        created_by = comment.get('CreatedBy', {})
                        if isinstance(created_by, dict) and created_by.get('Name') == 'Customer Support User':
                            created_date = comment.get('CreatedDate')
                            if created_date:
                                last_customer_comment_time = convert_to_ist(created_date)
                            break
            
            # If no customer comment, use CreatedDate
            if last_customer_comment_time == "N/A":
                created_date = row.get('Created Date')
                if created_date:
                    last_customer_comment_time = convert_to_ist(created_date)
            
            # Calculate SLA deadline using your existing function
            sla_hours = get_sla_hours(severity, support_level)
            
            if not sla_hours:
                continue  # Skip if no SLA defined
                
            sla_deadline = calculate_sla_deadline(last_customer_comment_time, sla_hours, support_level)
            
            # Check if breached using your existing function
            sla_text, sla_mins = calculate_sla_variance(sla_deadline)
            is_breached = isinstance(sla_mins, (int, float)) and sla_mins < 0
            
            if is_breached:
                # For chart: aggregate by month
                breach_month = datetime.now(pytz.timezone('Asia/Kolkata')).strftime('%Y-%m')
                breached_chart_rows.append({
                    'Case Owner': case_owner,
                    'Support Tier': df.loc[row.name, 'Support Tier'],
                    'Breach_Month': breach_month
                })
                
                # For table: store full record details
                breached_table_rows.append({
                    'Case Number': case_number,
                    'Customer Name': customer_name,
                    'Case Owner': case_owner,
                    'Support Level': support_level,
                    'Support Tier': df.loc[row.name, 'Support Tier'],
                    'Severity': severity,
                    'Subject': subject[:80] + '...' if len(subject) > 80 else subject,
                    'Last Customer Comment': last_customer_comment_time,
                    'SLA Deadline': sla_deadline,
                    'SLA Variance (mins)': int(sla_mins) if isinstance(sla_mins, (int, float)) else None,
                    'SLA Status': f"🚨 Overdue: {sla_text.split(': ')[1] if ': ' in sla_text else sla_text}"
                })
                
        except Exception as e:
            print(f"Error checking SLA breach for case: {e}")
            continue  # Skip problematic rows
    
    # Prepare chart data
    if breached_chart_rows:
        chart_df = pd.DataFrame(breached_chart_rows)
        breach_counts = chart_df.groupby(['Breach_Month', 'Support Tier']).size().reset_index(name='Breach_Count')
        pivot_df = breach_counts.pivot(index='Breach_Month', columns='Support Tier', values='Breach_Count').fillna(0)
        for tier in ['Standard', 'Premium']:
            if tier not in pivot_df.columns:
                pivot_df[tier] = 0
        pivot_df = pivot_df.sort_index().tail(6)
    else:
        pivot_df = pd.DataFrame()
    
    return pivot_df, breached_table_rows


def render_30_day_chart(active_owners):
    """
    Renders the SLA Breach Stacked Bar Chart (Last 6 Months) + Detail Table below.
    """
    st.markdown("<h3 style='color: #F8FAFC; margin-top: 0; margin-bottom: 10px;'>📊 Active SLA Breaches</h3>", unsafe_allow_html=True)

    with st.spinner("Analyzing active case SLA status..."):
        pivot_df, breached_records = get_active_sla_breach_data()

    # 🔒 Filter table records by selected owners (respects region/owner filters)
    if active_owners and breached_records:
        breached_records = [r for r in breached_records if r['Case Owner'] in active_owners]

    # ─────────────────────────────────────────────────────────────
    # 📈 STACKED BAR CHART
    # ─────────────────────────────────────────────────────────────
    with st.container(border=True, height=350): 
        if pivot_df.empty or pivot_df.sum().sum() == 0:
            st.markdown(
                "<div style='text-align:center; color:#94A3B8; padding:25px; font-size:14px;'>✨ No active SLA breaches for selected owners</div>",
                unsafe_allow_html=True
            )
        else:
            months = pivot_df.index.tolist()
            formatted_months = [datetime.strptime(m, '%Y-%m').strftime("%b '%y") for m in months]
            
            standard_counts = pivot_df['Standard'].astype(int).tolist()
            premium_counts = pivot_df['Premium'].astype(int).tolist()
            
            fig = go.Figure()
            
            fig.add_trace(go.Bar(
                x=formatted_months, y=standard_counts, name='Standard',
                marker_color='rgba(59, 130, 246, 0.9)',
                marker_line_color='rgba(37, 99, 235, 1)',
                marker_line_width=1,
                hovertemplate='<b>Standard Support</b><br>📅 %{x}<br>🔴 Breached: %{y}<extra></extra>'
            ))
            
            fig.add_trace(go.Bar(
                x=formatted_months, y=premium_counts, name='Premium',
                marker_color='rgba(16, 185, 129, 0.9)',
                marker_line_color='rgba(5, 150, 105, 1)',
                marker_line_width=1,
                hovertemplate='<b>Premium Support</b><br>📅 %{x}<br>🔴 Breached: %{y}<extra></extra>'
            ))
            
            total_breaches = sum(standard_counts) + sum(premium_counts)
            
            fig.update_layout(
                barmode='stack', height=330,
                margin=dict(l=45, r=15, t=25, b=50),
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                font=dict(color="#F8FAFC", family="Inter, sans-serif", size=11),
                xaxis=dict(title="", tickangle=-45, gridcolor='#334155', linecolor='#475569',
                          linewidth=1, tickfont=dict(size=10, color="#94A3B8"), showgrid=True, gridwidth=1),
                yaxis=dict(title="Breached Cases", gridcolor='#334155', linecolor='#475569',
                          linewidth=1, tickfont=dict(size=10, color="#94A3B8"),
                          title_font=dict(size=11, color="#CBD5E1"), showgrid=True, gridwidth=1,
                          zeroline=True, zerolinecolor='#475569'),
                legend=dict(orientation="h", yanchor="top", y=-0.18, xanchor="center", x=0.5,
                           font=dict(size=10, color="#E2E8F0"), bgcolor="rgba(30, 41, 59, 0.85)",
                           bordercolor="#475569", itemwidth=30),
                hoverlabel=dict(bgcolor="#1E293B", font_size=11, font_family="Inter, sans-serif", bordercolor="#475569"),
                annotations=[dict(x=0.5, y=1.02, xref="paper", yref="paper",
                                text=f"Total Active Breaches: <b>{total_breaches}</b>",
                                showarrow=False, font=dict(size=11, color="#94A3B8"),
                                bgcolor="rgba(30, 41, 59, 0.6)", borderpad=8, bordercolor="#475569", borderwidth=1)]
            )
            
            st.plotly_chart(fig, use_container_width=True, theme=None)

    # ─────────────────────────────────────────────────────────────
    # 📋 BREACHED CASES DETAIL TABLE (NEW)
    # ─────────────────────────────────────────────────────────────
    if breached_records:
        st.markdown("<div style='margin-top: 8px;'></div>", unsafe_allow_html=True)
        
        with st.expander(f"🔍 View {len(breached_records)} Breached Case Details", expanded=False):
            # Create DataFrame for table display
            table_df = pd.DataFrame(breached_records)
            
            # Select and order columns for display
            display_cols = [
                'Case Number', 'Customer Name', 'Case Owner', 'Severity', 
                'Support Level', 'SLA Status', 'SLA Deadline', 'Last Customer Comment', 'Subject'
            ]
            display_df = table_df[display_cols].copy()
            
            # Style: Highlight overdue status
            def style_sla_status(val):
                if 'Overdue' in str(val):
                    return 'color: #F87171; font-weight: 600;'
                return ''
            
            # Render compact table matching your dashboard styling
            st.dataframe(
                display_df.style.map(style_sla_status, subset=['SLA Status']),
                use_container_width=True,
                height=200,  # Scrollable within expander
                hide_index=True,
                column_config={
                    "Case Number": st.column_config.TextColumn("Case #", width="small"),
                    "Customer Name": st.column_config.TextColumn("Customer", width="medium"),
                    "Case Owner": st.column_config.TextColumn("Owner", width="small"),
                    "Severity": st.column_config.TextColumn("Sev", width="xsmall"),
                    "Support Level": st.column_config.TextColumn("Support", width="small"),
                    "SLA Status": st.column_config.TextColumn("Status", width="medium"),
                    "SLA Deadline": st.column_config.TextColumn("Deadline", width="small"),
                    "Last Customer Comment": st.column_config.TextColumn("Last Comment", width="small"),
                    "Subject": st.column_config.TextColumn("Subject", width="large"),
                }
            )
            
            # Quick stats footer
            premium_count = sum(1 for r in breached_records if r['Support Tier'] == 'Premium')
            standard_count = len(breached_records) - premium_count
            st.markdown(
                f"""
                <div style='text-align:right; font-size:11px; color:#94A3B8; margin-top:8px;'>
                    <b>{standard_count}</b> Standard • <b>{premium_count}</b> Premium breached cases
                </div>
                """,
                unsafe_allow_html=True
            )
    else:
        # No breached records to show
        st.markdown(
            "<div style='text-align:center; color:#64748B; padding:12px; font-size:12px; margin-top:8px; border:1px dashed #334155; border-radius:6px;'>📭 No breached case details to display</div>",
            unsafe_allow_html=True
        )

    # Footer note
    st.markdown(
        """
        <div style='text-align:center; font-size:11px; color:#64748B; margin-top:8px; opacity:0.9;'>
            Showing SLA breaches for New/Open/Assigned cases • Data refreshed hourly
        </div>
        """,
        unsafe_allow_html=True
    )