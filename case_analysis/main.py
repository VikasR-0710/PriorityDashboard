## Xactly Confidential Author - Vikas R (X003286)

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
# 1. PAGE LAYOUT CONFIG
# ---------------------------------------------------
st.set_page_config(page_title="AI Prioritisation Dashboard", layout="wide")
inject_custom_css()

st.title("Prioritisation Dashboard")
st.markdown("---")

# ---------------------------------------------------
# 2. RUN EXTRACTIONS, FILTERS & SELECTION LOGIC
# ---------------------------------------------------
df, cases = get_processed_data()
filtered_df = apply_filters_and_ranking(df)

st.markdown("---")

# ---------------------------------------------------
# 3. CONCURRENT UI ELEMENTS
# ---------------------------------------------------
left, right = st.columns([1.3, 0.7])

with left:
    render_table(filtered_df, cases, OpenAIService())

with right:
    render_chart(filtered_df)

st.markdown("---")
st.caption(":arrows_counterclockwise: Dashboard refreshes every 3 minutes from Salesforce")