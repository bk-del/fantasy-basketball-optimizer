# Stage 09 proposal: local fixture dashboard

The owner requested a usable interface. This extension provides a local browser
interface to the working fixture CLI pipeline and category tradeoff display.

Data: existing handmade operations fixtures only. No Yahoo connection, new model,
transaction submission, notification or scheduler. The dashboard runs the existing
pipeline in temporary dry-run storage with the provisional recency model, seed 42
by default and the existing 256/4096 scenario budgets. Weekly forecasts and game
samples remain separate sources. It never opens the owner's database or registry.

Cost: Python standard-library HTTP server, packaged HTML/CSS and server-rendered
forms; no browser build, JavaScript runtime or new dependency. At most eight
in-memory reports, evicted in insertion order. No durable dashboard data. Only
127.0.0.1 is served, with local Host checks, bounded inputs and fixed routes.

Success: scenario/seed analysis, action selection, category effects and frontier
axes, active lineups, rejection reasons, uncertainty and JSON export work through
real HTTP requests. Outputs exactly preserve the existing pipeline recommendation
and estimates. Fresh baseline page under 3 seconds and five-run median cached
page under 0.1 seconds on this host; measure response bytes and cache bound.
Reject/revise if parity, required checks or these budgets fail. User review remains
required; display usability is not measured live decision uplift.

Rollback: stop the server with Ctrl+C; use the existing CLI unchanged. Revert the
focused dashboard commit if needed. No model/database migration or publication.

## Launch

```bash
uv run fantasy dashboard --fixture
```

Open **http://127.0.0.1:8765** in your browser. Keep the terminal running; Ctrl+C
stops it and clears the in-memory reports. On WSL, use the same URL in the Windows
browser (localhost forwarding must be enabled). If the port is busy, use
`--port 8766`. Binding to a public address is deliberately unavailable.

Choose a fixture scenario and seed, then Analyze scenario. Select an action to
inspect its win chance, category win/tie changes, roster and lineup. Choose axes
and Apply categories to change the category frontier display only. Download JSON
exports the exact run report; nothing is submitted to Yahoo. Repeated analysis of
the same scenario/seed reuses its session report; restart to clear the cache.

Partial ingestion displays an error and recovery controls, without an old
recommendation. Unknown acquisition rules display HOLD with the missing-constraint
reasons; probabilities remain unavailable when a lineup cannot be verified.
Screened estimates are explicitly marked and
excluded from frontier comparisons. Monte Carlo SE measures sampling precision;
model uncertainty remains uncalibrated. All names/times are synthetic.

The interface uses native forms/links and works without JavaScript. The server
supports one local user and handles requests sequentially. It is a development
fixture tool, not a hosted or live production dashboard.

## Observed verification

Real HTTP navigation, category filtering, exports, failure recovery and pipeline
parity passed, including an extracted-wheel test of packaged HTML/CSS and native
simulation. Fresh baseline page: 0.800 seconds; cached median over five requests:
0.00353 seconds. Both meet the proposal budgets. HTML response: 12,655 bytes;
JSON: 21,230 bytes. Startup excluded; single-user local measurements only.
See [saved measurements](benchmarks/stage09-dashboard.json). Browser automation
was unavailable, so visual review in your browser remains pending.
