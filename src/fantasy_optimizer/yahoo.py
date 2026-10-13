"""Bounded read-only requests and explicit synthetic fixtures; no OAuth login."""

import json
import logging
import math
import os
import re
import stat
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path
from typing import Literal, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

BASE_URL = "https://fantasysports.yahooapis.com/fantasy/v2"
MAX_BODY = 1_048_576
RESOURCES = ("settings", "roster", "players", "stats", "scoreboard", "transactions")
LOGGER = logging.getLogger(__name__)
MESSAGES = {
    "unapproved": "Yahoo access is unconfirmed. Use audit --fixture until approved.",
    "missing_auth": "No OAuth token file. Complete Yahoo authorization first.",
    "unsafe_token": (
        "Token file must be a private regular file owned by this user (0600)."
    ),
    "invalid_token": "Token file is invalid; replace it using authorized OAuth tokens.",
    "expired_auth": "OAuth token expired. Refresh or reauthorize outside this audit.",
    "denied_auth": (
        "Yahoo denied authorization. Check approval, consent and token validity."
    ),
    "invalid_keys": "Set matching YAHOO_LEAGUE_KEY and YAHOO_TEAM_KEY.",
    "timeout": "Yahoo request timed out. Retry the audit later.",
    "rate_limit": (
        "Yahoo limited requests. Stop and retry later; quota is unverified."
    ),
    "http_error": "Yahoo returned an HTTP error. Check access and retry later.",
    "network_error": "Yahoo is unreachable. Check connectivity or use audit --fixture.",
    "invalid_response": "Unexpected Yahoo response; do not treat it as valid data.",
}


class YahooError(Exception):
    """Expose a fixed diagnostic rather than response bodies, URLs or credentials."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(MESSAGES[code])


@dataclass(frozen=True)
class AccessToken:
    value: str = field(repr=False)
    expires_at: datetime


def load_token(path: Path) -> AccessToken:
    """Read a private token without following a final-component symlink."""
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        raise YahooError("missing_auth") from None
    except OSError:
        raise YahooError("unsafe_token") from None
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or info.st_mode & 0o077
        ):
            raise YahooError("unsafe_token")
        try:
            body = stream.read(16_385)
            if len(body) > 16_384:
                raise YahooError("invalid_token")
            data = json.loads(body)
            value, expiry = data["access_token"], data["expires_at"]
            if (
                not isinstance(value, str)
                or not value
                or not value.isascii()
                or not value.isprintable()
            ):
                raise YahooError("invalid_token")
            if any(character.isspace() for character in value):
                raise YahooError("invalid_token")
            if not isinstance(expiry, str):
                raise YahooError("invalid_token")
            expires_at = datetime.fromisoformat(expiry)
            if expires_at.tzinfo is None:
                raise YahooError("invalid_token")
            return AccessToken(value, expires_at.astimezone(UTC))
        except (ValueError, KeyError, TypeError, OSError):
            raise YahooError("invalid_token") from None


def auth_status(path: Path, approved: bool) -> dict[str, object]:
    """Local metadata only; the presence of a token does not verify consent/scopes."""
    try:
        token = load_token(path)
        state = (
            "expired" if token.expires_at <= datetime.now(UTC) else "present_unverified"
        )
    except YahooError as error:
        state = error.code
    return {
        "approval_declared": approved,
        "token_state": state,
        "network_checked": False,
    }


class YahooClient(Protocol):
    mode: Literal["fixture", "authorized"]

    def fetch(self, resource: str) -> bytes:
        """Read one of the six fixed audit resources."""
        ...


class FixtureYahooClient:
    """Handmade data, never an authorized Yahoo sample."""

    mode: Literal["fixture", "authorized"] = "fixture"

    def __init__(self, responses: Mapping[str, bytes] | None = None) -> None:
        if responses is None:
            data = json.loads(
                files("fantasy_optimizer")
                .joinpath("fixtures/yahoo_audit.json")
                .read_bytes()
            )
            responses = {name: data[name].encode("utf-8") for name in RESOURCES}
        self.responses = dict(responses)

    def fetch(self, resource: str) -> bytes:
        try:
            return self.responses[resource]
        except KeyError:
            raise YahooError("invalid_response") from None


@dataclass(frozen=True)
class Response:
    status: int
    body: bytes = field(default=b"", repr=False)
    retry_after: float | None = None


class NoRedirect(HTTPRedirectHandler):
    """Never forward a bearer token to a redirect target."""

    def redirect_request(
        self,
        req: Request,
        fp: object,
        code: int,
        msg: str,
        headers: object,
        newurl: str,
    ) -> None:
        return None


def http_get(request: Request, timeout: float) -> Response:
    try:
        with build_opener(NoRedirect()).open(request, timeout=timeout) as result:
            return Response(result.status, result.read(MAX_BODY + 1))
    except HTTPError as error:
        header = error.headers.get("Retry-After")
        delay = None
        if header is not None:
            try:
                delay = float(header)
            except ValueError:
                # An unparsed HTTP-date must not cause an early retry.
                delay = math.inf
        error.close()
        return Response(error.code, retry_after=delay)
    except TimeoutError:
        raise YahooError("timeout") from None
    except URLError as error:
        code = "timeout" if isinstance(error.reason, TimeoutError) else "network_error"
        raise YahooError(code) from None
    except OSError:
        raise YahooError("network_error") from None


class HttpYahooClient:
    """Six allowlisted GET routes; timeout=10s, >=1s spacing, <=3 attempts each."""

    mode: Literal["fixture", "authorized"] = "authorized"

    def __init__(
        self,
        *,
        approved: bool,
        token_path: Path,
        league_key: str,
        team_key: str,
        transport: Callable[[Request, float], Response] = http_get,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not approved:
            raise YahooError("unapproved")
        if not re.fullmatch(r"[a-zA-Z0-9]+\.l\.\d+", league_key):
            raise YahooError("invalid_keys")
        if not re.fullmatch(re.escape(league_key) + r"\.t\.\d+", team_key):
            raise YahooError("invalid_keys")
        self.token = load_token(token_path)
        self.paths = {
            "settings": f"/league/{league_key}/settings",
            "roster": f"/team/{team_key}/roster",
            "players": f"/league/{league_key}/players;count=5",
            "stats": f"/league/{league_key}/players;count=5/stats",
            "scoreboard": f"/league/{league_key}/scoreboard",
            "transactions": f"/league/{league_key}/transactions;count=5",
        }
        self.transport, self.sleep, self.clock = transport, sleep, clock
        self.last_request: float | None = None

    def fetch(self, resource: str) -> bytes:
        if resource not in self.paths:
            raise YahooError("invalid_response")
        for attempt in range(3):
            if self.last_request is not None:
                self.sleep(max(0.0, 1.0 - (self.clock() - self.last_request)))
            if self.token.expires_at <= datetime.now(UTC):
                raise YahooError("expired_auth")
            self.last_request = self.clock()
            request = Request(
                BASE_URL + self.paths[resource],
                headers={
                    "Authorization": f"Bearer {self.token.value}",
                    "Accept": "application/xml",
                },
                method="GET",
            )
            response = self.transport(request, 10.0)
            if response.status == 200:
                if len(response.body) > MAX_BODY:
                    raise YahooError("invalid_response")
                return response.body
            if response.status in (401, 403):
                raise YahooError("denied_auth")
            if response.status not in (429, 500, 502, 503, 504):
                raise YahooError("http_error")
            code = "rate_limit" if response.status == 429 else "http_error"
            if response.retry_after is not None and (
                not math.isfinite(response.retry_after) or response.retry_after < 0
            ):
                raise YahooError(code)
            delay = max(float(2**attempt), response.retry_after or 0.0)
            if attempt == 2 or not math.isfinite(delay) or delay > 10.0:
                raise YahooError(code)
            LOGGER.warning(
                json.dumps(
                    {
                        "event": "yahoo_retry",
                        "status": response.status,
                        "attempt": attempt + 1,
                    }
                )
            )
            self.sleep(delay)
        raise AssertionError("Bounded retry loop must return or raise")
