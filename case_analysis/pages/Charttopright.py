import streamlit as st
import plotly.graph_objects as go

def render_chart(filtered_df):
    
    # Use markdown for the header to maintain theme consistency instead of default subheader
    st.markdown("<h3 style='color: #F8FAFC; margin-top: 0; margin-bottom: 10px;'>📊 Utilization Meter</h3>", unsafe_allow_html=True)

    # Calculate total score
    total_score = filtered_df["Case Score"].sum()

    selected_regions = filtered_df["Region"].nunique()
    selected_owners = filtered_df["Case Owner"].nunique()

    # Dynamic max scale
    max_score = max(total_score + 50, 100)

    # Card wrapper matching table height — now set explicit height to match table container
    with st.container(border=True, height=350):  # 👈 MATCH TABLE HEIGHT

        # Added explicit color #F8FAFC so text is visible on dark slate
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

        fig = go.Figure(go.Indicator(
            mode="gauge+number",
            value=total_score,

            domain={'x':[0,1],
                    'y':[0.15,0.9]},  # Adjusted y-range to use more vertical space

            number={
                "font":{"size":50, "color": "#F8FAFC"} # Slightly larger font for better visibility
            },

            gauge={
                'axis':{
                    'range':[0,max_score],
                    'tickwidth':1,
                    'tickcolor': "#F8FAFC",
                    'tickfont': dict(color="#F8FAFC", size=12)
                },

                'bar':{
                    # Exact RGB for 'darkgreen' (0, 100, 0) with 0.85 opacity
                    'color':'rgba(0, 100, 0, 0.85)',
                    'thickness':0.35  # Slightly thicker bar for visual balance
                },

                'steps':[
                    # Exact RGB for 'lightgreen' (144, 238, 144) with 0.4 opacity
                    {'range':[0,max_score*0.4],'color':'rgba(144, 238, 144, 0.4)'},
                    
                    # Exact RGB for 'yellow' (255, 255, 0) with 0.4 opacity
                    {'range':[max_score*0.4,max_score*0.75],'color':'rgba(255, 255, 0, 0.4)'},
                    
                    # Exact RGB for 'red' (255, 0, 0) with 0.4 opacity
                    {'range':[max_score*0.75,max_score],'color':'rgba(255, 0, 0, 0.4)'}
                ],

                'threshold':{
                    'line':{
                        'color':'#FFFFFF',
                        'width':5
                    },
                    'thickness':0.9,
                    'value':total_score
                }
            }
        ))

        fig.update_layout(
            height=330,   # 👈 Match table container height minus padding
            margin=dict(
                l=15,
                r=15,
                t=40,     # More top margin for title
                b=15
            ),
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=dict(color="#F8FAFC")
        )

        st.plotly_chart(
            fig,
            use_container_width=True,
            theme=None
        )

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