import sys
import os
import threading
import time
import importlib.util
import streamlit as st

sys.path.append(os.getcwd())

# -------------------------------------------------------
# 🕒 BACKGROUND SCHEDULER (Runs Once Per Session)
# -------------------------------------------------------
INITIAL_DELAY_MINUTES = 60
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
            print(f"⏳ Sentiment scheduler: Waiting {INTERVAL_MINUTES} minutes until next run...")
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
# 📦 IMPORTS & PAGE CONFIG
# -------------------------------------------------------
try:
    from case_analysis.pages.Reporttopleft import (
        inject_custom_css, 
        get_processed_data, 
        apply_filters_and_ranking, 
        render_table,
        sync_audit_history
    )
    from case_analysis.pages.Charttopright import render_chart
    from case_analysis.pages.Chart_30_days import render_30_day_chart
except ImportError as e:
    st.error(f"❌ Import Error: {e}. Please check your file structure.")
    st.stop()

st.set_page_config(
    page_title="Prioritization Dashboard", 
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# -------------------------------------------------------
# 🎨 UI THEME & CSS
# -------------------------------------------------------
if 'accent_color' not in st.session_state:
    st.session_state.accent_color = "#3B82F6"

if st.button("🎨 Toggle Accent Theme (Blue / Slate)"):
    st.session_state.accent_color = "#64748B" if st.session_state.accent_color == "#3B82F6" else "#3B82F6"

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
    keys_to_clear = ['filter_case_id', 'filter_region', 'filter_status', 'expanded_rows', 'selected_cases', 'audit_synced']
    for key in keys_to_clear:
        if key in st.session_state: del st.session_state[key]
    st.rerun()

header_col1, header_col2 = st.columns([0.8, 0.2])
with header_col1:
    st.markdown('<div class="dashboard-title">GCS Prioritization and Utilization Dashboard</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="accent-bar"></div>', unsafe_allow_html=True)
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
            status_text = "🔄 Next Cycle"
        mins, secs = divmod(int(next_run_seconds), 60)
        st.markdown(
            f"""<div style="display: inline-block; background-color: #1E293B; border: 1px solid #334155; border-radius: 6px; padding: 4px 12px; margin-top: 8px; font-size: 0.85rem; color: #94A3B8;">
                <span style="color: {st.session_state.accent_color}; font-weight: bold;">{status_text}:</span> 
                Sentiment Pipeline runs in <b>{mins}m {secs}s</b>
            </div>""", unsafe_allow_html=True)

with header_col2:
    if st.button("🔄 Refresh Dashboard", use_container_width=True, type="secondary"):
        refresh_dashboard()

st.divider()

# -------------------------------------------------------
# 📈 DATA FETCHING, AUDIT SYNC & RENDERING
# -------------------------------------------------------
try:
    with st.spinner("Loading cases from Salesforce..."):
        df, cases = get_processed_data()
    
    # 🔒 AUDIT SYNC: Runs exactly once per data fetch cycle
    if not st.session_state.get("audit_synced"):
        try:
            sync_audit_history(df)
            st.session_state.audit_synced = True
        except Exception as e:
            st.warning(f"⚠️ Audit sync failed (dashboard still functional): {e}")
    
    if df.empty:
        st.warning("⚠️ No open cases found for the selected owners.")
    else:
        filtered_df, active_owners = apply_filters_and_ranking(df)
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
                try: render_30_day_chart(active_owners)
                except Exception as e: st.error(f"Chart 2 Error: {e}")
            st.markdown('</div>', unsafe_allow_html=True)

except Exception as e:
    st.error(f"❌ Critical Error Loading Dashboard: {e}")
    st.exception(e)
    st.stop()

st.divider()
st.caption("🔄 Dashboard auto-refreshes every 1 Hour directly from Salesforce. Audit history retains 2-day change snapshots.")