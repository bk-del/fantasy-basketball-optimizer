# NBA intelligence data audit

The cached snapshot contains more usable historical player data than the original
two-season adapter exposes. The separate ESPN player box table supports **six
complete regular seasons, 153,546 source player-game rows**: 2018–19 and
2020–21 through 2024–25. These are conditional recorded player rows, not complete
pregame roster or participation panels. Existing NBA incumbent inputs remain
unchanged. No new source data was downloaded and no new model was trained in this
audit.

The executable audit verifies all 115 immutable files (99,882,513 bytes) against
the existing manifest before scanning source rows. Its measured results are in
[nba-intelligence-data.json](benchmarks/nba-intelligence-data.json). Source commit
is `62df92a05f16b57498851167b8289cf9ec316aea`, retrieved
`2026-10-13T02:04:28.124793+00:00`.

| Source / dataset | Season end years | Grain and identifiers | Timing | Missingness / reliability | Storage, cost and expected value |
|---|---|---|---|---|---|
| Cached NBA player logs | 2025–26 complete; 2010–24 sparse and duplicated | NBA player/game/team IDs, player-game | Event date joined from team logs; publication unknown, actual retrieval retained | Incumbent 64,695 rows/697 players, including zero rows; older partitions unsuitable as complete player history | Existing immutable Parquet; free cached input; incumbent foundation |
| Cached ESPN player boxes | Complete 2019,2021–25; incomplete 2020,2026 | NBA player IDs; source game key verified against NBA game IDs; team IDs recovered by exact game/home join | Same date/retrieval limitations; no verified historic publication or revision time | Six-season player keys unique; makes/attempts and points identities pass; starter/played fields present | Existing Parquet, no download; supports much broader player-history research |
| Cached ESPN team boxes | 2019–26 | Team-game, stable NBA team IDs, game and home-side flag | Final observed game data | All player rows uniquely match team/game/home; team abbreviation agrees; matches NBA team/game keys | Existing Parquet; recovers missing historical team IDs without player-name matching |
| Cached NBA team logs and advanced box statistics | 2010–26 | NBA team-game, game date, opponent from paired team IDs, pace/possessions | Historical final snapshots; no pregame schedule publication history | Exact paired-game coverage checked for ESPN comparison; some small player/team aggregate differences remain | Existing Parquet; supports lagged team/opponent context, rest dates and shared-game relationships |
| Membership and teammates | Six supported ESPN seasons | Observed player-team-game co-occurrence | Valid as an observed relationship after game availability | Does not establish roster start/end dates, current membership, positional competition or absence reason | Derive in DuckDB; low storage cost; useful temporal graph prerequisite |
| Starting status / playing time | Six supported ESPN seasons | Player-game starter flag and minutes text | Retrospective game result, usable only after origin-known history | Actual target starter flag cannot enter pregame features; source played flag is not an injury label | Existing source; lagged rotation and minutes research supported |
| Injuries / availability | None verified locally | No stable-ID, timestamped injury panel | Unknown | Missing row does not imply injury, inactive, suspension, rest or DNP | Critical blocker for valid pregame availability and injury redistribution claims |
| Play-by-play / substitutions / lineups | None in selected processed cache | No verified event/lineup table | Unknown | Box-score co-occurrence is not shared-court time | Acquisition/processing required; no lineup or possession-level claim |
| Transactions / coaches / positions | None verified as temporal local records | No validated historical relationship source | Unknown | Final-season team totals cannot reconstruct trade dates or rotation hierarchy | Unsupported; do not infer from future membership |
| Odds / implied totals | None verified or licensed locally | None | Unknown | No paid service or unverified archived market joined | Unsupported; no forecast adjustment |
| Future NBA schedule / Yahoo rules and ownership | None verified for live use | Existing fixture rules remain synthetic | No current timestamped schedule/rules panel | Historic realized games do not prove a pregame-known future schedule | Live and multiweek decision forecasts remain blocked |

All cached data uses the owner-authorized mirror. This audit does not establish
rights to redistribute raw data or operate a public product. No raw observations
or learned artifacts are added to Git.

## Complete and quarantined ESPN partitions

Coverage is measured against the cached NBA team logs, preserving the shortened
2020–21 season rather than imposing an 82-game assumption.

| End year | Player rows | ESPN games | NBA team-log games | Result |
|---:|---:|---:|---:|---|
| 2019 | 26,098 | 1,230 | 1,230 | Usable |
| 2020 | 20,498 | 971 | 1,059 | Quarantined: 88 missing games |
| 2021 | 23,053 | 1,080 | 1,080 | Usable |
| 2022 | 25,972 | 1,230 | 1,230 | Usable |
| 2023 | 25,830 | 1,230 | 1,230 | Usable |
| 2024 | 26,290 | 1,230 | 1,230 | Usable; eight source played=0 rows retained |
| 2025 | 26,303 | 1,230 | 1,230 | Usable |
| 2026 | 26,605 | 1,228 | 1,230 | Quarantined: two missing games |

The loader rejects incomplete requested seasons, duplicate/multiplied player-game
keys, unmatched or inconsistent team identities, unknown count values, invalid
shooting arithmetic, noninteger counts and inconsistent point totals. Team IDs
are entirely null in ESPN player rows for 2022–25. They are recovered using
`(season, game_id, home)` to the ESPN team box, then verified against the exact
NBA `(game_id, team_id)` team log. Source team abbreviations are a cross-check;
player names never participate in joins. Game keys are namespaced `espn:` in
derived observations, with the separately verified NBA game ID retained.

Cross-source aggregate differences are real: for seasons 2019/2021/2022/2023/
2024/2025, player PTS sums disagree with NBA team PTS in 0/0/4/7/11/3 team-games.
Other small count discrepancies also exist, plausibly including later revisions;
their cause is unverified. Team turnovers include events not assigned to an
individual player, so they cannot be used as an equality gate on summed player
turnovers. This loader preserves ESPN player counts and NBA lagged team context
with separate provenance; it does not silently repair counts to force equality.
Full game coverage does not establish perfect historical statistics or individual
participant coverage.

## Operational offline interface

From repository root:

```bash
UV_CACHE_DIR=/tmp/fantasy-stage01-uv-cache uv run --offline --no-sync \
  python scripts/audit_nba_intelligence_data.py
UV_CACHE_DIR=/tmp/fantasy-stage01-uv-cache uv run --offline --no-sync \
  pytest -q tests/test_intelligence_data.py
```

`fantasy_optimizer.intelligence_data.observations(root, policy="strict",
seasons=COMPLETE_SEASONS)` returns `(records, provenance)`. Each record has the
existing `advanced_features.observations` fields: `player`, `id`, `team`, `season`,
`day`, `end`, `available`, eleven-count NumPy `counts`, eleven nonnegative shooting
`primitive` counts, parsed `minutes`, and the same seven lagged-context values.
Additional fields retain `nba_game_id`, `starter`, `source_played`, source name,
`observed_at=None`, actual `ingested_at`, and `availability_status="unknown"`.

Default strict availability admits rows only at actual retrieval. Explicit
`retrospective_next_day` uses next-date noon UTC with virtual ingestion, preserving
actual retrieval separately. Dates are source game labels, not tip-off timestamps.
This assumption cannot recover unpublished or subsequently revised information.
Training must keep current-game context, actual starter/played labels and future
co-membership out of prediction inputs. Default research seasons are fixed and
source hashes, code hashes and missing minutes are reported. The existing
statistical incumbent and its cache/registry are untouched.

The expanded dataset has **not** been passed through a new feature build, learner
training, graph construction or final evaluation in this audit. Previous newest
periods have already been examined. Freeze a new chronological research protocol
before model fitting; use disclosed rolling validation unless a defensible fresh
final period exists. Do not relabel the already examined 2025/2026 outcomes as an
untouched holdout.

An actual default six-season loader invocation completed with **153,546 rows /
1,150 NBA player IDs**, 343 unparseable/unknown-minute rows, and event dates
2018-10-16 through 2025-04-13 in 9.32539 seconds locally. This measures source
verification and Python record construction, excluding imports; no RAM or GPU
benchmark was taken. Source hash:
`b570911ac6f376f60ed2418666b984bd05c27329accafde718a63303db4e2c44`.

## External-source verification and constraints

The mirror's [upstream documentation](https://github.com/llimllib/nba_data) offers
a v2 public object-store catalog and season-partitioned NBA-ID files. Its
[data dictionary](https://github.com/llimllib/nba_data/blob/main/docs/DATA_DICTIONARY.md)
states that v2 player logs omit DNPs, final rosters are latest/final snapshots,
and some source histories are revised. Direct v2 ingestion therefore needs a new
coverage/identity/time gate; it cannot silently replace the incumbent's zero-row
semantics. No new raw v2 file was fetched here.

Restricted stdlib URL reads to GitHub, the mirror object store and official NBA
failed with `[Errno -3] Temporary failure in name resolution`. An approved
unrestricted public GitHub metadata read succeeded; DNS is an environment limit,
not evidence that the dataset is unavailable. The returned moving HEAD was
`ef67a76a2b4b1c0fc215147cf6983e56b08f3f44`, dated `2026-10-14T03:31:53Z`, later
than this session's declared date. It was not adopted as a source pin. The cached
snapshot is sufficient for this bounded offline expansion.

[Official NBA injury reporting](https://official.nba.com/nba-injury-report-2025-26-season/)
describes recurring report deadlines and continuing daily updates. The old
2024–25 landing URL redirects to 2025–26; a landing page alone does not validate a
historical archive, NBA-ID mapping or original publication times. No report was
silently translated from player names into confirmed historical injuries.

[NBA Terms §9](https://www.nba.com/termsofuse) restrict fantasy-game and statistics-
database uses. Public accessibility does not resolve permission. The
[nba_api MIT license](https://github.com/swar/nba_api/blob/master/LICENSE) concerns
its software; it does not establish a license for third-party sports data. No
explicit data license was verified for the mirror. Further acquisition or
redistribution should resolve those source-specific rights; this audit makes no
legal determination and introduces no paid service or restricted-endpoint scrape.

Verification for this atomic audit: Ruff lint/format, strict mypy on the loader,
two focused tests (8.04 seconds, no local skips), executable audit, and an actual
six-season loader smoke. Whole-project checks and research continuation belong to
the parent milestone handoff in the existing STATUS.md.
