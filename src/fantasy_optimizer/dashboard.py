"""Local browser interface over the existing fixture-only dry-run pipeline."""

import json
import tempfile
from collections.abc import Mapping
from html import escape
from http.server import BaseHTTPRequestHandler, HTTPServer
from importlib.resources import files
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit

import duckdb

from fantasy_optimizer.operations import SCENARIOS, OperationError, run_fixture
from fantasy_optimizer.registry import Registry, RegistryError
from fantasy_optimizer.simulation import CATEGORIES
from fantasy_optimizer.tradeoffs import tradeoff_view

LABELS = {
    "baseline": "Baseline matchup",
    "new_stats": "Updated weekly stats",
    "transaction": "Acquisition limit reached",
    "unknown_settings": "Missing league rules",
    "partial_ingestion": "Incomplete data refresh",
}
MAX_REPORTS = 8


def h(value: object) -> str:
    return escape(str(value), quote=True)


def percent(value: Any) -> str:
    return "Unavailable" if value is None else f"{value * 100:.2f}%"


def action_name(value: str) -> str:
    if value == "HOLD":
        return "Keep current roster"
    return value.replace("ADD:", "Add ").replace("/DROP:", " · Drop ")


class Dashboard:
    def __init__(self) -> None:
        self.reports: dict[tuple[str, int], dict[str, Any]] = {}

    def report(self, scenario: str, seed: int) -> dict[str, Any]:
        key = (scenario, seed)
        if key not in self.reports:
            # Dry-run creates and cleans its own temporary database/output. This
            # nonexistent registry selects the provisional fixture baseline only.
            with tempfile.TemporaryDirectory(prefix="fantasy-dashboard-") as scratch:
                result = run_fixture(
                    Path(scratch) / "unused.duckdb",
                    Path(scratch) / "unused-runs",
                    Registry(Path(scratch) / "registry.json"),
                    scenario=scenario,
                    seed=seed,
                    dry_run=True,
                )
            if len(self.reports) >= MAX_REPORTS:
                del self.reports[next(iter(self.reports))]
            self.reports[key] = result
        return self.reports[key]


def controls(scenario: str, seed: int) -> str:
    options = "".join(
        f'<option value="{h(key)}" {"selected" if key == scenario else ""}>'
        f"{h(LABELS[key])}</option>"
        for key in SCENARIOS
    )
    return (
        '<form class="controls" action="/" method="get">'
        f'<label>Fixture scenario<select name="scenario">{options}</select></label>'
        '<label>Simulation seed<input name="seed" type="number" min="0" '
        f'max="4294967295" value="{seed}" required></label>'
        '<button type="submit">Analyze scenario <span aria-hidden="true">↗</span>'
        "</button></form>"
    )


def shell(content: str, scenario: str, seed: int) -> str:
    template = files("fantasy_optimizer").joinpath("web/index.html").read_text()
    return template.replace("{{CONTROLS}}", controls(scenario, seed)).replace(
        "{{CONTENT}}", content
    )


def render(
    report: Mapping[str, Any], categories: tuple[str, ...], action: str | None
) -> str:
    decision = report["optimization"]
    rows = decision["ranked_actions"]
    recommendation = decision["recommended_action"]
    selected = next((row for row in rows if row["action"] == action), None)
    if action is not None and selected is None:
        raise ValueError("Choose an action from this scenario's results.")
    selected = selected or next(
        (row for row in rows if row["action"] == recommendation), None
    )
    view = tradeoff_view(report, categories)
    query: list[tuple[str, str]] = [
        ("scenario", report["scenario"]),
        ("seed", str(report["seed"])),
    ]
    axes = [("category", category) for category in categories]
    download = "/report.json?" + urlencode(query)
    before = selected["win_probability_before"] if selected else None
    after = selected["win_probability_after"] if selected else None
    uncertainty = selected["win_probability_mc_se"] if selected else None
    gain = selected["matchup_credit_gain"] if selected else None
    paired_se = selected["paired_gain_mc_se"] if selected else None
    gain_label = "Unavailable" if gain is None else f"{gain * 100:+.2f} pp"
    body = (
        '<section class="result-heading"><div><p class="eyebrow">MATCHUP ANALYSIS</p>'
        f"<h2>{h(action_name(recommendation))}</h2>"
        "<p>Suggested move for this handmade fixture. You make every transaction.</p>"
        f'</div><a class="secondary" href="{h(download)}" download="fixture-run.json">'
        "Download JSON ↓</a></section>"
        '<div class="metrics">'
        f"<article><p>Current roster win chance</p><strong>{percent(before)}</strong>"
        "<small>HOLD baseline</small></article>"
        f"<article><p>Selected action win chance</p><strong>{percent(after)}</strong>"
        f"<small>Monte Carlo SE: {percent(uncertainty)}</small></article>"
        f"<article><p>Matchup credit change</p><strong>{gain_label}</strong>"
        f"<small>Paired SE: {percent(paired_se)}"
        "</small></article></div>"
        '<p class="notice">Synthetic fixture • probabilities are uncalibrated. '
        "Sampling error does not include model uncertainty.</p>"
        '<div class="analysis-grid"><section class="panel"><div class="panel-heading">'
        '<div><p class="eyebrow">YOUR OPTIONS</p><h3>Compare actions</h3></div>'
        f'<span class="pill">{len(rows)} evaluated</span></div>'
    )
    if not rows:
        body += '<p class="empty">No verified action estimates. HOLD retained.</p>'
    for row in rows:
        chosen = selected is not None and row["action"] == selected["action"]
        link = "/?" + urlencode([*query, *axes, ("action", row["action"])])
        badge = "Recommended" if row["action"] == recommendation else "Alternative"
        quality = "Refined" if row["refined"] else "Screening only"
        body += (
            f'<a class="action {"selected" if chosen else ""}" href="{h(link)}" '
            f"{'aria-current="true"' if chosen else ''}>"
            f'<span class="action-top"><b>{h(action_name(row["action"]))}</b>'
            f"<span>{percent(row['win_probability_after'])}</span></span>"
            f'<span class="action-meta">{badge} · {quality} · '
            f"{row['samples']:,} samples"
            "</span></a>"
        )
    body += '</section><section class="panel"><div class="panel-heading"><div>'
    body += '<p class="eyebrow">SELECTED ACTION</p><h3>Category impact</h3></div></div>'
    if selected:
        body += f"<p>{h(selected['explanation'])}</p>"
        if not selected["refined"]:
            body += (
                '<p class="notice">Screening estimate only; excluded from Pareto '
                "comparisons and recommendations.</p>"
            )
        body += (
            '<p class="subtle">Change in chance of winning each category versus HOLD. '
            "Positive TO means a better chance with fewer turnovers.</p>"
            '<div class="table-scroll"><table><caption class="sr-only">'
            "Category win and tie probability changes</caption><thead><tr>"
            '<th scope="col">Category</th><th scope="col">Win change</th>'
            '<th scope="col">Tie change</th></tr></thead><tbody>'
        )
        for category in CATEGORIES:
            delta = selected["category_win_deltas"][category]
            tie = selected["category_tie_deltas"][category]
            width = min(abs(delta) * 100, 100)
            body += (
                f'<tr><th scope="row">{h(category)}</th><td class="delta '
                f'{"positive" if delta >= 0 else "negative"}">'
                f"<span>{delta * 100:+.2f} pp</span>"
                f'<i aria-hidden="true" style="width:{width:.2f}%"></i></td>'
                f"<td>{tie * 100:+.2f} pp</td></tr>"
            )
        body += "</tbody></table></div>"
    else:
        body += (
            '<p class="empty">Category probabilities unavailable '
            "with missing rules.</p>"
        )
    body += '</section></div><section class="panel"><div class="panel-heading"><div>'
    body += '<p class="eyebrow">TRADEOFFS</p><h3>Pareto comparison</h3></div></div>'
    body += (
        '<p class="subtle">An action is on a frontier when none is better on every '
        "chosen axis. Point estimates only; frontier membership "
        "is not a recommendation."
        " Category selection changes this display only.</p>"
        '<form action="/" method="get"><fieldset>'
        "<legend>Category frontier axes</legend>"
    )
    for key, value in query + ([("action", selected["action"])] if selected else []):
        body += f'<input type="hidden" name="{h(key)}" value="{h(value)}">'
    for category in CATEGORIES:
        body += (
            f'<label class="check"><input type="checkbox" name="category" '
            f'value="{h(category)}" {"checked" if category in categories else ""}>'
            f"{h(category)}</label>"
        )
    body += (
        '</fieldset><button class="secondary" type="submit">Apply categories</button>'
        '<input type="hidden" name="axes" value="selected">'
        '</form><div class="frontiers">'
    )
    for label, key in (
        ("Matchup credit & roster cost", "utility_frontier"),
        ("Selected categories & roster cost", "category_frontier"),
    ):
        names = (
            ", ".join(action_name(name) for name in view[key])
            or "No comparable estimates"
        )
        body += f"<div><p>{h(label)}</p><b>{h(names)}</b></div>"
    body += '</div><div class="table-scroll"><table><caption class="sr-only">'
    body += "Comparable actions and roster cost</caption><thead><tr><th>Action</th>"
    body += (
        "<th>Value loss</th><th>Credit frontier</th>"
        "<th>Category frontier</th></tr></thead><tbody>"
    )
    for row in view["actions"]:
        body += (
            f'<tr><th scope="row">{h(action_name(row["action"]))}</th>'
            f"<td>{row['long_term_value_loss']:g}</td>"
            f"<td>{'Yes' if row['action'] in view['utility_frontier'] else 'No'}</td>"
            f"<td>{'Yes' if row['action'] in view['category_frontier'] else 'No'}</td>"
            "</tr>"
        )
    body += (
        '</tbody></table></div><p class="subtle">'
        "Value loss is an ordinal fixture proxy.</p>"
    )
    body += '</section><section class="panel"><h3>Roster & active lineup</h3>'
    if selected:
        body += f"<p>After this action: {h(', '.join(selected['roster_after']))}</p>"
        body += "<details><summary>Show scheduled player-game selections</summary>"
        body += '<ul class="lineup">'
        for slot in selected["active_lineup"]:
            body += (
                f"<li><b>{h(slot['slot'])}</b> {h(slot['game_key'])} "
                f'<span class="subtle">Team {h(slot["team"])}</span></li>'
            )
        body += "</ul></details>"
    else:
        body += (
            '<p class="empty">Lineup cannot be verified with current fixture rules.</p>'
        )
    body += (
        '</section><section class="panel"><h3>Constraints & excluded actions</h3><ul>'
    )
    for row in decision["filtered_actions"]:
        body += (
            f"<li><b>{h(action_name(row['action']))}</b> · {h(row['feasibility'])}: "
            f"{h('; '.join(row['reasons']))}</li>"
        )
    for row in view["excluded"]:
        body += f"<li>{h(action_name(row['action']))}: {h(row['reason'])}</li>"
    body += '</ul></section><section class="panel"><h3>Data & uncertainty</h3><ul>'
    for message in [*report["limitations"], *decision["diagnostics"]]:
        body += f"<li>{h(message)}</li>"
    body += (
        "</ul><details><summary>Weekly forecasts & reproducibility</summary>"
        f"<p>As of {h(report['as_of'])} · Seed {report['seed']} · "
        f"Weekly baseline: {h(report['weekly']['active_baseline'])}</p>"
        f"<p>Synthetic observation time: {h(report['freshness']['snapshot_at'])}</p>"
        "<p>Weekly expected counts are independent of the handmade game samples.</p>"
        '<div class="table-scroll"><table><caption>Weekly expected counts</caption>'
        "<thead><tr><th>Fixture player</th><th>PTS</th><th>REB</th><th>AST</th>"
        "<th>3PM</th></tr></thead><tbody>"
    )
    for prediction in report["weekly"]["forecasts"]:
        body += f'<tr><th scope="row">{h(prediction["player_key"])}</th>'
        for stat in ("PTS", "REB", "AST", "3PM"):
            value = prediction["expected_counts"][stat]
            body += f"<td>{'Unavailable' if value is None else f'{value:.1f}'}</td>"
        body += "</tr>"
    body += (
        "</tbody></table></div>"
        f'<p class="hash">Run ID: {h(report["run_id"])}</p></details></section>'
    )
    return shell(body, report["scenario"], report["seed"])


def parameters(query: str) -> tuple[str, int, tuple[str, ...], str | None]:
    args = parse_qs(query, keep_blank_values=True, max_num_fields=16)
    if set(args) - {"scenario", "seed", "category", "action", "axes"}:
        raise ValueError("Unsupported dashboard option.")
    for key in ("scenario", "seed", "action"):
        if len(args.get(key, [])) > 1:
            raise ValueError("Choose one scenario, seed and action.")
    scenario = args.get("scenario", ["baseline"])[0]
    if scenario not in SCENARIOS:
        raise ValueError("Choose a supported fixture scenario.")
    seed = int(args.get("seed", ["42"])[0])
    if not 0 <= seed <= 2**32 - 1:
        raise ValueError("Seed must be between 0 and 4294967295.")
    categories = tuple(args.get("category", () if "axes" in args else CATEGORIES))
    if not categories or len(set(categories)) != len(categories):
        raise ValueError("Choose at least one unique category.")
    if any(category not in CATEGORIES for category in categories):
        raise ValueError("Choose supported category axes.")
    return scenario, seed, categories, args.get("action", [None])[0]


def make_server(port: int = 8765) -> HTTPServer:
    dashboard = Dashboard()

    class Handler(BaseHTTPRequestHandler):
        server: HTTPServer

        def setup(self) -> None:
            super().setup()
            self.connection.settimeout(10)

        def log_message(self, format: str, *args: Any) -> None:
            pass  # URLs may contain user-entered values; avoid logging them.

        def send(self, status: int, content: bytes, mime: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'none'; style-src 'self' 'unsafe-inline'; "
                "form-action 'self'; frame-ancestors 'none'; base-uri 'none'",
            )
            if mime == "application/json":
                self.send_header(
                    "Content-Disposition", 'attachment; filename="fixture-run.json"'
                )
            self.end_headers()
            self.wfile.write(content)

        def do_GET(self) -> None:
            host = self.headers.get("Host", "")
            allowed = {
                f"127.0.0.1:{self.server.server_port}",
                f"localhost:{self.server.server_port}",
            }
            if host not in allowed:
                self.send(403, b"Open the local dashboard URL.", "text/plain")
                return
            if len(self.path) > 2048:
                self.send(414, b"Dashboard URL too long.", "text/plain")
                return
            url = urlsplit(self.path)
            if url.path == "/style.css":
                css = files("fantasy_optimizer").joinpath("web/style.css").read_bytes()
                self.send(200, css, "text/css; charset=utf-8")
                return
            if url.path not in ("/", "/report.json"):
                self.send(404, b"Page not found.", "text/plain")
                return
            scenario, seed = "baseline", 42
            try:
                scenario, seed, categories, action = parameters(url.query)
                report = dashboard.report(scenario, seed)
                if url.path == "/report.json":
                    self.send(
                        200,
                        json.dumps(report, sort_keys=True, allow_nan=False).encode(),
                        "application/json",
                    )
                    return
                self.send(
                    200,
                    render(report, categories, action).encode(),
                    "text/html; charset=utf-8",
                )
            except (ValueError, OperationError, RegistryError, duckdb.Error, OSError):
                page = shell(
                    '<section class="panel error" role="alert">'
                    "<h2>Analysis unavailable</h2>"
                    "<p>Check your scenario, seed and category selection. "
                    "Incomplete data "
                    "refreshes cannot produce recommendations. Choose Baseline matchup "
                    'to recover.</p><a href="/">Reset to baseline →</a></section>',
                    scenario,
                    seed,
                )
                self.send(400, page.encode(), "text/html; charset=utf-8")

    return HTTPServer(("127.0.0.1", port), Handler)


def serve(port: int = 8765) -> None:
    with make_server(port) as server:
        print(f"Fixture dashboard: http://127.0.0.1:{server.server_port}", flush=True)
        print("Keep this terminal open. Press Ctrl+C to stop.", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
