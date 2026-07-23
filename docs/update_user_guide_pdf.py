import fitz


SOURCE = "docs/GCS_Snowflake_Table_Structure.pdf"
OUTPUT = "docs/GCS_Snowflake_Table_Structure_updated.pdf"


def replace_with_html(page, rect, html):
    page.add_redact_annot(rect, fill=(1, 1, 1))
    page.apply_redactions()
    spare_height = page.insert_htmlbox(
        rect,
        html,
        css="body { font-family: Helvetica, Arial, sans-serif; font-size: 8.5pt; line-height: 1.38; color: #263238; }",
    )
    if isinstance(spare_height, tuple):
        spare_height = spare_height[0]
    if spare_height < 0:
        raise RuntimeError(f"Replacement text did not fit in {rect}")


doc = fitz.open(SOURCE)
page = doc[1]

replace_with_html(
    page,
    fitz.Rect(53, 95, 590, 158),
    """
    Open the Case Priority Index to see active cases in recommended working order. Cases with <b>Priority 1</b> should normally be reviewed first.<br>
    Before acting, review <b>severity, escalation, sentiment, SLA response time, latest comment and owner here</b>.<br>
    Use the region, owner, status, support-level and Heal Desk filters to focus the list. Select <b>Refresh</b> whenever you need the latest data.<br>
    Sentiment reflects the latest customer comment. When no customer comment is available, the case is displayed as Neutral.<br>
    The 72-hour sentiment result is authoritative and overrides the OpenAI classification when the two results differ.
    """,
)

replace_with_html(
    page,
    fitz.Rect(603, 95, 1135, 158),
    """
    Filter by region, owner and status to compare workload and find unassigned or overloaded queues. <b>Review top-priority cases first.</b><br>
    Before reassigning work, check severity, sentiment, SLA position and the owner's active workload.<br>
    In Slack queue alerts, <b>bold rows identify the new or follow-up case</b> and other cases whose queue position changed.
    """,
)

replace_with_html(
    page,
    fitz.Rect(53, 195, 590, 248),
    """
    Use SLA Response Time to find overdue and near-due cases. <b>Review red overdue cases immediately</b> and plan due-soon work next.<br>
    Use the case details shown here to read the latest customer comment, confirm ownership and decide whether a response is required.<br>
    <b>Work overdue customer-facing actions first</b>, followed by the closest upcoming deadlines.<br>
    <b>Use the dashboard as your primary workspace</b>; Salesforce remains the case system of record.
    """,
)

replace_with_html(
    page,
    fitz.Rect(603, 195, 1135, 248),
    """
    <b>Priority is the recommended working order.</b> A lower number means earlier review.<br>
    The ordering considers escalation, SevOne, severity, support level, customer sentiment and whether the SLA is overdue.<br>
    Critical and Negative sentiment raise attention, while overdue duration helps order cases with similar business importance.<br>
    Always apply support judgment and <b>Refresh the dashboard</b> before acting.
    """,
)

replace_with_html(
    page,
    fitz.Rect(250, 426, 890, 444),
    """<b>Important:</b> Refresh the dashboard before making queue decisions. Use the information shown here to avoid switching back and forth between systems.""",
)

replace_with_html(
    page,
    fitz.Rect(910, 384, 1135, 402),
    """Review the bold cases promptly and <b>update the action plan here</b>.""",
)

doc.save(OUTPUT, garbage=4, deflate=True)
doc.close()
print(OUTPUT)
