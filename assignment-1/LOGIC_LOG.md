# Logic Log

## Trigger choice

Poll GitHub's documented public repository Events API and select `WatchEvent` with `payload.action=started`. This works for the requested `n8n-io/n8n` repository with the supplied token; the separate stargazer-list endpoint denied access. Fetch `/users/{login}` for enrichment. API version is pinned to `2026-03-10`.

## Rate limits

Authenticated reads normally have a 5,000/hour primary allowance. Polling reads at most three pages each cycle: at one minute per cycle that is at most 180 discovery calls/hour. One profile per worker run adds at most 60/hour at the default cadence, excluding retries and explicitly requested demo replays. GitHub credentials may share their allowance with other applications.

The service spaces GitHub requests at least one second apart and reads `X-RateLimit-Remaining`, `X-RateLimit-Reset`, and `X-Poll-Interval`. A returned polling interval above 60 seconds delays the next poll. Primary exhaustion delays requests until the reset time plus a margin. Secondary throttling honors `Retry-After`, uses a minimum 60-second cooldown, and backs off up to one hour. The cooldown is durable across restarts. An ordinary permission error does not masquerade as a rate limit. HTTP 5xx/transport failures preserve work for subsequent scheduled runs. No ETag quota savings are claimed in this version.

## State and qualification

SQLite records event IDs, baseline state, queue status, lease tokens, profile, pitch, and outcomes. A discovery batch is committed atomically only after all requested pages succeed. New event identity, not a timestamp watermark, drives processing; delayed older events can still qualify. The numerical rule is exactly `followers > 100 OR public_repos > 50` in the n8n IF node and checked again before delivery.

## AI and output

The native n8n Basic LLM Chain and Gemini Chat Model generate the rationale. The prompt treats profile values as untrusted data, requests a single short sentence, and forbids invented needs or authority. Output validation rejects empty, multiline, overlong, and obvious multi-sentence responses; it is a conservative check, not a complete natural-language sentence parser. Slack text fields do not interpret user-controlled mentions/formatting.

## Recovery and limits

A queue item has up to five attempts. Slack 429 responses are rescheduled using Retry-After and reuse the saved pitch. Successful posts require `200` and `ok`. Ambiguous send outcomes become `unknown`, requiring channel inspection rather than an automatic resend. n8n execution history and queue status provide diagnostics.

GitHub Events is a bounded, delayed feed, not a complete real-time stream. A busy repository, downtime, and events disappearing between scans can cause missed stars. Disjoint snapshots are flagged as possible gaps, but overlap is not proof of full coverage. The default worker consumes one lead per minute and can accumulate a backlog. For stronger guarantees, use a repository webhook with the required owner/admin access.

Sources:
- https://docs.github.com/en/rest/activity/events
- https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api
- https://docs.github.com/en/rest/activity/starring
- https://docs.slack.dev/messaging/sending-messages-using-incoming-webhooks
