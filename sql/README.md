# GCS notification setup

Shift-start Slack digest notifications are connected to `main.py`. They remain
inactive while `GCS_SLACK_ENABLED` is unset or `false`, and dry-run while
`GCS_SLACK_DRY_RUN=true`.

Before future activation:

1. Review and manually apply `gcs_notification_schema.sql` in the configured
   Snowflake database/schema.
2. Set an eligibility rule such as `GCS_NOTIFICATION_SCORE_THRESHOLD=30`.
3. Verify active analyst names and emails in `SF_CASE_ANALYST`.
4. Test with `GCS_SLACK_ENABLED=true` and `GCS_SLACK_DRY_RUN=true`.
5. Only then set `GCS_SLACK_DRY_RUN=false` and explicitly schedule or invoke the
job. Shift starts are APAC 06:00, EMEA 14:00, NA EAST 18:00, and NA WEST
21:00 IST.

The Slack bot token is loaded from Delinea folder `433`, secret
`Agentic Support Slack Bot`, field `API Key`; it is never read from this file.
