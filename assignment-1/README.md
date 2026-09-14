# Lead Sniper: GitHub events → Gemini → Slack

Yellow.ai assignment implementation using n8n 2.38.6, a small Python/SQLite companion service, GitHub's public Events API, a native Gemini LLM node, and a Slack incoming webhook. The repository is `n8n-io/n8n`.

## What runs where

The n8n workflow visibly orchestrates polling, profile enrichment, exact qualification, Gemini generation, and Slack delivery. The companion HTTP service provides durable event discovery, queue leases, GitHub throttling, and Slack delivery state. The workflow JSON therefore requires this service; it is not a standalone n8n Cloud import.

Filter: `followers > 100 OR public_repos > 50`. Thresholds are never lowered for live operation. The LLM receives only bio/company and writes one sentence about potential relevance to AI customer-support automation. Missing facts must not be invented. Slack uses plain-text blocks for profile and AI text.

## Start locally

Requirements: Docker Desktop running and Python 3 on the host. Commands below run from this directory.

1. Copy `.env.example` to `.env` only if `.env` does not already exist.
2. Fill `GITHUB_TOKEN`, `GEMINI_API_KEY`, and `SLACK_WEBHOOK_URL` locally. The GitHub token needs public API read access. Choose an available Gemini model in `GEMINI_MODEL`.
3. Run `python3 scripts/setup.py` to create encryption and internal service secrets.
4. Set `SLACK_SEND_ENABLED=true` when this channel is ready to receive alerts.
5. Run `docker compose up -d --build`.
6. Run `python3 scripts/install.py` to import encrypted credentials and the inactive workflow. It does not print secrets.
7. Run `docker compose restart n8n` after import.
8. Open http://localhost:5678 and complete local n8n owner setup if prompted. Open **Lead Sniper - GitHub Events to Slack**.
9. Execute manually to establish a baseline. Publish/activate only when ready for continuing one-minute polling.

The first successful poll records existing events without posting historical alerts. Each execution processes one queued lead. At this setting throughput is up to 60 leads/hour; a backlog remains durable. The machine and Docker must remain running for the schedule to run.

`python3 scripts/run.py` runs the actual imported workflow from the command line with a separate task-broker port and prints a concise result. Do not run concurrent CLI executions. `python3 scripts/control.py status` displays queue counts and GitHub budget without credentials.

## GitHub access and coverage

The stargazer-list endpoint returned 403 with this account for the example repositories. The supported alternative `/repos/n8n-io/n8n/events` returned public `WatchEvent` records with `payload.action=started` and actor usernames. These are star events, not subscription notifications.

The implementation checks up to three pages (300 events), respects `X-Poll-Interval` with a 60-second minimum, and deduplicates star event IDs. It accepts newly observed events even if their timestamps are older than previously observed events, handling delayed publication. Every star is enriched via `/users/{login}`.

GitHub's Events API is delayed (documented 30 seconds to six hours) and bounded. It cannot guarantee every star is observed. A disjoint feed snapshot is recorded as a possible gap; this heuristic cannot detect all gaps. The first baseline and any events that disappear before polling are intentionally not alerted. For complete real-time delivery, repository webhook access would be required.

## Tests and demo

- `python3 -m unittest discover -s tests -v` runs deterministic local tests without network calls.
- `python3 scripts/control.py replay` queues a labeled replay of one qualifying real star already observed. It checks at most 30 recent stored profiles. Run `python3 scripts/run.py` to process it. Slack labels replay messages `[TEST REPLAY]`.
- Replay preserves the real thresholds and original event record. It is a test, not proof of a new star being created at that instant.
- `FIXTURE_MODE=true` is only for an isolated disposable test deployment with separate volumes. It replaces GitHub/Slack with deterministic fixtures. Never enable it in the live deployment.
- `ALLOW_TEST_INPUT=true` enables `python3 scripts/test_input.py octocat`: this simulates an event using a real profile and marks Slack `[TEST INPUT]`. It does not claim octocat recently starred the repository. Disable the flag after testing.
- The user will create the screenshot and demo recording.

## Failures

A pending item is leased for ten minutes. A crashed worker can be retried after its lease expires, up to five attempts. A profile/enrichment failure is requeued with backoff. The n8n AI node retries three times and then requeues the item. A Slack 429 preserves the pitch and retries later; it does not call Gemini again for that retry.

Slack success requires HTTP 200 with body `ok`. Incoming webhooks do not return a message ID, so API acknowledgment is the delivery evidence. A timeout, unexpected response, or interrupted send is marked `unknown` and is not automatically resent: inspect the channel before any manual recovery. This prevents blind retries of possibly delivered messages but is not an exactly-once guarantee.

The `/status` endpoint and n8n execution history expose failures. There is no automatic operational paging. The delivered workflow is inactive; activate it in n8n when you want ongoing alerts.

## Secrets and submission

Never submit `.env`, Docker volumes, database files, execution dumps, or credentials. The workflow JSON contains credential references only. Keep the n8n encryption key and volumes together. Re-importing is a setup operation and imports the workflow inactive; avoid it during active runs.

Submit `workflows/lead-sniper.json` with this project and `LOGIC_LOG.md`. The companion service and setup steps are necessary for reproducibility.
