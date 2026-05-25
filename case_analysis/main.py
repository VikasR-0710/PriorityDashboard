import sys
import os
# Add current directory to path to allow imports from subfolders
sys.path.append(os.getcwd())

import streamlit as st
from case_analysis.services.openai_service import OpenAIService

# Import specific functions from the page modules. 
# Note: Importing from 'pages' suggests a multi-page app structure, 
# but here they are used as modular components for the main dashboard.
from case_analysis.pages.Reporttopleft import (
    inject_custom_css, 
    get_processed_data, 
    apply_filters_and_ranking, 
    render_table
)
from case_analysis.pages.Charttopright import render_chart

# ---------------------------------------------------
# 0. HELPER FUNCTIONS FOR REFRESH
# ---------------------------------------------------
def refresh_dashboard():
    """
    Clears ALL caches and session state to force a complete 
    reload of data from sources (Salesforce, APIs, etc.)
    
    This is crucial because Streamlit caches data (@st.cache_data) to improve performance.
    Without this, clicking 'Refresh' might just show old cached data.
    """
    # 1. Clear Streamlit Data Cache (covers @st.cache_data)
    # This forces get_processed_data() to re-run the Salesforce query next time it's called.
    st.cache_data.clear()
    
    # 2. Clear Streamlit Resource Cache (covers @st.cache_resource)
    # This forces the Salesforce connection object to be recreated.
    st.cache_resource.clear()
    
    # 3. Clear specific Session State keys related to UI filters/state
    # We remove user selections (like selected regions) so the dashboard resets to default view.
    keys_to_clear = [
        'filter_case_id', 
        'filter_region', 
        'filter_status',
        'expanded_rows',
        'selected_cases'
    ]
    for key in keys_to_clear:
        if key in st.session_state:
            del st.session_state[key]
    
    # 4. Force a full script rerun
    # Immediately restarts the script from top to bottom with clean state.
    st.rerun()

# ---------------------------------------------------
# 1. PAGE LAYOUT CONFIG & STATE
# ---------------------------------------------------
st.set_page_config(
    page_title="Prioritization Dashboard", 
    page_icon="📊",
    layout="wide", # Uses full browser width
    initial_sidebar_state="collapsed" # Hides sidebar by default for a cleaner look
)

# Initialize a session state variable for the dynamic accent color
# This allows the theme toggle button to persist its state across reruns.
if 'accent_color' not in st.session_state:
    st.session_state.accent_color = "#3B82F6"  # Default: Premium Corporate Blue

# Toggle thematic styles professionally
# When clicked, swaps between Blue and Slate Grey accent colors.
if st.button("🎨 Toggle Accent Theme (Blue / Slate)"):
    if st.session_state.accent_color == "#3B82F6":
        st.session_state.accent_color = "#64748B"  # Switch to Slate
    else:
        st.session_state.accent_color = "#3B82F6"  # Switch back to Blue

# Inject existing custom CSS from your imports (handles sidebar hiding, etc.)
inject_custom_css()

# Inject Refined, Professional UI Styles
# This block uses f-strings to inject dynamic CSS based on the selected accent color.
st.markdown(
    f"""
    <style>
    /* Modern Slate Dark Theme Base */
    .stApp {{
        background-color: #0F172A; /* Deep Slate/Navy Blue Black */
        color: #F8FAFC; /* Crisp white/grey text for contrast */
    }}
    
    /* Clean, professional horizontal dividers */
    hr {{
        border: 0;
        height: 1px;
        background: linear-gradient(to right, {st.session_state.accent_color}, transparent);
        margin: 1.5rem 0;
    }}
    
    /* Target ONLY top-level dashboard columns inside our main block */
    /* This creates the 'Card' effect for the Left (Table) and Right (Chart) panels */
    .main-dashboard-row [data-testid="stColumn"] {{
        background-color: #1E293B !important; /* Slightly lighter slate for cards */
        padding: 1.5rem !important;
        border-radius: 12px !important;
        border: 1px solid #334155 !important;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
    }}

    /* Reset styles for nested columns (inside the table/chart) so they don't inherit the card background */
    .main-dashboard-row [data-testid="stColumn"] [data-testid="stColumn"] {{
        background-color: transparent !important;
        padding: 0px !important;
        margin: 0px !important;
        border: none !important;
        box-shadow: none !important;
    }}

    /* --- INCREASE TABLE FONT SIZE --- */
    /* Specific selectors to target text inside the table container */
    .main-dashboard-row [data-testid="stColumn"]:first-child p,
    .main-dashboard-row [data-testid="stColumn"]:first-child div[data-testid="stHorizontalBlock"] p {{
        font-size: 14px !important; /* Increased from default ~12px for readability */
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

    /* Widget Labels styling (e.,g. Multiselect labels) */
    label, label p, label span {{
        color: #94A3B8 !important; /* Muted grey for labels */
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
        box-shadow: 0 0 10px {st.session_state.accent_color}40; /* Glow effect on hover */
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
# 2. EXECUTIVE HEADER SECTION WITH REFRESH BUTTON
# ---------------------------------------------------

# Create a row for Title (80% width) and Button (20% width)
header_col1, header_col2 = st.columns([0.8, 0.2])

with header_col1:
    # Render the main title using custom HTML/CSS class
    st.markdown('<div class="dashboard-title">GCS Prioritization and Utilization Dashboard</div>', unsafe_allow_html=True)
    # Render the colored accent bar below the title
    st.markdown(f'<div class="accent-bar"></div>', unsafe_allow_html=True)

with header_col2:
    # Add the refresh button aligned to the right
    # use_container_width=True makes it fill the column for better clickability
    if st.button("🔄 Refresh Dashboard", use_container_width=True, type="secondary"):
        refresh_dashboard()

# ---------------------------------------------------
# 3. RUN EXTRACTIONS, FILTERS & SELECTION LOGIC
# ---------------------------------------------------
# get_processed_data() returns the DataFrame and raw cases list.
df, cases = get_processed_data()

# apply_filters_and_ranking() renders the filter widgets (Region/Owner) 
# and returns the filtered/sorted DataFrame.
filtered_df = apply_filters_and_ranking(df)

# ---------------------------------------------------
# 4. CONCURRENT UI ELEMENTS (LAYOUT)
# ---------------------------------------------------
# Wrap the main content in a div with class 'main-dashboard-row' 
# so our CSS targets only these columns.
st.markdown('<div class="main-dashboard-row">', unsafe_allow_html=True)

# CHANGED: Ratio [3, 1] gives 75% width to Table and 25% to Chart
left, right = st.columns([3, 1], gap="large")

with left:
    # Render the detailed case table with AI sentiment analysis buttons
    render_table(filtered_df, cases, OpenAIService())

with right:
    # Render the gauge chart showing total workload/utilization
    render_chart(filtered_df)

st.markdown('</div>', unsafe_allow_html=True)

# ---------------------------------------------------
# 5. FOOTER
# ---------------------------------------------------
st.markdown("---")
st.caption("🔄 Dashboard auto-refreshes every 1 Hour directly from Salesforce.")