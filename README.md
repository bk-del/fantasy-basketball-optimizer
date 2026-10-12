# Fantasy Basketball Optimizer

**Status: fixture audit, storage, forecasts and matchup simulation implemented; live access unconfirmed.** Stage 00 provides
the Python/C++20 foundation. Stage 01 adds local authorization metadata, a
deterministic synthetic capability audit and a gated read-only live probe client.
Stage 02 adds DuckDB snapshots and offline incremental ingestion. Live OAuth
access is unverified. Stage 03 provides baseline weekly fixture forecasts;
Stage 04 adds correlated fixture matchup simulation. Recommendations are planned. See the [current handoff](fantasy-basketball-optimizer-guides/STATUS.md)
for verification results and blockers.

A personal, local tool planned for one initial user in a 14-team Yahoo H2H
9-category basketball league. The goal is to recommend ADD, DROP or HOLD based on
matchup probabilities and verified league constraints. It will be read-only: the
owner makes transactions manually. Recommendations will carry uncertainty and
offer no guarantees of results.

Yahoo Fantasy is the only planned runtime data source. API access is unconfirmed;
development uses local tests and, in later stages, clearly labeled handmade or
redacted fixtures. No commercial affiliation with Yahoo, business entity, paid
data service or paid inference is claimed.

## Planned architecture

```text
Yahoo (authorized read access only)
    -> Python ingestion -> local storage -> forecasts
    -> matchup simulation -> constrained recommendations -> CLI
                              ^
                    C++20 only for measured hotspots
```

Python owns orchestration and local DuckDB storage. The nanobind C++20 module aggregates joint
scenario batches; a Python reference verifies its arithmetic.

## Local development: WSL2 Ubuntu and native Ubuntu

Use an Ubuntu shell, preferably with the checkout in the Linux filesystem on
WSL2. The baseline is Ubuntu 22.04 or 24.04, GCC 11 or newer, CMake 3.22 or newer,
Ninja, and LLVM 14 formatting/static analysis. Install system tools yourself if
missing; agents require approval before system-wide installation:

```bash
sudo apt-get update
sudo apt-get install --no-install-recommends g++ cmake ninja-build clang-format-14 clang-tidy-14 catch2
```

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) version
0.12.18. Python 3.12.14 is pinned in `.python-version`, independent of Ubuntu's
system Python. Python 3.12 remains a supported security-maintenance branch;
this patch is available in the pinned uv download registry. The newer 3.12.15
is unavailable in that registry; review the runtime and uv pins together before
upgrading. This avoids modifying Ubuntu's system Python.

Run from this repository root:

```bash
uv sync --group dev
uv run fantasy --help
uv run fantasy status
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest -q
cmake -S cpp -B build/cpp -G Ninja -DCMAKE_BUILD_TYPE=Debug
cmake --build build/cpp
ctest --test-dir build/cpp --output-on-failure
git ls-files -z -- '*.cpp' '*.hpp' | xargs -0 -r clang-format-14 --dry-run --Werror
```

CMake runs clang-tidy on project C++ sources and enables address/undefined
behavior sanitizers in standalone Debug tests. Stage 04 uses Catch2 (2.13.8
verified locally) and explicitly tests the just-built module against Python.
NumPy 2.2.6 and nanobind 2.9.2 join DuckDB 1.4.5; scikit-build-core 0.11.6
builds the native wheel. Install C++ tools before the first uv sync.
In this restricted agent environment, LeakSanitizer fails under process tracing.
`ASAN_OPTIONS=detect_leaks=0 ctest --test-dir build/cpp --output-on-failure` passed
with address and undefined-behavior instrumentation retained. Use the normal
CTest command on Ubuntu; Stage 04 full leak checking also passed outside the restricted sandbox.

The first uv sync requires network access to install Python and download
development packages. `uv.lock` records the resolved versions; commit it and use
`uv sync --locked --group dev` to reproduce the environment. Checks then run
offline from the populated environment; CI has no Yahoo secrets or API calls.
CI has not yet been verified on GitHub. Ubuntu runner images/system package
patches may change; the pinned binding/build dependencies require an initial download.

If your home cache is read-only, set `UV_CACHE_DIR` to a writable directory and
`UV_PYTHON_INSTALL_DIR` to a writable managed-runtime directory before using uv.
No credentials are needed for Stage 00. `.env.example` lists reserved names only;
Stage 01 reads private token files only for local metadata or approved live probes.
Keep private data in
ignored `data/`, credentials in ignored local paths, and never commit tokens.

Pytest disables automatic third-party plugin discovery for this project. This
keeps a ROS-sourced shell from importing Python 3.10 ROS plugins into the pinned
Python 3.12 test environment. Any future test plugin must be declared as a
development dependency and enabled explicitly with `-p`.

## Yahoo capability audit (Stage 01)

```bash
uv run fantasy auth status
uv run fantasy audit --fixture
```

Fixture mode is offline and labels all evidence as synthetic. Live `fantasy audit`
refuses undeclared approval, missing/unsafe/expired credentials and denied access.
It performs only bounded GET requests; it never adds/drops players. OAuth login
and automatic refresh remain owner-run pending approved access. See
[capabilities and auth setup](docs/YAHOO_CAPABILITIES.md) for resource coverage,
freshness limits, official references and the point-in-time missing-data policy.

## Fixture storage and ingestion (Stage 02)

```bash
uv run fantasy sync --fixture
uv run fantasy sync --fixture
uv run fantasy sync --fixture --scenario changed
```

These commands use ignored `data/fixture.duckdb`. The first run creates seven
snapshots, the second creates none, and the changed scenario creates three.
Use `--database PATH` for a fresh scenario replay. Replaying baseline after the
changed scenario is rejected as an older observation; it cannot revert state.
Every output reports schema version, changed rows, fetch failures, actual database
size and elapsed time. Live `fantasy sync` is disabled pending verified samples.

Fixture observation dates are synthetic; ingestion records the actual local UTC
time. Historical queries require **both** timestamps to precede the decision.
Roster membership and availability collections are stored when changed, including
explicit empty rosters. Availability and player status fixtures exercise proposed
contracts and do not demonstrate Yahoo support. Missing players in a partial
collection never imply deletion or availability. Statistical windows remain
aggregates, without inferred NBA games, dates or unverified scoring categories.
See [storage schema and recovery](docs/STORAGE.md) for transaction and as-of rules.

## Baseline weekly forecasts (Stage 03)

```bash
uv run fantasy forecast --fixture
uv run fantasy forecast --fixture --benchmark
uv run fantasy forecast --fixture --model shrinkage
```

The forecast uses 48 handmade weekly vectors for four fictional players, separate
from the earlier storage fixture's season aggregate. It forecasts the next seven
days at weekly granularity; it does not reconstruct NBA games or assume a game
schedule. Live forecasts are disabled pending verified comparable stat windows.

The provisional default is recency weighting. `--model long_run` and `--model
shrinkage` expose the comparison baselines. Output includes expected raw counts,
joint integer samples, empirical intervals, missingness, Monte Carlo mean error,
feature provenance and model/config hashes. Unknown game count, minutes and
availability probability stay null. Percentages must be computed from raw makes
and attempts by a later consumer; no independent percentage averaging is used.

Versioned, content-addressed artifacts are written under ignored
`models/weekly-counts-v1/`; override with `--output DIRECTORY`. Fixed `--seed 42`
and `--samples 256` reproduce the same report and artifact. See
[forecast contract and measured benchmarks](docs/FORECASTING.md). These toy
benchmarks do not demonstrate real-world calibration or recommendation quality.

## Implementation guides

The original guides stay in their own folder. Read
[AGENTS.md](fantasy-basketball-optimizer-guides/AGENTS.md),
[design rules](fantasy-basketball-optimizer-guides/docs/DESIGN_RULES.md),
[contracts](fantasy-basketball-optimizer-guides/docs/DATA_CONTRACTS.md) and
[validation](fantasy-basketball-optimizer-guides/docs/VALIDATION.md).

| Stage | Purpose |
|---|---|
| [00](fantasy-basketball-optimizer-guides/docs/stages/00-repository-foundation.md) | Repository foundation |
| [01](fantasy-basketball-optimizer-guides/docs/stages/01-yahoo-api-audit.md) | Yahoo API audit |
| [02](fantasy-basketball-optimizer-guides/docs/stages/02-storage-and-ingestion.md) | Storage and ingestion |
| [03](fantasy-basketball-optimizer-guides/docs/stages/03-baseline-forecasting.md) | Baseline forecasting (current, fixture-only) |
| [04](fantasy-basketball-optimizer-guides/docs/stages/04-matchup-simulator.md) | Matchup simulator |
| [05](fantasy-basketball-optimizer-guides/docs/stages/05-waiver-optimization.md) | Waiver optimization |
| [06](fantasy-basketball-optimizer-guides/docs/stages/06-context-and-breakouts.md) | Context and breakout signals |
| [07](fantasy-basketball-optimizer-guides/docs/stages/07-learning-and-backtesting.md) | Learning and backtesting |
| [08](fantasy-basketball-optimizer-guides/docs/stages/08-cli-and-operations.md) | CLI and operations |
| [09](fantasy-basketball-optimizer-guides/docs/stages/09-optional-extensions.md) | Optional extensions |

[Yahoo access request draft](docs/API_REQUEST.md). Publication requires owner
approval; application submission is manual by the owner. Stop at each stage gate.

## Fixture matchup simulation (Stage 04)

```bash
uv run fantasy simulate --fixture --seed 42 --scenarios 1000
uv run fantasy simulate --fixture --backend python
uv run fantasy simulate --fixture --benchmark > /tmp/matchup-benchmark.json
```

Uses 40 handmade player-game forecasts and explicit synthetic rules, separate
from Stage 03 weekly aggregates. Live simulation is disabled. Reusable seeded
joint count scenarios preserve category dependence; weighted percentages,
turnovers, ties and observed totals use Python/native parity checks. See
[simulation contracts, limitations and saved timings](docs/SIMULATION.md).
