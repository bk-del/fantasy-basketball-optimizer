# AGENTS.md — mandatory instructions for all coding agents

Read this file and `STATUS.md` **before** exploring the repository. Then read **only** the current stage linked in `STATUS.md` plus any referenced design/contracts document. Do not scan the whole codebase unless a specific blocker requires it.

## Operating contract

1. Work on **one stage at a time**. Do not jump ahead, silently expand scope, add frameworks, or implement optional features.
2. Before editing, record a brief execution plan in `STATUS.md` (scope, tasks, expected commands). After meaningful milestones and at the end of each session, update `STATUS.md` with observed results and the exact next step. No fabricated success.
3. Every stage has acceptance criteria and a **STOP / approval gate**. Finish its criteria, run checks, update handoff notes, then stop. If blocked (e.g. Yahoo approval), make a fixture-only path and document the block; never fake API responses as production data.
4. Minimize context use: inspect narrow relevant files and commands; use `git status --short`, targeted tests, and the stage's declared file list. Do not repeatedly re-read all historical docs.
5. Prefer small, reviewable changes and commits. Ask before creating/publishing a remote repository, changing access visibility, modifying existing user files, spending money, deploying, or installing system-wide dependencies.
6. No paid APIs, LLM runtime dependency, automated waiver submission, or unapproved external data. Secrets never enter Git, logs, tests, or Markdown.
7. Build a **deterministic decision pipeline**: pin versions, seed simulations, record inputs/model/config hashes, use explicit timezones and as-of timestamps.
8. Do not assert an API field or historical data exists until it has been checked against Yahoo docs and an authorized sample. Maintain an explicit missing-data/fallback policy.
9. Use pragmatic testing: test contracts, arithmetic, no-leakage, reproducibility, constraints, and representative failure paths. Avoid excessive trivial mocks or performance guesses.
10. Every feature must demonstrate user value and justify its computational/storage cost. No RL, GPUs, distributed systems, microservices, or elaborate plugin frameworks without a measured need and approval.
11. Before editing, create or switch to a descriptive `dev_<feature>` branch based on current `dev` (for example, `dev_branch-workflow`). Agents commit only on these work branches. Open pull requests into `dev`, never directly into `main`. Merge into `dev` only after review and required checks pass for the proposed result. Promote `dev` to protected `main` through a separate pull request only after the full checks pass for the proposed result and the owner approves the promotion. Never commit directly to `main` or `dev`, force-push either, or bypass branch protection. If `dev` is missing, create it from the reviewed `main` baseline before creating a work branch. If branch creation is blocked, use an isolated checkout and provide a patch; do not edit the protected checkout as a workaround. See `docs/DESIGN_RULES.md` for the merge gates.

## Required engineering checks

When configured (Stage 00), run from repository root:

```bash
uv sync --group dev
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest -q
cmake -S cpp -B build/cpp -G Ninja -DCMAKE_BUILD_TYPE=Debug
cmake --build build/cpp
ctest --test-dir build/cpp --output-on-failure
```

The C++ checks apply once a C++ target exists. Do not treat missing tools/credentials as passing tests. C++ formatting: `clang-format --dry-run --Werror` on **tracked C++ files** (not build trees); enable `clang-tidy` on changed C++ code when the target exists. Pin tool versions where practical. Fix failures rather than suppressing diagnostics without justification.

## Completion report (mandatory)

In `STATUS.md`, record: completed work; changed files; commands run and results; tests skipped and why; blockers; new decisions; next exact action; stage acceptance status. Keep the top-level summary short and current. Keep detailed completed work in the log at bottom. This file is the primary agent-to-agent handoff.

For architectural principles see `docs/DESIGN_RULES.md`; for schema see `docs/DATA_CONTRACTS.md`; for tests see `docs/VALIDATION.md`.
