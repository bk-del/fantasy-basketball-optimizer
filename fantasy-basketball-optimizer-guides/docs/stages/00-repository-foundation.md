# Stage 00 — Repository foundation and GitHub readiness

**Goal:** produce a professional, small, reproducible repository with a public-facing README suitable for Yahoo's API access application. **Do not build Yahoo integration or models yet.**

## Agent setup

1. Read `AGENTS.md`, `STATUS.md`, `docs/DESIGN_RULES.md`.
2. Check environment with targeted commands (`pwd`, `git status --short`, `python --version`, `uv --version`, `cmake --version`, `ninja --version`, `clang-format --version`, `clang-tidy --version`, `gh auth status` when installed). Record missing tools; do not install system software or authenticate without permission.
3. Update the current execution plan in `STATUS.md`.
4. Follow `docs/DESIGN_RULES.md` branch rules: work on `dev_<feature>` created from `dev`, integrate through a reviewed/check-passing pull request into `dev`, and promote to protected `main` only after full verification and owner approval. If the repository has no commits, the owner establishes its initial baseline first; never silently use `main` for agent development.

## Implement

- Set project/repo name (suggest `fantasy-basketball-optimizer`; ask owner before final choice). Keep a concise, accurate public README: scope, architecture diagram in Markdown, status **planned**, Yahoo-only data source, no commercial affiliation, read-only use, one initial user, no guarantees, how to develop with fixtures. Do not claim an approved API key or that features are implemented.
- Create Python `src/fantasy_optimizer` package (`__init__.py`, minimal Typer or argparse CLI with `--help` and `status`; prefer stdlib argparse until complexity justifies Typer). Initialize a `pyproject.toml`, uv dependency resolution/lockfile and Python runtime version supported by WSL Ubuntu. Choose a currently supported version; pin it and explain any tradeoff.
- Add tiny placeholder C++20 CMake project under `cpp/` with a compiled library/test target **only if** it is lightweight to configure. Use a single established test framework (GoogleTest or Catch2) if available/reproducibly obtainable. Do not block Stage 00 on downloading third-party code; a plain CTest executable is sufficient.
- Repo tooling: `.gitignore` for `.env`, `data/`, `models/`, `.venv/`, `build/`, caches, OAuth credentials, local DB and profiler outputs; `.env.example` containing **names only**, not values. Add `.editorconfig`, Ruff, mypy, pytest config, `.clang-format`, CMake warnings and test configuration. Add pre-commit only if it meaningfully simplifies checks.
- Add `tests/test_smoke.py` for the CLI and an optional simple C++ smoke test. Add GitHub Actions CI running offline Python checks plus C++ smoke checks (pin supported versions; Linux runner). GitHub CI must not require Yahoo API secrets.
- Preserve these instruction documents and link stages from README. Keep a `docs/API_REQUEST.md` with truthful, short language for Yahoo's application and the repository URL placeholder; avoid stating a business exists.
- Run configured lint, format, typecheck, Python tests, CMake build and CTest. Fix actual errors. Do not create fake passing logs or giant scaffolding.
- Initialize Git if not already initialized; commit on `dev_<feature>` if owner has authorized commits. Establish `dev` from the reviewed baseline if needed. **Ask explicit approval before `gh repo create` / GitHub publication, public visibility or `git push`, unless that action is already authorized in this session.** An initial public README can be reviewed before publication. Require GitHub protection on `main` before any promotion; verify rather than assume it is enabled.

## Acceptance criteria

- Clean repository structure and documented local setup for WSL2 and Ubuntu.
- A new developer can `uv sync --group dev` and run help/smoke tests; C++ targets build or the absent toolchain is explicitly documented as a blocker.
- CI configuration exists and covers only local/fixture tests.
- Secrets are ignored; `git status` does not show private files.
- Public-facing description is honest and suitable to link in a Yahoo access request.
- `STATUS.md` contains completed artifacts, exact check results, blockers and next stage (01).

## STOP / approval gate

Stop after local scaffolding and validation. Do not publish remotely without owner confirmation. Yahoo application submission is manual by owner.
