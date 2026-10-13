# Stage 06: count shifts and breakout-label protocol

`fantasy context --fixture` reports deterministic count-only diagnostics and
explicit source gaps. No authorized Yahoo samples have confirmed minutes,
exposure, role/opponent context or historical availability. The existing
[capability audit](YAHOO_CAPABILITIES.md) was revisited without adding a live probe
or changing its production classifications. No new external data, package,
model, storage schema or C++ implementation is needed.

## Pre-registration (2026-10-12)

Protocol `weekly-production-breakout-v1` is fixed before any model fitting.
Its full serialized settings and hash appear in each report. This is a sustained
weekly-production label, not a verified category-adjusted replacement-value
label: live category rules, replacement pools and exposure are unverified.

- Origin features require six consecutive, completed seven-day windows ending
  at origin, observed and ingested at/before that origin. Four older windows form
  the baseline; two recent windows measure a possible shift.
- Require baseline mean weekly PTS at least 10. A diagnostic shift requires both
  recent windows individually at least 25% above baseline, a recent mean gain of
  at least 25%, and a standardized mean difference of at least two.
- Standardize by `sqrt(var(old)/4 + var(recent)/2)` with a one-point denominator
  floor, so constant toy counts cannot produce infinite evidence. This is a
  transparent shift heuristic, not a formal change-point significance test or
  probability of a breakout. No threshold was fitted to the fixture results.
- The future label horizon is exactly two consecutive weeks starting at origin.
  Both future PTS totals must reach 125% of the frozen origin baseline.
- Require at least four future games in total and observed played/scheduled
  availability of at least 75% in each future week. Missing games or schedule
  evidence, incomplete counts/horizon or unmet exposure minimums exclude the case;
  they are not false labels. The label is false only for an eligible completed
  case whose future production does not sustain the threshold.

`ExposureEvidence` is an internal proposed contract, not a Yahoo field assertion.
It requires aware timestamps, completed weekly events and explicit source
text. The command supplies no exposure evidence because none exists in the
fixture history. Tests use separately handmade exposure metadata to verify the
label arithmetic; that test evidence is not production data.

## Time boundaries and missing context

Reuse Stage 03 `known_windows`: filter event, observation and ingestion times
before revision selection. Feature hashes contain only windows actually used at
origin. Future targets and corrections cannot alter those features. Labels are
a separate function with an explicit evaluation time: only future outcome and
exposure records already observed/ingested by evaluation can label the case.
Outcomes have a separate hash. Conflicting exposure revisions require explicit
resolution rather than silently overwriting metadata. Naive timestamps, invalid
thresholds, impossible game counts and backward evaluation times reject.

Only weekly PTS count changes are computed. Minutes, statuses, game exposure,
transactions, opponent/role, teammate injury on/off and usage features are
explicitly skipped as unverified. Coverage and missingness accompany each
feature; missing counts remain missing. A weekly count gain may reflect more
games, variance or production. No starting role, depth-chart promotion, injury
absence or causal teammate explanation is inferred.

Counts-only diagnostics do not adjust active forecasts. Stage 03's provisional
recency baseline (`weekly-counts-v1`) and its existing joint exposure uncertainty
widening remain intact, including wider small-history shocks. Null availability
probability/minutes remain null. No unsupported extra role multiplier is applied
or claimed calibrated. Diagnostics provide reviewable alarms and data-readiness
checks; they are not waiver recommendations or automatic model promotion.

## Evaluation and model gate

The command uses chronological rolling origins on the 48 handmade weekly windows
for four fictional players. It does not randomly shuffle player-games or convert
weeks into fake games. Final as-of report: all four count-shift alarms are false;
relative recent gains range from 10.3% to 15.1%, below the registered 25% threshold.
There are 28 candidate label origins and **zero usable labels**. Twenty have a
complete future horizon but lack game/availability evidence; eight horizons are
incomplete at the fixture as-of time.

Precision, recall, probability calibration and decision uplift versus Stage 03
are explicitly null with reasons. Zero verified Yahoo histories/usable labels
cannot establish improvement. No supervised learner or LightGBM is installed or
trained, no probability is invented from a shift statistic, and no synthetic
accuracy/calibration/promotion claim is made. The Stage 03 model stays active until
strictly later verified periods establish improvement. A real category-adjusted
replacement-value label also requires verified league rules and contemporaneous
replacement pools; this production protocol does not pretend to supply them.

The [saved fixture report](benchmarks/stage06.json) carries input/protocol/code
hashes, coverage, skips, diagnostics and baseline retention. Its purpose is a
small reproducible audit artifact, not a persistent feature store or Stage 07
training/backtesting system. Runtime work scans a tiny selected weekly history;
no large training/storage cost or performance claim is introduced.

## Verification and stop gate

Tests verify sustained gain versus transient/noisy/flat/declining counts, future
correction and ingestion filtering, deterministic input order/hashes, missing
counts/gaps/zero baseline, complete and incomplete future label horizons,
positive/negative/excluded labels, independent game/availability minimums,
conflicting exposure and protocol validation, explicit source skips, unchanged
forecasts and offline/live CLI gates. Standard Python checks, existing Debug
C++/sanitizer/format checks and isolated native-wheel packaging also apply.

Stage 06 fixture/data-insufficiency acceptance is complete once those checks pass.
Actual Yahoo feature support, calibrated model improvement and decision uplift
remain blocked by missing authorized data. Stop at Stage 06 gate. Stage 07,
merge into main and external publication require new authorization.
