# Yahoo capability audit — Stage 01

Checked 2026-10-12. No authorized sample has been obtained. The bundled JSON/XML
is handmade, with synthetic identifiers, values and observation time. It proves
the offline audit works; it is not evidence of Yahoo access or field availability.

## Official references and verification limits

- [Access application](https://sports.yahoo.com/developer/access/): the indexed
  official page says access is provisioned after approval. Owner submission and
  approval remain external prerequisites.
- [Fantasy documentation](https://sports.yahoo.com/developer/docs/): OAuth 2.0,
  app registration with Fantasy read permission, and API base
  `https://fantasysports.yahooapis.com/fantasy/v2` are documented. GET resource
  families include league settings/players/scoreboard/transactions and team roster.
  Player date/season stats are documented; an NBA date is not necessarily an NBA
  game identifier. Documentation examples use both HTTP and HTTPS XML namespace
  identifiers; actual requests always use HTTPS.
- [OAuth authorization-code guide](https://developer.yahoo.com/oauth2/guide/flows_authcode/):
  authorize at `https://api.login.yahoo.com/oauth2/request_auth`, exchange/refresh
  at `https://api.login.yahoo.com/oauth2/get_token`; replacement refresh tokens
  supersede previous ones. Initial consent/token exchange remains owner-run.

Direct document fetches returned HTTP 429; the above facts were checked against
official indexed page content. Exact current Fantasy scope identifiers (including
`fspt-r`), grant provisioning, numeric quotas and NBA/account-specific coverage
are **unknown**. Do not guess scopes or adopt third-party quotas. Generic OAuth
documentation is not proof that this application has Fantasy permission.

## Capability matrix

Classification applies to production Yahoo data. No row is confirmed via an
authorized sample. A missing fixture/sample field does not prove unavailability.

| Required input | Classification | Probe / outstanding verification |
|---|---|---|
| League settings | Documented only | settings; exact league rules unverified |
| 9-CAT scoring | Documented only | category definitions; actual nine categories/ties unverified |
| Roster eligibility | Unknown | candidate eligible_positions; exact field/position semantics need verification |
| Owned players | Documented only | roster; one team's current snapshot |
| Unowned/addable players | Unknown | five league players do not establish ownership/waiver eligibility |
| Current player stats | Documented only | stats; counts/makes/attempts completeness unverified |
| Archived player stats | Documented only | no historical probe; season access unverified |
| Games/stat windows | Documented only | coverage_type; no verified NBA game key |
| Matchups | Documented only | scoreboard; scoring-period semantics unverified |
| Future NBA schedules | Unknown | no confirmed schedule source |
| Injury/player status | Unknown | candidate status; exact field and publication time need verification |
| Transactions | Documented only | five completed events; pending claims/history not audited |
| Historical availability | Unknown | no point-in-time addability observations |
| Historical player-game records | Unknown | date/window totals are not proven per-game records |
| Teammate injury/on-off context | Unknown | no verified teammate lineup/absence fields |

No capability is labeled unavailable solely because access is pending. Teammate
on/off analysis, reconstructed historical waiver availability and player-game
backtests are blocked until their required inputs are verified. Missing context
must remain explicit and widen uncertainty in later stages. Stage 02 must remain
fixture-only unless the owner provides approved access and authorized samples.

## Commands and token handling

```bash
uv run fantasy auth status
uv run fantasy audit --fixture
uv run fantasy audit --fixture > data/fixture-audit.json
```

Create ignored `data/` before redirecting there (`mkdir -p data`). Reports contain
field presence, SHA-256 payload hashes, source-unknown freshness and granularity,
not raw responses or account/player identifiers. Fixture output is deterministic;
its fixed observation time is explicitly synthetic. No sample can establish
complete history or exact source publication time.

Live mode is opt-in: after approval/consent, set `YAHOO_ACCESS_APPROVED=1`,
`YAHOO_LEAGUE_KEY`, `YAHOO_TEAM_KEY` and optionally `YAHOO_TOKEN_FILE` in the local
environment. There is no automatic `.env` loading. Default token path is ignored
`.oauth/tokens.json`. Store a regular, user-owned 0600 file containing
`access_token` and timezone-aware ISO-8601 `expires_at` (computed when obtaining
the token from its expiry duration). Do not paste tokens into commands, logs,
Markdown or Git. `auth status` reports local metadata only; it does not verify
approval, scopes or server-side revocation.

`fantasy audit` makes six allowlisted GET probes, with at most three attempts
each, a 10-second timeout, at least one second between starts, and exponential
backoff for 429/transient server errors. Numeric Retry-After is honored only up
to ten seconds; longer or unparsed date values stop the audit so the caller can
retry later. This is a conservative local policy, not Yahoo's documented quota.
Redirects are refused. Payloads are bounded, XML DTD/entity declarations rejected,
and error/log messages omit request URLs, response bodies and credentials.

Expired or denied tokens stop without retrying authorization. Automatic login,
refresh and token writing are deliberately deferred while access is pending;
an owner must refresh through the approved OAuth flow and replace the private
file, including any rotated refresh token. This avoids unverified auth success
and unintended credential changes. Neither live consent nor refresh was tested.
