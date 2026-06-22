import sys
import os
import threading
import time
import importlib.util
import streamlit as st
import pytz
from datetime import datetime, timedelta

sys.path.append(os.getcwd())

# -------------------------------------------------------
# 📦 PAGE CONFIG
# -------------------------------------------------------
st.set_page_config(
    page_title="Prioritization Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# -------------------------------------------------------
# 🕒 BACKGROUND SCHEDULER (Runs Once Per Session)
# -------------------------------------------------------
INITIAL_DELAY_MINUTES = 0.5
INTERVAL_MINUTES = 60
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SENTIMENT_SCRIPT_PATH = os.path.join(SCRIPT_DIR, "pages", "Sentiment_analysis.py")

def _run_sentiment_pipeline_loop():
    try:
        print(f"⏳ Sentiment scheduler: Waiting {INITIAL_DELAY_MINUTES} minutes before first run...")
        time.sleep(INITIAL_DELAY_MINUTES * 60)
        while True:
            try:
                print("🚀 Executing Sentiment Analysis & Snowflake Ingestion...")
                if not os.path.exists(SENTIMENT_SCRIPT_PATH):
                    raise FileNotFoundError(f"Script not found at: {SENTIMENT_SCRIPT_PATH}")
                spec = importlib.util.spec_from_file_location("sentiment_analysis", SENTIMENT_SCRIPT_PATH)
                sentiment_module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(sentiment_module)
                if hasattr(sentiment_module, "main"):
                    sentiment_module.main()
                    print("✅ Pipeline run completed successfully.")
                else:
                    raise AttributeError("Sentiment_analysis.py must define a main() function")
            except Exception as e:
                print(f"❌ Pipeline execution failed: {e}")
                import traceback
                traceback.print_exc()
            print(f" Sentiment scheduler: Waiting {INTERVAL_MINUTES} minutes until next run...")
            time.sleep(INTERVAL_MINUTES * 60)
    except Exception as e:
        print(f"🔥 Background scheduler crashed: {e}")
        import traceback
        traceback.print_exc()

def schedule_pipeline():
    if st.session_state.get("pipeline_scheduled", False):
        return
    st.session_state.pipeline_scheduled = True
    st.session_state.pipeline_launch_time = time.time()
    thread = threading.Thread(target=_run_sentiment_pipeline_loop, daemon=True)
    thread.start()

schedule_pipeline()

# -------------------------------------------------------
# 📦 IMPORTS
# -------------------------------------------------------
try:
    from pages.CasePriorityIndex import (
        inject_custom_css, 
        get_processed_data, 
        apply_filters_and_ranking, 
        render_table,
        sync_audit_history
    )
    from pages.WeightageMeter import render_chart
    from pages.OngoingSLABreaches import render_30_day_chart, sync_sla_breach_impact_history
except ImportError as e:
    st.error(f"❌ Import Error: {e}. Please check your file structure.")
    st.stop()

# -------------------------------------------------------
# 📉 SLA BREACH IMPACT SCHEDULER
# -------------------------------------------------------
SLA_IMPACT_RUN_HOUR_IST = 18

def _seconds_until_next_sla_impact_run():
    ist = pytz.timezone("Asia/Kolkata")
    now_ist = datetime.now(ist)
    target = now_ist.replace(hour=SLA_IMPACT_RUN_HOUR_IST, minute=0, second=0, microsecond=0)
    if now_ist >= target:
        target += timedelta(days=1)
    return max(60, int((target - now_ist).total_seconds()))

def _run_sla_breach_impact_loop():
    while True:
        sleep_seconds = _seconds_until_next_sla_impact_run()
        print(f"⏳ SLA breach impact scheduler: waiting {sleep_seconds // 60} minutes until 6 PM IST run.")
        time.sleep(sleep_seconds)
        try:
            print("🚀 Executing daily SLA breach impact sync...")
            current_df, _ = get_processed_data()
            sync_sla_breach_impact_history(current_df)
            print("✅ Daily SLA breach impact sync completed.")
        except Exception as e:
            print(f"❌ Daily SLA breach impact sync failed: {e}")
            import traceback
            traceback.print_exc()

def schedule_sla_breach_impact_pipeline():
    if st.session_state.get("sla_breach_impact_scheduler_scheduled", False):
        return
    st.session_state.sla_breach_impact_scheduler_scheduled = True
    thread = threading.Thread(target=_run_sla_breach_impact_loop, daemon=True)
    thread.start()

schedule_sla_breach_impact_pipeline()

# -------------------------------------------------------
# 🎨 UI THEME & CSS
# -------------------------------------------------------
# Set default accent color if not present
if 'accent_color' not in st.session_state:
    st.session_state.accent_color = "#3B82F6"

inject_custom_css()

st.markdown(
    f"""
    <style>
    .stApp {{ background-color: #0F172A !important; color: #F8FAFC !important; }}
    hr {{ border: 0; height: 1px; background: linear-gradient(to right, {st.session_state.accent_color}, transparent); margin: 1.5rem 0; }}
    .main-dashboard-row [data-testid="stColumn"] {{ background-color: #1E293B !important; padding: 1.5rem !important; border-radius: 12px !important; border: 1px solid #334155 !important; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1); }}
    .main-dashboard-row [data-testid="stColumn"] [data-testid="stColumn"] {{ background-color: transparent !important; padding: 0px !important; margin: 0px !important; border: none !important; box-shadow: none !important; }}
    .main-dashboard-row [data-testid="stColumn"]:first-child p, .main-dashboard-row [data-testid="stColumn"]:first-child div[data-testid="stHorizontalBlock"] p {{ font-size: 14px !important; line-height: 1.4 !important; }}
    .main-dashboard-row [data-testid="stColumn"]:first-child h1, .main-dashboard-row [data-testid="stColumn"]:first-child h2, .main-dashboard-row [data-testid="stColumn"]:first-child h3, .main-dashboard-row [data-testid="stColumn"]:first-child h4 {{ font-size: 1.2rem !important; color: #FFFFFF !important; }}
    label, label p, label span {{ color: #94A3B8 !important; font-weight: 500 !important; font-size: 0.9rem !important; letter-spacing: 0.5px; }}
    div[data-testid="stButton"] button {{ background-color: #1E293B !important; border: 1px solid #334155 !important; border-radius: 6px !important; transition: all 0.2s ease-in-out; }}
    div[data-testid="stButton"] button p {{ color: #E2E8F0 !important; font-weight: 500 !important; }}
    div[data-testid="stButton"] button:hover {{ border-color: {st.session_state.accent_color} !important; box-shadow: 0 0 10px {st.session_state.accent_color}40; }}
    .dashboard-title {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif !important; color: #FFFFFF !important; font-size: 2rem !important; font-weight: 700 !important; letter-spacing: -0.5px !important; margin-bottom: 4px !important; }}
    .dashboard-subtitle {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif !important; color: #94A3B8 !important; font-size: 0.95rem !important; margin-bottom: 20px !important; }}
    .accent-bar {{ height: 4px; width: 60px; background-color: {st.session_state.accent_color}; border-radius: 2px; margin-bottom: 25px; }}
    
    /* 🎯 Sleek Search Input Styling */
    div[data-testid="stTextInput"] > div > div > input {{
        background-color: #1E293B !important;
        border: 1px solid #334155 !important;
        border-radius: 6px !important;
        color: #F8FAFC !important;
        font-size: 13px !important;
        padding: 8px 12px !important;
        height: 42px !important;
    }}
    div[data-testid="stTextInput"] > div > div > input:focus {{
        border-color: {st.session_state.accent_color} !important;
        box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.2) !important;
    }}
    div[data-testid="stTextInput"] > div > div > input::placeholder {{
        color: #64748B !important;
    }}
    </style>
    """,
    unsafe_allow_html=True
)

# -------------------------------------------------------
# 🔄 HEADER & REFRESH LOGIC
# -------------------------------------------------------
def refresh_dashboard():
    st.cache_data.clear()
    st.cache_resource.clear()
    keys_to_clear = ['filter_case_id', 'filter_region', 'filter_status', 'expanded_rows', 'selected_cases', 'audit_synced', 'dashboard_loaded', 'search_case_input']
    for key in keys_to_clear:
        if key in st.session_state: del st.session_state[key]
    st.rerun()

def clear_search_only():
    """Clear only the search field."""
    if "search_case_input" in st.session_state:
        st.session_state.search_case_input = ""

# 🎯 SINGLE ROW HEADER: Title/Status on Left, Actions on Right
header_col1, header_col2 = st.columns([0.85, 0.15])

with header_col1:
    # Title and Accent Bar
    st.markdown('<div class="dashboard-title">GCS Prioritization Index</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="accent-bar"></div>', unsafe_allow_html=True)
    
    # Pipeline Status Indicator
    launch_time = st.session_state.get("pipeline_launch_time")
    if launch_time:
        current_time = time.time()
        elapsed = current_time - launch_time
        if elapsed < (INITIAL_DELAY_MINUTES * 60):
            next_run_seconds = (INITIAL_DELAY_MINUTES * 60) - elapsed
            status_text = "⏳ Initial Wait"
        else:
            cycle_elapsed = elapsed % (INTERVAL_MINUTES * 60)
            next_run_seconds = (INTERVAL_MINUTES * 60) - cycle_elapsed
            status_text = " Next Cycle"
        mins, secs = divmod(int(next_run_seconds), 60)
       ## st.markdown(
      ##      f"""<div style="display: inline-block; background-color: #1E293B; border: 1px solid #334155; border-radius: 6px; padding: 4px 12px; margin-top: 8px; font-size: 0.85rem; color: #94A3B8;">
        ##        <span style="color: {st.session_state.accent_color}; font-weight: bold;">{status_text}:</span> 
          ##      Sentiment Pipeline runs in <b>{mins}m {secs}s</b>
            ##</div>""", unsafe_allow_html=True)

with header_col2:
    # Vertical spacer to push buttons down to align with the status indicator
    st.markdown("<br>", unsafe_allow_html=True) 
    
    # Clear Search Button (Conditional)
    if st.session_state.get("search_case_input"):
        st.button("🔍 Clear Search", use_container_width=True, type="secondary", on_click=clear_search_only)
        
    # Refresh Button
    if st.button("🔄 Refresh", use_container_width=True, type="secondary"):
        refresh_dashboard()

st.divider()

# -------------------------------------------------------
#  DATA FETCHING, AUDIT SYNC & RENDERING
# -------------------------------------------------------

# 🔄 FULL-SCREEN LOADING OVERLAY WITH REAL-TIME PERCENTAGE
is_initial_load = "dashboard_loaded" not in st.session_state
loading_overlay = None

def update_overlay(percent, text):
    """Updates the full-screen overlay with current progress percentage and status text."""
    if loading_overlay:
        with loading_overlay:
            st.markdown(f"""
                <div style="position: fixed; top: 0; left: 0; width: 100vw; height: 100vh; 
                            background-color: rgba(15, 23, 42, 0.98); z-index: 99999; 
                            display: flex; justify-content: center; align-items: center; 
                            flex-direction: column; color: #F8FAFC; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">
                    <div style="border: 5px solid #334155; border-top: 5px solid {st.session_state.accent_color}; 
                                border-radius: 50%; width: 60px; height: 60px; 
                                animation: spin 1s linear infinite; margin-bottom: 20px;"></div>
                    <div style="font-size: 22px; font-weight: 700; letter-spacing: -0.5px;">Calculating Index for your Priority ............</div>
                    <div style="font-size: 14px; color: #94A3B8; margin-top: 8px;">{text}</div>
                    <div style="width: 300px; height: 8px; background-color: #334155; border-radius: 4px; overflow: hidden; margin-top: 20px;">
                        <div style="width: {percent}%; height: 100%; background-color: {st.session_state.accent_color}; border-radius: 4px; transition: width 0.5s ease-out;"></div>
                    </div>
                    <div style="margin-top: 10px; font-size: 16px; font-weight: 600; color: #94A3B8;">{percent}%</div>
                </div>
                <style>
                    @keyframes spin {{
                        0% {{ transform: rotate(0deg); }}
                        100% {{ transform: rotate(360deg); }}
                    }}
                </style>
            """, unsafe_allow_html=True)

if is_initial_load:
    loading_overlay = st.empty()
    update_overlay(0, "Preparing to load...")

try:
    df, cases = get_processed_data(progress_callback=update_overlay)
    
    update_overlay(92, "Syncing audit history...")
    if not st.session_state.get("audit_synced"):
        try:
            sync_audit_history(df)
            st.session_state.audit_synced = True
        except Exception as e:
            st.warning(f"⚠️ Audit sync failed (dashboard still functional): {e}")

    update_overlay(95, "Syncing SLA breach impact...")
    if not st.session_state.get("sla_breach_impact_synced"):
        try:
            sync_sla_breach_impact_history(df)
            st.session_state.sla_breach_impact_synced = True
        except Exception as e:
            st.warning(f"⚠️ SLA breach impact sync failed (dashboard still functional): {e}")
    
    update_overlay(100, "Rendering dashboard...")
    
    if loading_overlay:
        loading_overlay.empty()
        st.session_state.dashboard_loaded = True

    if df.empty:
        st.warning("⚠️ No open cases found for the selected owners.")
    else:
        # UPDATED: Unpack the 4th value (is_heal_desk_filter)
        filtered_df, active_owners, search_query, is_heal_desk_filter = apply_filters_and_ranking(df)
        
        if filtered_df.empty:
            st.info("ℹ️ No cases match the current filters.")
        else:
            st.markdown('<div class="main-dashboard-row">', unsafe_allow_html=True)
            render_table(filtered_df, cases)
            st.markdown('</div>', unsafe_allow_html=True)
            st.markdown("<br>", unsafe_allow_html=True)

            st.markdown('<div class="main-dashboard-row">', unsafe_allow_html=True)
            chart_col1, chart_col2 = st.columns(2, gap="large")
            with chart_col1:
                try: render_chart(filtered_df)
                except Exception as e: st.error(f"Chart 1 Error: {e}")
            with chart_col2:
                # UPDATED: Pass is_heal_desk_filter to the chart
                try: render_30_day_chart(active_owners, search_query, is_heal_desk_filter)
                except Exception as e: st.error(f"Chart 2 Error: {e}")
            st.markdown('</div>', unsafe_allow_html=True)

except Exception as e:
    if loading_overlay:
        loading_overlay.empty()
    st.error(f"❌ Critical Error Loading Dashboard: {e}")
    st.exception(e)
    st.stop()

st.divider()
st.caption("🔄 Index auto-refreshes every 1 Hour directly from Salesforce. Audit history retains 2-day change snapshots.")
