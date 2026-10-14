"""Exercise browser-native navigation and fixture pipeline parity over real HTTP."""

import copy
import json
import threading
from collections.abc import Callable, Iterator
from html.parser import HTMLParser
from http.client import HTTPConnection
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import pytest

from fantasy_optimizer import dashboard
from fantasy_optimizer.cli import main
from fantasy_optimizer.operations import OperationError, run_fixture
from fantasy_optimizer.registry import Registry
from fantasy_optimizer.simulation import CATEGORIES

Request = Callable[..., tuple[int, dict[str, str], bytes]]


class Page(HTMLParser):
    def __init__(self, html: str) -> None:
        super().__init__()
        self.links: list[str] = []
        self.inputs: list[dict[str, str | None]] = []
        self.forms: list[dict[str, str | None]] = []
        self.feed(html)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        fields = dict(attrs)
        if tag == "a" and fields.get("href"):
            self.links.append(str(fields["href"]))
        if tag in ("input", "select", "button"):
            self.inputs.append(fields)
        if tag == "form":
            self.forms.append(fields)


@pytest.fixture
def http(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Request]:
    monkeypatch.chdir(tmp_path)
    with dashboard.make_server(0) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        def request(
            path: str = "/", *, host: str | None = None, method: str = "GET"
        ) -> tuple[int, dict[str, str], bytes]:
            connection = HTTPConnection("127.0.0.1", server.server_port, timeout=10)
            try:
                connection.request(method, path, headers={"Host": host} if host else {})
                response = connection.getresponse()
                return response.status, dict(response.getheaders()), response.read()
            finally:
                connection.close()

        try:
            assert server.server_address[0] == "127.0.0.1"
            yield request
        finally:
            server.shutdown()
            thread.join(timeout=5)
            assert not thread.is_alive()
    assert list(tmp_path.iterdir()) == []


def test_navigation_export_and_pipeline_parity(
    http: Request, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[dict[str, Any]] = []
    actual = dashboard.run_fixture

    def record(*args: Any, **kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        return actual(*args, **kwargs)

    monkeypatch.setattr(dashboard, "run_fixture", record)
    status, headers, content = http()
    assert status == 200
    assert headers["Content-Type"] == "text/html; charset=utf-8"
    page = Page(content.decode())
    assert len(page.forms) == 2
    assert {item.get("name") for item in page.inputs} >= {
        "scenario",
        "seed",
        "category",
        "axes",
    }
    assert all(form.get("method") == "get" for form in page.forms)
    assert b"Add target" in content and b"12.99%" in content
    assert b"Weekly expected counts" in content and b"Show scheduled" in content
    hold_link = next(link for link in page.links if "action=HOLD" in link)
    assert http(hold_link)[0] == 200
    assert b"HOLD preserves roster" in http(hold_link)[2]
    screened = next(link for link in page.links if "action=ADD%3Abad-target" in link)
    assert b"Screening estimate only" in http(screened)[2]
    selected_axes = "/?" + urlencode({"category": "TO", "action": "HOLD"})
    assert b'value="TO" checked' in http(selected_axes)[2]
    assert b'value="PTS" checked' not in http(selected_axes)[2]
    export = next(link for link in page.links if link.startswith("/report.json"))
    status, headers, raw = http(export)
    assert status == 200 and headers["Content-Type"] == "application/json"
    assert "attachment" in headers["Content-Disposition"]
    report = json.loads(raw)
    expected = run_fixture(
        tmp_path / "unused.duckdb",
        tmp_path / "unused-output",
        Registry(tmp_path / "unused-registry.json"),
        dry_run=True,
        seed=42,
    )
    assert report == expected
    assert http(export)[2] == raw
    assert len(calls) == 1 and calls[0]["dry_run"] is True


def test_failure_unknown_constraints_and_recovery(http: Request) -> None:
    assert http()[0] == 200
    status, _, content = http("/?scenario=partial_ingestion")
    assert status == 400 and b"Analysis unavailable" in content
    assert b"12.99%" not in content and b"MATCHUP ANALYSIS" not in content
    assert b"Reset to baseline" in content
    assert http()[0] == 200
    status, _, content = http("/?scenario=unknown_settings")
    assert status == 200
    assert b"Keep current roster" in content and b"Missing setting" in content
    report = json.loads(http("/report.json?scenario=transaction")[2])
    assert report["optimization"]["recommended_action"] == "HOLD"
    report = json.loads(http("/report.json?scenario=new_stats&seed=43")[2])
    assert report["scenario"] == "new_stats" and report["seed"] == 43


def test_routes_host_bounds_and_safe_errors(http: Request) -> None:
    assert http(host="malicious.example")[0] == 403
    assert http("/../pyproject.toml")[0] == 404
    assert http("/", method="POST")[0] == 501
    for query in (
        "seed=-1",
        "seed=4294967296",
        "seed=abc",
        "seed=1&seed=2",
        "category=UNKNOWN",
        "category=PTS&category=PTS",
        "axes=selected",
        "scenario=live",
        "token=SECRET",
        "action=%3Cscript%3ESECRET%3C/script%3E",
    ):
        status, _, content = http("/?" + query)
        assert status == 400
        assert b"SECRET" not in content
    assert http("/?" + "x" * 2048)[0] == 414
    status, headers, css = http("/style.css")
    assert status == 200 and b"@media(max-width:700px)" in css
    assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]
    assert headers["Cache-Control"] == "no-store"


def test_cache_bound_and_failed_runs_never_cached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def fake(*args: Any, **kwargs: Any) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        if kwargs["scenario"] == "partial_ingestion":
            raise OperationError("failed")
        return {"seed": kwargs["seed"]}

    monkeypatch.setattr(dashboard, "run_fixture", fake)
    app = dashboard.Dashboard()
    for seed in range(10):
        assert app.report("baseline", seed) == {"seed": seed}
    assert len(app.reports) == dashboard.MAX_REPORTS
    assert ("baseline", 0) not in app.reports
    assert app.report("baseline", 9) == {"seed": 9} and calls == 10
    with pytest.raises(OperationError):
        app.report("partial_ingestion", 9)
    assert ("partial_ingestion", 9) not in app.reports
    assert len(app.reports) == dashboard.MAX_REPORTS


def test_render_escapes_report_and_preserves_decision() -> None:
    report = dashboard.Dashboard().report("baseline", 42)
    original = copy.deepcopy(report)
    report["optimization"]["ranked_actions"][0]["explanation"] = (
        "<script>alert(1)</script>"
    )
    page = dashboard.render(report, ("TO",), None)
    assert "<script>" not in page and "&lt;script&gt;" in page
    assert (
        report["optimization"]["recommended_action"]
        == original["optimization"]["recommended_action"]
    )
    assert dashboard.render(original, CATEGORIES, None)
    assert (
        report["optimization"]["ranked_actions"][0]["category_win_deltas"]
        == original["optimization"]["ranked_actions"][0]["category_win_deltas"]
    )


def test_empty_estimates_do_not_invent_probabilities() -> None:
    report = dashboard.Dashboard().report("baseline", 42)
    report["optimization"]["ranked_actions"] = []
    report["optimization"]["recommended_action"] = "HOLD"
    page = dashboard.render(report, CATEGORIES, None)
    assert "Unavailable" in page and "No comparable estimates" in page
    assert "Category probabilities unavailable" in page
    assert "No verified action estimates" in page


def test_cli_fixture_and_port_gate(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["dashboard"]) == 1
    assert "Use --fixture" in capsys.readouterr().err
    with pytest.raises(SystemExit) as exc:
        main(["dashboard", "--fixture", "--port", "0"])
    assert exc.value.code == 2
