"""Representative boundaries using handmade fixtures, never production Yahoo data."""

import json
from collections import deque
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request

import pytest

from fantasy_optimizer.audit import NAMESPACE, audit, parse_xml
from fantasy_optimizer.cli import main
from fantasy_optimizer.yahoo import (
    FixtureYahooClient,
    HttpYahooClient,
    Response,
    YahooError,
    auth_status,
    http_get,
    load_token,
)

SYNTHETIC_TOKEN = "synthetic-test-access-token"


@pytest.fixture
def token_path(tmp_path: Path) -> Path:
    path = tmp_path / "tokens.json"
    path.write_text(
        json.dumps(
            {
                "access_token": SYNTHETIC_TOKEN,
                "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
            }
        )
    )
    path.chmod(0o600)
    return path


class ScriptedTransport:
    def __init__(self, responses: list[Response]) -> None:
        self.responses = deque(responses)
        self.requests: list[Request] = []
        self.time = 0.0
        self.delays: list[float] = []

    def __call__(self, request: Request, timeout: float) -> Response:
        assert timeout == 10.0
        assert request.get_method() == "GET"
        assert request.full_url.startswith(
            "https://fantasysports.yahooapis.com/fantasy/v2/"
        )
        self.requests.append(request)
        return self.responses.popleft()

    def sleep(self, seconds: float) -> None:
        self.delays.append(seconds)
        self.time += seconds

    def clock(self) -> float:
        return self.time


def client_for(path: Path, transport: ScriptedTransport) -> HttpYahooClient:
    return HttpYahooClient(
        approved=True,
        token_path=path,
        league_key="0.l.1",
        team_key="0.l.1.t.1",
        transport=transport,
        sleep=transport.sleep,
        clock=transport.clock,
    )


def test_fixture_report_is_deterministic_and_not_authorized() -> None:
    result = audit(FixtureYahooClient())
    assert result == audit(FixtureYahooClient())
    assert result["synthetic"] is True
    assert result["scope_verified"] is False
    assert "confirmed_via_authorized_sample" not in json.dumps(result)
    assert result["sources"]["stats"]["granularity"] == "season"
    assert result["sources"]["stats"]["source_updated_at"] is None
    assert (
        result["capabilities"]["historical_availability"]["classification"] == "unknown"
    )


def test_missing_field_remains_missing_not_unavailable() -> None:
    fixture = FixtureYahooClient()
    fixture.responses["players"] = (
        f'<fantasy_content xmlns="{NAMESPACE}">'
        "<league><players /></league></fantasy_content>"
    ).encode()
    result = audit(fixture)
    status = result["capabilities"]["player_status"]
    assert status["field_present"] is False
    assert status["classification"] == "unknown"


def test_documented_legacy_namespace_is_supported() -> None:
    body = FixtureYahooClient().fetch("settings")
    legacy = body.replace(b"https://fantasysports", b"http://fantasysports")
    root = parse_xml(legacy)
    assert root.find(f".//{{{NAMESPACE}}}settings") is not None


def test_utf16_entity_declaration_cannot_bypass_guard() -> None:
    body = '<!DOCTYPE a [<!ENTITY a "fake">]><a>&a;</a>'.encode("utf-16")
    with pytest.raises(YahooError, match="Unexpected Yahoo response"):
        parse_xml(body)


@pytest.mark.parametrize(
    "body",
    [
        b"not xml",
        b"<fantasy_content />",
        b'<!DOCTYPE a [<!ENTITY a "fake">]><a>&a;</a>',
        b"x" * 1_048_577,
    ],
)
def test_invalid_xml_is_rejected(body: bytes) -> None:
    with pytest.raises(YahooError, match="Unexpected Yahoo response"):
        parse_xml(body)


def test_fixture_cli_ignores_unusable_credentials(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("YAHOO_TOKEN_FILE", "/nonexistent/private-token")
    assert main(["audit", "--fixture"]) == 0
    assert json.loads(capsys.readouterr().out)["mode"] == "fixture"


def test_live_cli_refuses_unapproved_access(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("YAHOO_ACCESS_APPROVED", raising=False)
    assert main(["audit"]) == 1
    assert json.loads(capsys.readouterr().err)["error"] == "unapproved"


def test_token_privacy_and_local_status(token_path: Path) -> None:
    token = load_token(token_path)
    assert SYNTHETIC_TOKEN not in repr(token)
    assert SYNTHETIC_TOKEN not in repr(Response(200, SYNTHETIC_TOKEN.encode()))
    metadata = auth_status(token_path, True)
    assert metadata == {
        "approval_declared": True,
        "token_state": "present_unverified",
        "network_checked": False,
    }
    assert SYNTHETIC_TOKEN not in json.dumps(metadata)
    token_path.chmod(0o644)
    with pytest.raises(YahooError, match="private regular file"):
        load_token(token_path)


def test_token_symlink_and_invalid_data_are_rejected(token_path: Path) -> None:
    link = token_path.with_name("link.json")
    link.symlink_to(token_path)
    with pytest.raises(YahooError, match="private regular file"):
        load_token(link)
    token_path.write_text(
        json.dumps({"access_token": SYNTHETIC_TOKEN, "expires_at": "2026-01-01"})
    )
    assert auth_status(token_path, True)["token_state"] == "invalid_token"


def test_missing_and_expired_tokens_make_no_requests(token_path: Path) -> None:
    transport = ScriptedTransport([])
    with pytest.raises(YahooError, match="No OAuth token file"):
        client_for(token_path.with_name("missing.json"), transport)
    token_path.write_text(
        json.dumps(
            {"access_token": SYNTHETIC_TOKEN, "expires_at": "2000-01-01T00:00:00Z"}
        )
    )
    client = client_for(token_path, transport)
    assert auth_status(token_path, True)["token_state"] == "expired"
    with pytest.raises(YahooError, match="OAuth token expired"):
        client.fetch("settings")
    assert transport.requests == []


def test_keys_cannot_escape_allowed_host(token_path: Path) -> None:
    with pytest.raises(YahooError, match="matching YAHOO_LEAGUE_KEY"):
        HttpYahooClient(
            approved=True,
            token_path=token_path,
            league_key="https://other.invalid",
            team_key="0.l.1.t.1",
        )


def test_retry_after_and_throttle(
    token_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    transport = ScriptedTransport(
        [
            Response(429, SYNTHETIC_TOKEN.encode(), 2.0),
            Response(200, b"first"),
            Response(200, b"second"),
        ]
    )
    client = client_for(token_path, transport)
    assert client.fetch("settings") == b"first"
    assert client.fetch("roster") == b"second"
    assert len(transport.requests) == 3
    assert 2.0 in transport.delays
    assert 1.0 in transport.delays
    assert SYNTHETIC_TOKEN not in caplog.text
    assert "yahoo_retry" in caplog.text


@pytest.mark.parametrize(
    "status, code, attempts",
    [
        (401, "denied_auth", 1),
        (403, "denied_auth", 1),
        (429, "rate_limit", 3),
        (503, "http_error", 3),
    ],
)
def test_failure_stops_at_bounded_attempts(
    token_path: Path,
    status: int,
    code: str,
    attempts: int,
    caplog: pytest.LogCaptureFixture,
) -> None:
    transport = ScriptedTransport(
        [Response(status, SYNTHETIC_TOKEN.encode())] * attempts
    )
    with pytest.raises(YahooError) as exc:
        client_for(token_path, transport).fetch("settings")
    assert exc.value.code == code
    assert len(transport.requests) == attempts
    assert SYNTHETIC_TOKEN not in str(exc.value) + caplog.text


@pytest.mark.parametrize("delay", [3600.0, float("inf"), float("nan"), -1.0])
def test_invalid_or_long_retry_after_stops_without_waiting(
    token_path: Path, delay: float
) -> None:
    transport = ScriptedTransport([Response(429, retry_after=delay)])
    with pytest.raises(YahooError) as exc:
        client_for(token_path, transport).fetch("settings")
    assert exc.value.code == "rate_limit"
    assert transport.delays == []


def test_transport_timeout_is_sanitized(monkeypatch: pytest.MonkeyPatch) -> None:
    class FailingOpener:
        def open(self, request: Request, timeout: float) -> None:
            raise URLError(TimeoutError(SYNTHETIC_TOKEN))

    monkeypatch.setattr(
        "fantasy_optimizer.yahoo.build_opener", lambda *args: FailingOpener()
    )
    with pytest.raises(YahooError) as exc:
        http_get(Request("https://fantasysports.yahooapis.com/fantasy/v2"), 10.0)
    assert exc.value.code == "timeout"
    assert SYNTHETIC_TOKEN not in str(exc.value)
