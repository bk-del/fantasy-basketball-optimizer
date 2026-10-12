# Fantasy Basketball Optimizer

**Status: planned.** Stage 00 provides a Python CLI and a C++20 build smoke target.
Yahoo integration, storage, forecasts, simulation and recommendations are not
implemented. See the [current handoff](fantasy-basketball-optimizer-guides/STATUS.md)
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

Python owns orchestration and the initial reference implementation. Storage and
Python/C++ bindings are planned for later stages. The present C++ target only
checks the toolchain; it is not a simulator.

## Local development: WSL2 Ubuntu and native Ubuntu

Use an Ubuntu shell, preferably with the checkout in the Linux filesystem on
WSL2. The baseline is Ubuntu 22.04 or 24.04, GCC 11 or newer, CMake 3.22 or newer,
Ninja, and LLVM 14 formatting/static analysis. Install system tools yourself if
missing; agents require approval before system-wide installation:

```bash
sudo apt-get update
sudo apt-get install --no-install-recommends g++ cmake ninja-build clang-format-14 clang-tidy-14
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

CMake runs clang-tidy on both C++ translation units and enables address/undefined
behavior sanitizers in Debug builds. CTest uses a plain executable, avoiding
third-party downloads. No pre-commit layer or Python runtime dependency is needed.
In this restricted agent environment, LeakSanitizer fails under process tracing.
`ASAN_OPTIONS=detect_leaks=0 ctest --test-dir build/cpp --output-on-failure` passed
with address and undefined-behavior instrumentation retained. Use the normal
CTest command on Ubuntu; full leak checking has not been verified here.

The first uv sync requires network access to install Python and download
development packages. `uv.lock` records the resolved versions; commit it and use
`uv sync --locked --group dev` to reproduce the environment. Checks then run
offline from the populated environment; CI has no Yahoo secrets or API calls.
CI has not yet been verified on GitHub. Ubuntu runner images/system package
patches may change; C++ dependencies do not require downloads.

If your home cache is read-only, set `UV_CACHE_DIR` to a writable directory and
`UV_PYTHON_INSTALL_DIR` to a writable managed-runtime directory before using uv.
No credentials are needed for Stage 00. `.env.example` lists reserved names only;
OAuth loading and fixture parsing are not yet implemented. Keep private data in
ignored `data/`, credentials in ignored local paths, and never commit tokens.

Pytest disables automatic third-party plugin discovery for this project. This
keeps a ROS-sourced shell from importing Python 3.10 ROS plugins into the pinned
Python 3.12 test environment. Any future test plugin must be declared as a
development dependency and enabled explicitly with `-p`.

## Implementation guides

Development follows `dev_<feature>` -> `dev` -> protected `main`. Agents work on
descriptive branches created from `dev`; reviewed pull requests with passing
checks integrate into `dev`. A separate promotion pull request reaches `main`
only after full verification and owner approval. Direct commits to `main` or
`dev`, force pushes to either, and bypassing protection are prohibited. See the
[branch and merge rules](fantasy-basketball-optimizer-guides/docs/DESIGN_RULES.md).
GitHub branch protection must be configured and verified separately.

The original guides stay in their own folder. Read
[AGENTS.md](fantasy-basketball-optimizer-guides/AGENTS.md),
[design rules](fantasy-basketball-optimizer-guides/docs/DESIGN_RULES.md),
[contracts](fantasy-basketball-optimizer-guides/docs/DATA_CONTRACTS.md) and
[validation](fantasy-basketball-optimizer-guides/docs/VALIDATION.md).

| Stage | Purpose |
|---|---|
| [00](fantasy-basketball-optimizer-guides/docs/stages/00-repository-foundation.md) | Repository foundation (current) |
| [01](fantasy-basketball-optimizer-guides/docs/stages/01-yahoo-api-audit.md) | Yahoo API audit |
| [02](fantasy-basketball-optimizer-guides/docs/stages/02-storage-and-ingestion.md) | Storage and ingestion |
| [03](fantasy-basketball-optimizer-guides/docs/stages/03-baseline-forecasting.md) | Baseline forecasting |
| [04](fantasy-basketball-optimizer-guides/docs/stages/04-matchup-simulator.md) | Matchup simulator |
| [05](fantasy-basketball-optimizer-guides/docs/stages/05-waiver-optimization.md) | Waiver optimization |
| [06](fantasy-basketball-optimizer-guides/docs/stages/06-context-and-breakouts.md) | Context and breakout signals |
| [07](fantasy-basketball-optimizer-guides/docs/stages/07-learning-and-backtesting.md) | Learning and backtesting |
| [08](fantasy-basketball-optimizer-guides/docs/stages/08-cli-and-operations.md) | CLI and operations |
| [09](fantasy-basketball-optimizer-guides/docs/stages/09-optional-extensions.md) | Optional extensions |

[Yahoo access request draft](docs/API_REQUEST.md). Publication requires owner
approval; application submission is manual by the owner. Stop at each stage gate.
