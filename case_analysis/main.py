import sys
import os
sys.path.append(os.getcwd())

import streamlit as st
from case_analysis.services.openai_service import OpenAIService

# Pull all configurations, logic, and rendering from Reporttopleft
from case_analysis.pages.Reporttopleft import (
    inject_custom_css, 
    get_processed_data, 
    apply_filters_and_ranking, 
    render_table
)
from case_analysis.pages.Charttopright import render_chart

# ---------------------------------------------------
# 1. PAGE LAYOUT CONFIG & STATE
# ---------------------------------------------------
st.set_page_config(
    page_title="Prioritization Dashboard", 
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Initialize a session state variable for the dynamic color
if 'accent_color' not in st.session_state:
    st.session_state.accent_color = "#3B82F6"  # Premium Corporate Blue

# Toggle thematic styles professionally
if st.button("🎨 Toggle Accent Theme (Blue / Slate)"):
    if st.session_state.accent_color == "#3B82F6":
        st.session_state.accent_color = "#64748B"  # Professional Slate Muted Grey
    else:
        st.session_state.accent_color = "#3B82F6"  # Premium Corporate Blue

# Inject existing custom CSS from your imports
inject_custom_css()

# Inject Refined, Professional UI Styles
st.markdown(
    f"""
    <style>
    /* Modern Slate Dark Theme Base */
    .stApp {{
        background-color: #0F172A; /* Deep Slate/Navy Blue Black */
        color: #F8FAFC; /* Crisp text */
    }}
    
    /* Clean, professional horizontal dividers */
    hr {{
        border: 0;
        height: 1px;
        background: linear-gradient(to right, {st.session_state.accent_color}, transparent);
        margin: 1.5rem 0;
    }}
    
    /* Target ONLY top-level dashboard columns inside our main block */
    .main-dashboard-row [data-testid="stColumn"] {{
        background-color: #1E293B !important; 
        padding: 1.5rem !important;
        border-radius: 12px !important;
        border: 1px solid #334155 !important;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
    }}

    /* Reset styles for columns inside your tables/widgets so they don't break */
    .main-dashboard-row [data-testid="stColumn"] [data-testid="stColumn"] {{
        background-color: transparent !important;
        padding: 0px !important;
        margin: 0px !important;
        border: none !important;
        box-shadow: none !important;
    }}

    /* --- INCREASE TABLE FONT SIZE --- */
    /* Target the text inside the table container specifically */
    .main-dashboard-row [data-testid="stColumn"]:first-child p,
    .main-dashboard-row [data-testid="stColumn"]:first-child div[data-testid="stHorizontalBlock"] p {{
        font-size: 14px !important; /* Increased from default ~12px */
        line-height: 1.4 !important;
    }}
    
    /* Make headers bold and slightly larger */
    .main-dashboard-row [data-testid="stColumn"]:first-child h1,
    .main-dashboard-row [data-testid="stColumn"]:first-child h2,
    .main-dashboard-row [data-testid="stColumn"]:first-child h3,
    .main-dashboard-row [data-testid="stColumn"]:first-child h4 {{
        font-size: 1.2rem !important;
        color: #FFFFFF !important;
    }}

    /* Widget Labels styling */
    label, label p, label span {{
        color: #94A3B8 !important; 
        font-weight: 500 !important;
        font-size: 0.9rem !important;
        letter-spacing: 0.5px;
    }}

    /* Premium Button overrides */
    div[data-testid="stButton"] button {{
        background-color: #1E293B !important;
        border: 1px solid #334155 !important;
        border-radius: 6px !important;
        transition: all 0.2s ease-in-out;
    }}
    
    div[data-testid="stButton"] button p {{
        color: #E2E8F0 !important;
        font-weight: 500 !important;
    }}
    
    div[data-testid="stButton"] button:hover {{
        border-color: {st.session_state.accent_color} !important;
        box-shadow: 0 0 10px {st.session_state.accent_color}40;
    }}

    /* Clean, Modern Corporate Title */
    .dashboard-title {{
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif !important;
        color: #FFFFFF !important;
        font-size: 2rem !important; 
        font-weight: 700 !important;
        letter-spacing: -0.5px !important;
        margin-bottom: 4px !important;
    }}
    .dashboard-subtitle {{
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif !important;
        color: #94A3B8 !important;
        font-size: 0.95rem !important;
        margin-bottom: 20px !important;
    }}
    .accent-bar {{
        height: 4px;
        width: 60px;
        background-color: {st.session_state.accent_color};
        border-radius: 2px;
        margin-bottom: 25px;
    }}

 
    </style>
    """,
    unsafe_allow_html=True
)

# ---------------------------------------------------
# 2. EXECUTIVE HEADER SECTION
# ---------------------------------------------------
st.markdown('<div class="dashboard-title">GCS Prioritization and Utilization Dashboard</div>', unsafe_allow_html=True)
st.markdown(f'<div class="accent-bar"></div>', unsafe_allow_html=True)

# ---------------------------------------------------
# 3. RUN EXTRACTIONS, FILTERS & SELECTION LOGIC
# ---------------------------------------------------
df, cases = get_processed_data()
filtered_df = apply_filters_and_ranking(df)

# ---------------------------------------------------
# 4. CONCURRENT UI ELEMENTS (LAYOUT)
# ---------------------------------------------------
st.markdown('<div class="main-dashboard-row">', unsafe_allow_html=True)

# CHANGED: Ratio [3, 1] gives 75% width to Table and 25% to Chart
left, right = st.columns([3, 1], gap="large")

with left:
    render_table(filtered_df, cases, OpenAIService())

with right:
    render_chart(filtered_df)

st.markdown('</div>', unsafe_allow_html=True)

# ---------------------------------------------------
# 5. FOOTER
# ---------------------------------------------------
st.markdown("---")
st.caption("🔄 **Data Sync Status:** Dashboard auto-refreshes every 3 minutes directly from Salesforce CRM.")