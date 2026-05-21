## Xactly Confidential Author - Vikas R (X003286)

import streamlit as st
import pandas as pd
from services.case_service import CaseService
from clients.salesforce_connector import SalesforceConnector
from datetime import datetime
import pytz



# ---------------------------------------------------
# CONFIGURATION & CSS
# ---------------------------------------------------

OWNER_REGION_MAP = {
    "Sakthi Devi SK":"APAC", "Mohamed Ramzin":"APAC", "Syeda Sajida":"APAC", "Yogesh R":"APAC", "Ganesh Babu":"APAC", "Naveen Kumar Surisetti":"APAC", "Srinivas Aaguri":"APAC",
    "Abhishek Bose":"EMEA", "Sindhu M Y":"EMEA", "Payal Gupta":"EMEA", "Poonam Pandey":"EMEA", "Mugilan Gowthaman":"EMEA", "Santosh Veduruvada":"EMEA", "Sivagnana Bharathi Nagaraj":"EMEA", "Ullas Shenoy":"EMEA", "Vipul SG":"EMEA", "Vilas Potadar":"EMEA", "Chethan Kumar P.":"EMEA", "Amith Gujjar":"EMEA", "Monika Sihag":"EMEA", "Chandra Sai Surya Santosh Veduruvada":"EMEA",
    "Aqsa Pandith":"NA EAST", "Prabu R":"NA EAST", "Vikas R":"NA EAST", "Tarun Buthala":"NA EAST", "Gnanasiri Pechetti":"NA EAST", "Shivendra Yadav":"NA EAST", "Kaushik Patowary":"NA EAST", "Shahrukh Shahzad":"NA EAST", "Amit Bhojak":"NA EAST", "Mohammed Usman":"NA EAST", "Santi Sahoo":"NA EAST", "Nilanjan Roy":"NA EAST", "Nupur Rao":"NA EAST", "Rohit Nargundkar":"NA EAST", "Prabu Rajendran":"NA EAST", "Palak Kharche":"NA EAST", "Pooja Singh":"NA EAST", "Becca Lozano":"NA EAST", "Mohammad Raza":"NA EAST", "Sumit Paul":"NA EAST",
    "Selvin Raja":"NA WEST", "Shakti Prasad Pati":"NA WEST", "Sanjay Kademani":"NA WEST", "Shreyas G Nambiar":"NA WEST", "Vishal Mavi":"NA WEST", "Infant Raj.":"NA WEST", "Pallavi M R":"NA WEST", "Aniket Chinde":"NA WEST", "Kalyan Kumar":"NA WEST", "Amit Kumar":"NA WEST", "Karthik Dosapati":"NA WEST", "Peter Kyller":"NA WEST", "Imari Killikelly":"NA WEST", "Anthony Pham":"NA WEST", "Sushmitha Rayalkeri":"NA WEST", "Merlyn Pushparaj":"NA WEST", "ZAREENA BANO":"NA WEST", "Joshua Halle" : "NA WEST", "Karalie Murray" : "NA WEST"
}



def inject_custom_css():

    st.markdown("""

<style>
    /* Nuke Streamlit's automatic multi-page nav sidebar elements completely */
    [data-testid="stSidebar"] { display: none !important; }
    [data-testid="collapsedControl"] { display: none !important; }
    
    .main { padding-top:10px; }
    .block-container { padding-top:1rem; }
    h1 { font-size:42px !important; font-weight:800 !important; }
    [data-testid="stHorizontalBlock"] { gap:0.2rem; }
    p { font-size:12px !important; }
    button { font-size:11px !important; padding:0.1rem !important; }        
    </style>

    """,unsafe_allow_html=True)





# ---------------------------------------------------
# BUSINESS LOGIC
# ---------------------------------------------------

def calculate_score(
    sevone,
    severity,
    support_level,
    escalated
):

    if sevone:
        return 14

    if escalated:
        return 13

    score_map={

        ("S1","Premium Plus"):12,
        ("S1","Premium (24x7)"):11,
        ("S1","Standard"):10,

        ("S2","Premium Plus"):9,
        ("S2","Premium (24x7)"):8,
        ("S2","Standard"):7,

        ("S3","Premium Plus"):6,
        ("S3","Premium (24x7)"):5,
        ("S3","Standard"):4,

        ("S4","Premium Plus"):3,
        ("S4","Premium (24x7)"):2,
        ("S4","Standard"):1
    }

    return score_map.get(
        (severity,support_level),
        0
    )



@st.cache_data(ttl=180)
def fetch_cases():

    connector=SalesforceConnector()

    sf=connector.connect()

    service=CaseService(sf)

    return service.get_recent_cases()


def convert_to_ist(date_string):

    if not date_string or date_string=="N/A":
        return "N/A"

    try:

        utc_time = datetime.strptime(
            date_string,
            "%Y-%m-%dT%H:%M:%S.000+0000"
        )

        utc_time = pytz.utc.localize(
            utc_time
        )

        ist = pytz.timezone(
            "Asia/Kolkata"
        )

        ist_time = utc_time.astimezone(
            ist
        )

        return ist_time.strftime(
            "%d-%b %H:%M"
        )

    except:
        return date_string


def get_processed_data():

    with st.spinner(
        "Fetching Salesforce Cases..."
    ):

        cases=fetch_cases()

    if "sentiments" not in st.session_state:

        st.session_state.sentiments={}

    dashboard=[]

    for case in cases:

        if case is None:
            continue

        owner_name=(
            case.get("Owner") or {}
        ).get(
            "Name",
            "UNKNOWN"
        )

        customer_name=(
            case.get("Account") or {}
        ).get(
            "Name",
            "N/A"
        )

        support_level=(
            case.get(
                "Support_Level__c"
            ) or "N/A"
        )

        severity=(
            case.get(
                 "Severity__c"
              )
              or "N/A"
        )

        sevone=(
            case.get(
                 "SEVONE__c"
              )
        )

        escalated=(
            case.get(
                "IsEscalated"
            ) or False
        )

        case_score=calculate_score(
          sevone,
          severity,
         support_level,
         escalated
        )       



        last_commenter="Internal Comment"
        last_customer_comment_time="N/A"



        comments=(
            case.get(
                "CaseComments"
            ) or {}
        ).get(
            "records",
            []
        )



        if comments:

            latest=comments[0]

            created_by=(
                latest.get(
                    "CreatedBy"
                ) or {}
            ).get(
                "Name",
                ""
            )

            if created_by in OWNER_REGION_MAP:

                last_commenter="Support Comment"

            else:

                last_commenter="Customer Comment"

            for comment in comments:
                comment_user=(
                    comment.get(
                        "CreatedBy"
                    ) or {}
                ).get(
                    "Name",""
                )
                if comment_user not in OWNER_REGION_MAP:
                    last_customer_comment_time=convert_to_ist(
                        comment.get(
                            "CreatedDate"
                        )
                        or "N/A"
                    )
                    break



        dashboard.append({

            "Region":OWNER_REGION_MAP.get(
                owner_name,
                "UNKNOWN"
            ),

            "Case Number":case.get(
                "CaseNumber",
                "N/A"
            ),

            "Customer Name":customer_name,

            "Case Owner":owner_name,

            "Support Level":support_level,
            "Severity":severity,

            "Status":case.get(
                "Status",
                "N/A"
            ),

            "Escalated":escalated,

            "Last Comment By":last_commenter,

            "Sentiment":
            st.session_state.sentiments.get(
                case.get("CaseNumber"),
                "Not Analyzed"
            ),
            "Case Score":case_score,
            "Last Customer Comment":last_customer_comment_time
        })

    return pd.DataFrame(
        dashboard
    ),cases



def apply_filters_and_ranking(df):

    c1, c2 = st.columns(2)

    # -------- Region filter --------
    with c1:

        regions = sorted(
            df["Region"].dropna().unique()
        )

        selected_regions = st.multiselect(
            ":earth_africa: Region",
            regions,
            default=regions
        )

    if not selected_regions:
        selected_regions = regions



    # Filter temporary dataframe by region first
    temp_df = df[
        df["Region"].isin(selected_regions)
    ]



    # -------- Owner filter depends on region --------
    with c2:

        owners = sorted(
            temp_df["Case Owner"]
            .dropna()
            .unique()
        )

        selected_owners = st.multiselect(
            ":bust_in_silhouette: Owner",
            owners,
            default=owners
        )

    if not selected_owners:
        selected_owners = owners



    # Final filter
    filtered_df = temp_df[
        temp_df["Case Owner"]
        .isin(selected_owners)
    ]



    # Ranking logic unchanged
    filtered_df = filtered_df.sort_values(
        by=[
            "Case Owner",
            "Case Score"
        ],
        ascending=[True,False]
    )

    filtered_df["Sequential_Rank"] = (
        filtered_df.groupby(
            "Case Owner"
        ).cumcount()+1
    )

    return filtered_df








# ---------------------------------------------------
# TABLE
# ---------------------------------------------------

def render_table(filtered_df, cases, openai_service):
    st.subheader(":clipboard: AI Case Monitoring")

    report_box = st.container(height=350)

    with report_box:
        headers = st.columns([1, 1, 2.5, 2, 1.2,1, 1.2, 1, 1.5,2, 2,1])

        headers[0].write("**Region**")
        headers[1].write("**Case**")
        headers[2].write("**Customer**")
        headers[3].write("**Owner**")
        headers[4].write("**Support Level**")
        headers[5].write("**Severity**")
        headers[6].write("**Status**")
        headers[7].write("**Escalated**")
        headers[8].write("**Sentiment**")
        headers[9].write("**Last Comment**")
        headers[10].write("**Last Customer Comment Time**")
        headers[11].write("**Rank**")

        st.markdown("---")
        
        for index, row in filtered_df.iterrows():
            cols = st.columns([1, 1, 2.5, 2, 1.2,1, 1.2, 1, 1.5,2,2, 1])

            cols[0].write(row["Region"])
            cols[1].write(row["Case Number"])
            cols[2].write(row["Customer Name"])
            cols[3].write(row["Case Owner"])
            cols[4].write(row["Support Level"])
            cols[5].write(row["Severity"])
            cols[6].write(row["Status"])
            cols[7].write("Yes" if row["Escalated"] else "No")

            sentiment = row["Sentiment"]

            if sentiment == "Not Analyzed":
                if cols[8].button(":brain: Analyze", key=f"analyze_{row['Case Number']}"):
                    with st.spinner(f"Analyzing {row['Case Number']}..."):
                        matching_case = next(
                            c for c in cases
                            if c["CaseNumber"] == row["Case Number"]
                        )
                        response = openai_service.analyze_case(matching_case)
                        st.session_state.sentiments[row["Case Number"]] = response
                        st.rerun()
            else:
                # Dynamic sentiment colors
                sentiment_lower = sentiment.lower()
                if "positive" in sentiment_lower:
                    cols[8].success(sentiment) 
                elif "medium" in sentiment_lower or "neutral" in sentiment_lower:
                    cols[8].warning(sentiment) 
                elif "negative" in sentiment_lower or "critical" in sentiment_lower:
                    cols[8].error(sentiment)   
                else:
                    cols[8].info(sentiment)    

            # Sequential Rank
            cols[9].write(row["Last Comment By"])
            cols[10].write(row["Last Customer Comment"])
            cols[11].write(f"{row['Sequential_Rank']} ({row['Case Score']}pts)")
