## Xactly Confidential Author - Vikas R (X003286)

import streamlit as st
import plotly.graph_objects as go


def render_chart(filtered_df):

    import plotly.graph_objects as go
    import streamlit as st

    st.subheader(":bar_chart: Utilisation Meter")

    # Calculate total score
    total_score = filtered_df["Case Score"].sum()

    selected_regions = filtered_df["Region"].nunique()
    selected_owners = filtered_df["Case Owner"].nunique()

    # Dynamic max scale
    max_score = max(total_score + 50, 100)

    # Card wrapper matching table height
    with st.container(border=True):

        st.markdown(
            f"""
            <div style='text-align:center;
                        font-size:18px;
                        font-weight:600;
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
                    'y':[0.22,0.95]},  # move gauge upward

            number={
                "font":{"size":55}
            },

            gauge={
                'axis':{
                    'range':[0,max_score],
                    'tickwidth':1
                },

                'bar':{
                    'color':'darkgreen',
                    'thickness':0.30
                },

                'steps':[
                    {'range':[0,max_score*0.4],'color':'lightgreen'},
                    {'range':[max_score*0.4,max_score*0.75],'color':'yellow'},
                    {'range':[max_score*0.75,max_score],'color':'red'}
                ],

                'threshold':{
                    'line':{
                        'color':'black',
                        'width':4
                    },
                    'thickness':0.8,
                    'value':total_score
                }
            }
        ))

        fig.update_layout(
            height=290,   # match table
            margin=dict(
                l=20,
                r=20,
                t=30,
                b=10
            )
        )

        st.plotly_chart(
            fig,
            use_container_width=True
        )

        if selected_owners == 1:
            owner = filtered_df["Case Owner"].iloc[0]

            st.markdown(
                f"""
                <div style='text-align:center;
                            font-size:15px;
                            font-weight:bold'>
                 {owner}
                </div>
                """,
                unsafe_allow_html=True
            )




