"""Generate the end-user operational guide for the GCS Prioritization Index."""

from datetime import date
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate, Frame, KeepTogether, PageBreak, PageTemplate, Paragraph,
    Spacer, Table, TableStyle,
)


OUTPUT = Path(__file__).with_name("GCS_Prioritization_Index_Operational_User_Guide.pdf")
NAVY = colors.HexColor("#0F172A")
BLUE = colors.HexColor("#2563EB")
PALE_BLUE = colors.HexColor("#EFF6FF")
SLATE = colors.HexColor("#475569")
LIGHT = colors.HexColor("#E2E8F0")
RED = colors.HexColor("#B91C1C")
AMBER = colors.HexColor("#B45309")
GREEN = colors.HexColor("#047857")


styles = getSampleStyleSheet()
styles.add(ParagraphStyle(name="CoverTitle", parent=styles["Title"], fontName="Helvetica-Bold", fontSize=26, leading=31, textColor=NAVY, alignment=TA_CENTER, spaceAfter=10))
styles.add(ParagraphStyle(name="CoverSub", parent=styles["Normal"], fontSize=13, leading=19, textColor=SLATE, alignment=TA_CENTER))
styles.add(ParagraphStyle(name="H1x", parent=styles["Heading1"], fontName="Helvetica-Bold", fontSize=18, leading=22, textColor=NAVY, spaceBefore=6, spaceAfter=10))
styles.add(ParagraphStyle(name="H2x", parent=styles["Heading2"], fontName="Helvetica-Bold", fontSize=13, leading=17, textColor=BLUE, spaceBefore=10, spaceAfter=6))
styles.add(ParagraphStyle(name="Bodyx", parent=styles["BodyText"], fontName="Helvetica", fontSize=9.3, leading=14, textColor=colors.HexColor("#1E293B"), spaceAfter=6))
styles.add(ParagraphStyle(name="Smallx", parent=styles["BodyText"], fontSize=8, leading=11, textColor=SLATE))
styles.add(ParagraphStyle(name="Callout", parent=styles["BodyText"], fontSize=9.3, leading=14, textColor=NAVY, backColor=PALE_BLUE, borderColor=BLUE, borderWidth=0.7, borderPadding=8, spaceBefore=5, spaceAfter=9))
styles.add(ParagraphStyle(name="Step", parent=styles["BodyText"], fontSize=9.3, leading=14, leftIndent=8, firstLineIndent=-8, spaceAfter=5))


def P(text, style="Bodyx"):
    return Paragraph(text, styles[style])


def bullets(items):
    return [P(f"&#8226;&nbsp; {item}", "Step") for item in items]


def steps(items):
    return [P(f"<b>{i}.</b>&nbsp; {item}", "Step") for i, item in enumerate(items, 1)]


def table(rows, widths, header=True):
    data = [[P(str(c), "Smallx") for c in row] for row in rows]
    t = Table(data, colWidths=widths, repeatRows=1 if header else 0, hAlign="LEFT")
    commands = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.35, LIGHT),
        ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("ROWBACKGROUNDS", (0, 1 if header else 0), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
    ]
    if header:
        commands += [("BACKGROUND", (0, 0), (-1, 0), NAVY), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white)]
        for cell in data[0]:
            cell.style.textColor = colors.white
            cell.style.fontName = "Helvetica-Bold"
    t.setStyle(TableStyle(commands))
    return t


class GuideDoc(BaseDocTemplate):
    def __init__(self, filename):
        super().__init__(filename, pagesize=A4, rightMargin=17*mm, leftMargin=17*mm, topMargin=18*mm, bottomMargin=17*mm, title="GCS Prioritization Index - Operational User Guide", author="GCS Operations")
        frame = Frame(self.leftMargin, self.bottomMargin, self.width, self.height, id="normal")
        self.addPageTemplates(PageTemplate(id="guide", frames=frame, onPage=self.decorate))

    def decorate(self, canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(LIGHT); canvas.line(17*mm, 13*mm, A4[0]-17*mm, 13*mm)
        canvas.setFont("Helvetica", 7.5); canvas.setFillColor(SLATE)
        canvas.drawString(17*mm, 8*mm, "GCS Prioritization Index | Operational User Guide")
        canvas.drawRightString(A4[0]-17*mm, 8*mm, f"Page {doc.page}")
        canvas.restoreState()


story = []
story += [Spacer(1, 28*mm), P("GCS Prioritization Index", "CoverTitle"), P("Detailed Operational User Guide", "CoverTitle"), Spacer(1, 8*mm), P("A plain-language guide for support analysts, queue owners, shift leads, and operational users", "CoverSub"), Spacer(1, 15*mm)]
story += [P("Purpose", "H2x"), P("This guide explains how to use the dashboard safely and consistently during normal support operations. It focuses on what users see, what each item means, and what action to take."), P("Important: the dashboard recommends a working order. Salesforce remains the official system of record. Confirm the case in Salesforce before making a customer-facing or ownership decision.", "Callout"), Spacer(1, 16*mm)]
story += [table([["Document owner", "GCS Operations"], ["Audience", "Dashboard end users and shift leads"], ["Version", "1.0"], ["Published", date.today().strftime("%d %B %Y")], ["Application", "GCS Prioritization Index"]], [43*mm, 105*mm], header=False), PageBreak()]

story += [P("1. What the dashboard does", "H1x"), P("The dashboard brings active support cases into one view and places them in a recommended order. It combines Salesforce case details, response-time information, support level, escalation flags, SevOne flags, and customer sentiment. This helps users decide what to review first without manually comparing every case.")]
story += bullets(["Shows Salesforce cases whose status is <b>New, Open, or Assigned</b> for configured owners.", "Creates a Priority number: <b>1 is the first case to review</b>, 2 is next, and so on.", "Shows whether the response deadline is upcoming or overdue.", "Allows filtering by region, owner, support level, attention group, case number, and Heal Desk.", "Displays a Weightage Meter for the cases currently visible.", "Displays active SLA breach history and breached-case details.", "Refreshes source data in the background and tells you when newer data is ready.", "May send Slack shift digests and case-change alerts to configured analysts."])
story += [P("What it does not do", "H2x")]
story += bullets(["It does not replace Salesforce or update a case merely because you viewed it.", "It does not decide the correct customer response. Apply support judgment and follow normal escalation policy.", "It does not guarantee that a background update is already visible; the visible page changes only after you click <b>Refresh</b>."])

story += [P("2. Before you begin", "H1x"), P("You need the dashboard link, network access, and normal access to Salesforce. Slack is helpful if notifications are enabled for your team, but it is not required to view the dashboard."), P("Use the dashboard in a current desktop browser. A wider window makes the table easier to read. Never share passwords, access tokens, customer data, or screenshots outside approved company channels.", "Callout")]
story += [P("Opening checklist", "H2x")]
story += steps(["Open the approved dashboard link supplied by your team.", "Wait for the full-screen message <b>Calculating Index for your Priority</b> to finish.", "Confirm the main title reads <b>GCS Prioritization Index</b>.", "Check whether a green notice says newer data is available. If it does, click <b>Refresh</b>.", "Select the region or owner you are responsible for before acting on the list."])

story += [PageBreak(), P("3. Understanding the screen", "H1x")]
story += [table([
    ["Area", "What it means", "What the user should do"],
    ["Refresh", "Loads the newest available case snapshot into the visible dashboard.", "Click at shift start, when a new-data notice appears, and before an important queue decision."],
    ["Filter row", "Narrows the cases and both lower dashboard panels.", "Choose only the scope you are working on."],
    ["Case Priority Index", "The working list of cases in recommended order.", "Start with Priority 1 unless business context requires a different action."],
    ["Weightage Meter", "Total score of the currently visible cases, plus visible region and owner counts.", "Use it as a quick workload indicator, not as a personal performance rating."],
    ["Ongoing SLA Breaches", "Counts and details of active breached cases, split between Standard and Premium support.", "Open breached details and review overdue customer-facing actions promptly."],
    ["Footer", "Explains background refresh and audit retention.", "Remember that background data and visible data are not the same until Refresh is clicked."],
], [34*mm, 61*mm, 68*mm])]

story += [P("4. Filters and search", "H1x"), P("Filters work together. For example, selecting APAC, one owner, Premium support, and Heal Desk shows only cases meeting all four conditions.")]
story += [table([
    ["Control", "How to use it", "Important behavior"],
    ["Region", "Select ALL or one or more regions.", "Region controls which owners are available. If no active region remains, no cases appear."],
    ["Owner", "Select one or more names. Leave empty to include all available owners in the selected region.", "The selected owners also control the breach panel."],
    ["Support Level", "Select All support levels or one/more exact support levels.", "Premium/Plus cases may receive greater scoring weight."],
    ["Prioritization", "Choose All priority, Need Immediate Attention, or Need Secondary Attention.", "Immediate shows the first 25 ranked cases; Secondary shows positions 26-50. This filter is not applied during case-number search."],
    ["Case #", "Enter all or part of a case number. Separate several searches with commas.", "Search matches case numbers only. Search results are re-ranked from 1 for the returned list."],
    ["Heal Desk Only", "Turn on to show cases marked as Heal Desk.", "It also narrows the SLA breach panel."],
    ["Clear Search", "Appears when search text exists.", "Clears only the case-number search; other filters stay in place."],
], [30*mm, 63*mm, 70*mm])]
story += [P("Suggested filter routine", "H2x")]
story += steps(["Choose your Region.", "Choose your name in Owner, or leave Owner empty for the full regional queue.", "Keep All support levels unless your task is support-tier specific.", "Use All priority for the complete list or Immediate Attention for the first work block.", "Use Case # only when investigating known cases.", "Turn on Heal Desk Only only for that workflow."])

story += [PageBreak(), P("5. Reading the Case Priority Index", "H1x")]
story += [table([
    ["Column", "Plain-language meaning"],
    ["Region", "The support region assigned through the configured owner mapping."],
    ["Case", "Salesforce case number used to locate the official record."],
    ["Customer", "Customer or account associated with the case."],
    ["Owner", "Person currently responsible for the Salesforce case."],
    ["Support Level", "The customer's support entitlement, such as Standard, Premium, or Plus."],
    ["Severity", "Business/technical seriousness from S1 (highest) to S4 (lowest)."],
    ["Status", "Current Salesforce workflow state shown in this dashboard."],
    ["Escalated", "Yes means the escalation flag is set."],
    ["Sentiment", "System assessment of the latest customer tone: Positive, Neutral, Negative, Critical, or unavailable."],
    ["Last Comment", "Shows who made the latest relevant comment, helping you judge whether the customer is waiting."],
    ["SLA Deadline", "Time remaining until response is due, or how long it has been overdue."],
    ["Sevone", "Yes means the special SevOne flag is set."],
    ["Priority", "Recommended review position. Lower number means earlier review."],
], [38*mm, 125*mm])]
story += [P("Sorting", "H2x"), P("Click a column heading to sort by that column. Click it again to reverse the direction. A small triangle shows the direction. Sorting changes the viewing order only; it does not rewrite the calculated Priority values. To return to the normal recommended order, click Refresh or clear the temporary sort by returning to the standard workflow.")]
story += [P("Color cues", "H2x")]
story += bullets([f"<font color='{RED.hexval()}'>Red sentiment or overdue boxes</font>: review promptly.", f"<font color='{AMBER.hexval()}'>Amber/yellow boxes</font>: neutral sentiment or a deadline that is approaching.", f"<font color='{GREEN.hexval()}'>Green sentiment</font>: positive customer tone. This does not remove the need to meet the SLA.", "Red Priority badge: the number is the rank, not a severity code."])

story += [P("6. How priority is calculated", "H1x"), P("The application first assigns a hidden case score, then sorts higher scores first. If scores are similar, the closer or more overdue SLA helps determine order. The user normally acts on the displayed Priority number rather than calculating the score.")]
story += [table([
    ["Factor", "Effect in everyday terms"],
    ["SevOne", "Gets the maximum score (35) and normally rises to the top."],
    ["Escalated", "Gets a score of 30 unless the case is SevOne, which is higher."],
    ["Severity", "S1 generally ranks ahead of S2, then S3, then S4."],
    ["Support level", "Premium or Plus generally ranks above Standard when other facts are similar."],
    ["Sentiment", "Negative or Critical adds attention compared with Positive, Neutral, or unavailable sentiment."],
    ["SLA", "Overdue cases rank above comparable non-overdue cases. Longer overdue time adds a small tie-breaking bonus."],
    ["Low-priority record types", "Decommission Request and Customer Communication normally receive a low score of 0.25, unless escalated."],
], [43*mm, 120*mm])]
story += [P("Priority is guidance, not an instruction to ignore context. A live outage, manager direction, contractual commitment, safety concern, or fresh customer impact may require immediate action even if the displayed number is lower in the list.", "Callout")]

story += [PageBreak(), P("7. Recommended operating procedure", "H1x"), P("Use this procedure at shift start and repeat it after breaks, handovers, or a new-data notification.")]
story += steps(["Click <b>Refresh</b> and wait for loading to complete.", "Set Region and Owner to your working scope.", "Scan for SevOne, Escalated, Critical/Negative sentiment, and red Overdue items.", "Start with Priority 1 and review the case in Salesforce.", "Read the latest customer-facing activity, internal notes, ownership, severity, entitlement, and required next response.", "Take the correct action in Salesforce: respond, investigate, update the action plan, coordinate, reassign through the approved process, or escalate.", "Return to the dashboard. Refresh after material case changes if you need a newly calculated view.", "Continue down the ranked list, checking the SLA breach details as part of the same work cycle.", "Before handover, make sure active urgent cases have clear Salesforce notes, ownership, and next actions."])
story += [P("Decision check for each case", "H2x")]
story += bullets(["Is the customer currently waiting?", "Is the response overdue or nearly due?", "Is this SevOne, S1, or escalated?", "Is sentiment Negative or Critical, and what in the actual conversation supports that?", "Does the owner have the right responsibility and context?", "Is there a clear next step and an up-to-date internal note in Salesforce?"])

story += [P("8. Weightage Meter", "H1x"), P("The meter adds the scores of all currently visible cases. It also displays how many regions and owners are represented. The scale automatically expands based on the current total, so do not compare the visual needle position across unrelated filter selections.")]
story += bullets(["Use it to understand the combined urgency/weight of the list you are viewing.", "Filter consistently when comparing two queues.", "A higher number can mean more cases, more urgent cases, or both.", "Do not treat it as an individual productivity, quality, or performance score."])

story += [P("9. Ongoing SLA Breaches", "H1x"), P("This panel shows active overdue cases for New, Open, and Assigned statuses. Bars separate Standard and Premium support. The label above the chart shows the total active breaches after the current owner, search, and Heal Desk filters are applied.")]
story += steps(["Look at the total active breach count.", "Compare Standard and Premium bars for the recent months shown.", "Open <b>View breached case details</b> below the chart.", "Review Case #, Customer, Owner, Severity, Support, Status, Deadline, latest customer comment, and Subject.", "Open the official case in Salesforce and address the overdue customer-facing action."])
story += [P("The breach panel states that its data is refreshed hourly. The main dashboard also has a background refresh. Always click Refresh before a high-impact decision.", "Callout")]

story += [PageBreak(), P("10. Refresh and data freshness", "H1x")]
story += [table([
    ["What happens", "What it means for you"],
    ["Backend refresh runs about every minute", "The service checks for updated case data independently of the visible page."],
    ["Green 'New data available' notice", "A newer background snapshot exists. Click Refresh to show it."],
    ["Visible page stays unchanged", "Filters and sorts do not automatically replace your current snapshot."],
    ["Refresh button", "Starts a new visible load, clears the current visible snapshot, reloads owner configuration, and recalculates the dashboard."],
    ["Sentiment pipeline", "Runs in the background approximately hourly; a sentiment may be unavailable until processing finishes."],
    ["Audit history", "The application retains two days of case-change snapshots for operational audit purposes."],
], [58*mm, 105*mm])]
story += [P("Refresh is safe for normal use: it reloads the dashboard view. It does not by itself send a customer response or change a Salesforce case.", "Callout")]

story += [P("11. Slack notifications", "H1x"), P("If enabled and if your analyst profile is configured, the system can send operational messages in Slack. Treat these as prompts to review the case, not as a replacement for Salesforce.")]
story += [table([
    ["Notification", "When it may appear", "User action"],
    ["Shift digest", "At configured shift starts: APAC 6:00 AM, EMEA 2:00 PM, NA East 6:00 PM, NA West 9:00 PM (IST).", "Review the ranked cases, open the dashboard, refresh, and begin the shift workflow."],
    ["New assignment", "A case appears for a new owner between background snapshots.", "Confirm ownership and the next response in Salesforce."],
    ["Follow-up response", "A case moves to Assigned under supported conditions.", "Review whether a customer response or follow-up is required."],
    ["Priority/escalation change", "Rank changes or escalation becomes active.", "Refresh the dashboard and reassess the affected queue."],
], [37*mm, 67*mm, 59*mm])]
story += [P("Notification scope and recipients depend on operational configuration. If a colleague receives a message and you do not, contact the dashboard support owner rather than sharing credentials.")]

story += [P("12. Common situations and what to do", "H1x")]
story += [table([
    ["Situation", "Recommended response"],
    ["No open cases found", "Confirm Region/Owner scope. If still empty, there may be no eligible New/Open/Assigned cases or a source connection issue. Retry Refresh, then report it."],
    ["No cases match current filters", "Clear search, select All priority and All support levels, turn off Heal Desk Only, and widen Region/Owner."],
    ["Known case is missing", "Search the complete case number, verify its Salesforce status and owner, then Refresh. Closed or non-configured-owner cases are not expected."],
    ["Sentiment says N/A", "Continue using the actual case conversation. The sentiment pipeline may not have processed the case yet."],
    ["Sentiment looks wrong", "Trust the conversation, not the label. Do not edit customer facts to influence scoring. Report repeatable classification issues with the case number."],
    ["Priority looks unexpected", "Check SevOne, escalation, severity, support level, sentiment, SLA, and record type. Refresh and compare again before reporting."],
    ["Dashboard differs from Salesforce", "Treat Salesforce as authoritative. Refresh once. Record the case number and visible time, then report the mismatch."],
    ["Critical loading error", "Capture the non-sensitive error text and time, retry once, then contact support. Do not share secrets or customer data in an unapproved channel."],
    ["Audit/SLA sync warning", "The dashboard may still work, as the warning says. Continue cautiously and report the warning to support."],
], [52*mm, 111*mm])]

story += [PageBreak(), P("13. Safe use and operational controls", "H1x")]
story += bullets(["Use company-approved devices, browsers, networks, and communication channels.", "Do not copy customer content into public tools or personal notes.", "Do not make ownership or escalation changes solely from a color or score; verify the Salesforce record.", "Keep Salesforce notes clear enough for the next analyst to understand the status and next action.", "Report access issues through the approved support path. Never ask another user to share credentials.", "When sharing evidence, minimize customer information and redact secrets."])
story += [P("Suggested issue report", "H2x"), P("Include: date/time and timezone, dashboard URL or environment, your selected filters, affected case number(s), expected behavior, actual behavior, whether Refresh was tried, and a redacted screenshot if allowed. Never include passwords, tokens, or secret values.")]

story += [P("14. Quick reference: start-of-shift checklist", "H1x")]
story += [table([
    ["Done", "Check"],
    ["[ ]", "Open the approved dashboard and click Refresh."],
    ["[ ]", "Select your region and owner scope."],
    ["[ ]", "Review Priority 1 onward."],
    ["[ ]", "Check SevOne, Escalated, Critical/Negative sentiment, and Overdue cases."],
    ["[ ]", "Open SLA breached-case details."],
    ["[ ]", "Confirm each selected case in Salesforce before action."],
    ["[ ]", "Record next steps and ownership in Salesforce."],
    ["[ ]", "Refresh again after significant queue changes or a new-data notice."],
], [16*mm, 147*mm])]

story += [P("15. Quick reference: end-of-shift handover", "H1x")]
story += bullets(["Refresh and review the remaining top-ranked and overdue cases.", "Ensure SevOne, S1, escalated, and Critical-sentiment cases have current notes and clear next steps.", "Confirm ownership is correct for work continuing into the next shift.", "Communicate blockers and time-sensitive commitments through the approved handover channel.", "Do not rely on a screenshot as the handover record; update Salesforce."])

story += [P("16. Frequently asked questions", "H1x")]
faqs = [
    ("Is Priority 1 always the case I must work first?", "It is the recommended first review. Apply live incident context, management direction, customer commitments, and support policy after checking Salesforce."),
    ("Why did priority change after Refresh?", "Case facts, SLA time, sentiment, assignment, escalation, or other cases in the filtered list may have changed."),
    ("Why does search produce new Priority numbers?", "Search results are deliberately re-ranked from 1 within the returned result set."),
    ("Does changing a filter change Salesforce?", "No. Filters only change what you see."),
    ("Does clicking Refresh change Salesforce?", "No. It reloads and recalculates the dashboard using source information."),
    ("Can I compare Weightage totals between owners?", "Yes, but use the same region, support-level, attention, search, and Heal Desk settings. Remember that case count also affects the total."),
    ("What if the chart shows no breaches?", "It means no active breach record matches the current filter scope. Clear restrictive filters and Refresh before concluding there are none."),
]
for q, a in faqs:
    story += [KeepTogether([P(q, "H2x"), P(a)])]

story += [Spacer(1, 8*mm), P("End of guide", "H2x"), P("For access, data-quality, or application issues, use your team's approved GCS dashboard support channel and include the safe issue-report details listed above.", "Callout")]


if __name__ == "__main__":
    GuideDoc(str(OUTPUT)).build(story)
    print(OUTPUT)
