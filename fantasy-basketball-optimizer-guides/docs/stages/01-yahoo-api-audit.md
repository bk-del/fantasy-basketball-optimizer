# Stage 01 — Yahoo Fantasy access and capability audit

**Goal:** establish **verified** OAuth 2.0 access and the precise set of available Yahoo Fantasy Basketball fields; refuse to invent unavailable historical context.

## Implement

- Read `STATUS.md`; inspect only Stage 00 artifacts relevant to clients/config.
- Create an `YahooClient` interface and explicit fixture implementation, with throttling/backoff, request timeout, structured sanitized diagnostics, and secure OAuth token handling. Never commit client secrets or access/refresh tokens.
- Check current official Yahoo developer requirements and documentation at execution time. Record verified auth scopes, base URL, rate limits (if documented), and permitted read resources; mark uncertainty rather than extrapolate.
- Create a **capability matrix** (`docs/YAHOO_CAPABILITIES.md`) for league settings, 9-CAT scoring, roster eligibility, owned and unowned players, current/archived player stats, games or stat windows, matchups, schedules, injury/status information, transactions, historical availability and historical player-game records. Classify each: confirmed via authorized sample / documented only / unavailable / unknown.
- Implement `fantasy auth status` (safe metadata only), `fantasy audit` (authorized, read-only capability checks with minimal API calls), and `fantasy audit --fixture` usable offline.
- Use narrow fixture tests for success, missing fields, expired/revoked auth, timeout and API limit response. Avoid unnecessary request volume.

## Acceptance criteria

- A reproducible audit report identifies which required inputs truly exist and their freshness/granularity.
- Integration supports fixture mode without credentials; real mode refuses unapproved/absent credentials with actionable error.
- No use of unofficial scraping; no external NBA feed without owner approval.
- Explicitly identify blockers for injury-on/off teammate analysis and historical availability if Yahoo does not provide them.
- Update `STATUS.md`, including whether Stage 02 must be fixture-only.

## STOP / approval gate

If Yahoo access is pending, do not wait indefinitely or manufacture a successful login. Finish the fixture route and stop with the real-data blocker recorded.
