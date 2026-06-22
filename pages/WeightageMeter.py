import streamlit as st
import plotly.graph_objects as go

def render_chart(filtered_df):
    """
    Renders the Gauge Chart (Weightage Meter) on the right side.
    Calculates total case score and displays it against a dynamic scale.
    """
    
    # Use markdown for the header to maintain theme consistency instead of default subheader
    st.markdown("<h3 style='color: #F8FAFC; margin-top: 0; margin-bottom: 10px;'>📊 Weightage Meter</h3>", unsafe_allow_html=True)

    # Calculate total visible score without decimal-only overdue ranking bonuses.
    score_column = "Case Score Display" if "Case Score Display" in filtered_df.columns else "Case Score"
    total_score = filtered_df[score_column].sum()

    # Count unique regions and owners currently displayed
    selected_regions = filtered_df["Region"].nunique()
    selected_owners = filtered_df["Case Owner"].nunique()

    # Dynamic max scale for the gauge
    # Ensures the gauge doesn't look too full or too empty. 
    # Max is either total_score + 50 or 100, whichever is larger.
    max_score = max(total_score + 50, 100)

    # Card wrapper matching table height — now set explicit height to match table container
    with st.container(border=True, height=350):  # 👈 MATCH TABLE HEIGHT

        # Display summary stats above the gauge
        st.markdown(
            f"""
            <div style='text-align:center;
                        font-size:18px;
                        font-weight:600;
                        color:#F8FAFC; 
                        margin-bottom:-15px'>
            {selected_regions} Region(s) | {selected_owners} Owner(s)
            </div>
            """,
            unsafe_allow_html=True
        )

        # Create Plotly Gauge Chart
        fig = go.Figure(go.Indicator(
            mode="gauge+number",
            value=total_score,

            domain={'x':[0,1], 'y':[0.15,0.9]},  # Adjusted y-range to use more vertical space

            number={
                "font":{"size":50, "color": "#F8FAFC"} # Large white font for the score
            },

                gauge={
                'axis':{
                    'range':[0,max_score],
                    'tickwidth':1,
                    'tickcolor': "#F8FAFC",
                    'tickfont': dict(color="#F8FAFC", size=12)
                },
                # 👇 NEW: Updated to match the Dark Green from the main chart
                'bar':{'color':'rgba(0, 100, 0, 0.85)', 'thickness':0.35},
                'steps':[
                    # 👇 NEW: Updated to match the Green/Yellow/Red zones
                    {'range':[0,max_score*0.4],'color':'rgba(144, 238, 144, 0.4)'},
                    {'range':[max_score*0.4,max_score*0.75],'color':'rgba(255, 255, 0, 0.4)'},
                    {'range':[max_score*0.75,max_score],'color':'rgba(255, 0, 0, 0.4)'}
                ],
                'threshold':{
                    'line':{'color':'#FFFFFF', 'width':5},
                    'thickness':0.9,
                    'value':total_score
                }
            }
        ))

        # Update Layout for Dark Theme compatibility
        fig.update_layout(
            height=330,   # 👈 Match table container height minus padding
            margin=dict(l=15, r=15, t=40, b=15),
            paper_bgcolor="rgba(0,0,0,0)", # Transparent background
            plot_bgcolor="rgba(0,0,0,0)",  # Transparent plot area
            font=dict(color="#F8FAFC")     # White font
        )

        st.plotly_chart(fig, use_container_width=True, theme=None)

        # If only one owner is selected, display their name below the chart
        if selected_owners == 1:
            owner = filtered_df["Case Owner"].iloc[0]
            st.markdown(
                f"""
                <div style='text-align:center;
                            font-size:15px;
                            font-weight:bold;
                            color:#94A3B8;
                            margin-top: -10px;'>
                 {owner}
                </div>
                """,
                unsafe_allow_html=True
            )
