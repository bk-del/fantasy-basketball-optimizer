# Stage 04 — Correlated 9-CAT matchup simulation

**Goal:** correct, reproducible matchup win probabilities with a trusted Python reference and performance-oriented C++20 implementation.

## Implement

- Define simulation API receiving roster, schedule/eligibility constraints, player-game joint forecasts and observed matchup-to-date totals. Simulate only remaining games for in-progress matchups.
- Correctly aggregate raw category counts; FG% = ΣFGM/ΣFGA and FT% = ΣFTM/ΣFTA; fewer turnovers is better; support ties and the league's actual scoring/tie rules.
- Preserve dependencies among category outcomes. Use joint player-game samples/bootstrap with appropriate limitations; never independently sample category-win flags.
- Build small explicit Python reference, then port measured compute hotspots to a C++20 shared library with nanobind. Avoid Python calls inside per-scenario loops; pass contiguous arrays in batches.
- Reuse sampled scenarios across actions (common random numbers). Report Monte Carlo standard error; distinguish sampling precision from forecast calibration.
- Benchmark 1k, 10k and 20k scenarios on representative fixture; optimize only after measuring. GPU is out of scope.

## Acceptance criteria

- Hand-calculated examples pass for FG/FT weighting, TO inversion, ties, partial games and at-least-five win scoring.
- Fixed-seed C++ runs reproduce; Python/C++ parity passes for deterministic small fixtures (distributional parity for stochastic tests when RNG implementations differ).
- No false runtime speedup claims; save benchmarks and regression tests.
- Update `STATUS.md`.
