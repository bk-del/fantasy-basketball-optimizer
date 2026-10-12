# Stage 08 — End-to-end manual CLI and scheduling-ready operations

**Goal:** a robust manual, local workflow that can later run via systemd timer/cron unchanged.

## Implement

- Finish coherent CLI: `fantasy run`, `sync`, `forecast`, `optimize`, `train`, `backtest`, `status`; `--fixture` for offline validation; `--as-of` where historically meaningful.
- `fantasy run`: sync -> validate -> change detection -> update aggregates/features -> infer using active model -> simulate and optimize -> save results -> console output. Do not retrain. Idempotent and single-instance locked.
- Cache by input watermark, code/feature/model/config versions and RNG seed. Skip unnecessary recomputation; test invalidation when a league transaction or new stats arrive.
- Show data freshness, league rules not yet verified, model version, category effects and probability uncertainty. Fail safely on revoked auth or partial ingestion.
- Add structured redacted logging, `--dry-run` where appropriate, reasonable retries/backoff and user-facing failure messages. No background service in baseline implementation.
- Document manual WSL2 usage, how to migrate to native Ubuntu (recreate `.venv`, copy DB/model/secrets separately), and *optional* sample systemd timer/cron with explicit prerequisites; don't enable scheduling automatically.

## Acceptance criteria

- End-to-end `fantasy run --fixture` passes on fresh checkout with realistic representative league fixtures; live run only if user has valid credentials.
- Two identical runs reuse cache where appropriate and produce identical recommendations/seeds.
- CI and relevant targeted tests pass. Status includes next operational steps and any unresolved API limitations.
- Update `STATUS.md`; request owner validation of actual outputs before describing as production-ready.
