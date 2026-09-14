# Validation record — 2026-09-13

## Observed live results

- n8n 2.38.6 workflow imported successfully with local credential references.
- First actual CLI execution: 197 public repository events, 19 WatchEvent star records, baseline=true, no queued alert and no historical send.
- A later real event was discovered: 20 star records total, one new record. Its live GitHub profile failed the fixed qualification rule and reached Record Rejection.
- No qualifying profile was found among the initial 19 observed stars. A real-star qualifying replay was therefore not performed.
- A explicitly labeled test input using octocat's real GitHub profile qualified without changing thresholds. The actual n8n Gemini Chat Model and Basic LLM Chain completed successfully. Send Slack Alert returned status=sent, which requires Slack HTTP 200 and body `ok`.
- This test input simulates the trigger only. It is not evidence that octocat starred n8n during the test.
- After restarting both services, SQLite retained baseline=19, rejected=1, sent=1.
- Next actual workflow execution saw zero new records, no available job, and did not reach the Slack node. No duplicate alert was sent.
- Earlier direct Slack connection test returned 200 / ok.

## Automated checks

20 deterministic tests passed: threshold boundaries; invalid profile values; baseline behavior; delayed-event deduplication; polling interval; atomic pagination failure; three-page discovery; gap heuristic; primary reset; secondary cooldown; permission errors; lease expiry; rejection; delivery guard; acknowledged send; uncertain send; Slack throttling with pitch reuse; crash during send; retry exhaustion; pitch validation; plain-text Slack formatting (several behaviors share tests).

## Limits of this verification

Slack acceptance is confirmed by its webhook response; no Slack history/read token was requested. Screenshot and recording are left to the user. Scheduled activation and continuous operation have not been tested; workflow is delivered inactive. AI/rate-limit/recovery edge cases are primarily covered by deterministic service tests, not forced live provider failures. GitHub event-feed completeness cannot be guaranteed. The workflow JSON depends on the included state service.

## Non-empty bio validation

The real tiangolo profile had a non-empty bio, 32,185 followers and 54 public repositories. The native n8n workflow generated and sent a labeled test alert. Review identified an unsupported founder inference in that first pitch; the prompt was tightened to forbid inferring job titles from company affiliation. A corrected rerun is recorded below when verified.

Corrected rerun succeeded through the native Gemini and Slack nodes. Verified pitch: "Because this user builds FastAPI Cloud and works extensively with Python and APIs, they may find AI customer-support automation relevant to their ongoing development of developer-focused infrastructure tools." The test remained labeled TEST INPUT; no claim of a new star by tiangolo was made. The stricter prompt was published and n8n restarted.
