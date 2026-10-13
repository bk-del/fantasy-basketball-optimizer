"""Field evidence, not a production schema or inferred missing data."""

import hashlib
from datetime import UTC, datetime
from xml.etree import ElementTree

from fantasy_optimizer.yahoo import MAX_BODY, RESOURCES, YahooClient, YahooError

NAMESPACE = "https://fantasysports.yahooapis.com/fantasy/v2/base.rng"
NS = {"y": NAMESPACE}
# Explicit paths keep similarly named fields in unrelated resources from counting.
CHECKS = (
    ("league_settings", "settings", ".//y:league/y:settings"),
    ("scoring_categories", "settings", ".//y:settings/y:stat_categories"),
    ("roster_positions", "settings", ".//y:settings/y:roster_positions"),
    (
        "roster_eligibility",
        "roster",
        ".//y:roster/y:players/y:player/y:eligible_positions",
    ),
    ("owned_players", "roster", ".//y:roster/y:players"),
    ("league_players", "players", ".//y:league/y:players"),
    ("player_status", "players", ".//y:player/y:status"),
    ("current_player_stats", "stats", ".//y:player/y:player_stats/y:stats"),
    ("stat_windows", "stats", ".//y:player/y:player_stats/y:coverage_type"),
    ("matchups", "scoreboard", ".//y:scoreboard/y:matchups"),
    ("transactions", "transactions", ".//y:league/y:transactions"),
)
UNPROBED = {
    "unowned_player_availability": "unknown",
    "archived_stats": "documented_only",
    "future_nba_schedule": "unknown",
    "teammate_injury_on_off": "unknown",
    "historical_availability": "unknown",
    "historical_player_game_records": "unknown",
}
UNVERIFIED_FIELD_DOCS = {"roster_eligibility", "player_status"}


def parse_xml(body: bytes) -> ElementTree.Element:
    if len(body) > MAX_BODY:
        raise YahooError("invalid_response")
    try:
        text = body.decode("utf-8")
        if "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
            raise YahooError("invalid_response")
        root = ElementTree.fromstring(text)
    except (ElementTree.ParseError, UnicodeDecodeError):
        raise YahooError("invalid_response") from None
    accepted_namespaces = (NAMESPACE, NAMESPACE.replace("https://", "http://"))
    if root.tag not in {
        f"{{{namespace}}}fantasy_content" for namespace in accepted_namespaces
    }:
        raise YahooError("invalid_response")
    for element in root.iter():
        legacy_prefix = "{" + accepted_namespaces[1] + "}"
        if element.tag.startswith(legacy_prefix):
            element.tag = "{" + NAMESPACE + "}" + element.tag[len(legacy_prefix) :]
    return root


def audit(client: YahooClient) -> dict[str, object]:
    """Run six bounded probes; abort on auth/transport errors, never invent fields."""
    capabilities: dict[str, object] = {}
    sources: dict[str, object] = {}
    observed_at = (
        "2026-10-12T00:00:00Z"
        if client.mode == "fixture"
        else datetime.now(UTC).isoformat()
    )
    for resource in RESOURCES:
        body = client.fetch(resource)
        root = parse_xml(body)
        for name, source, path in CHECKS:
            if source != resource:
                continue
            element = root.find(path, NS)
            present = element is not None
            if element is not None and name == "stat_windows":
                present = bool(element.text and element.text.strip())
            capabilities[name] = {
                "classification": (
                    "confirmed_via_authorized_sample"
                    if present and client.mode == "authorized"
                    else "unknown"
                    if name in UNVERIFIED_FIELD_DOCS
                    else "documented_only"
                ),
                "field_present": present,
                "evidence": "synthetic_fixture"
                if client.mode == "fixture"
                else "authorized_sample",
                "resource": source,
                "limit": (
                    "Field presence only; populated values/history are unverified."
                ),
            }
        coverage = root.find(".//y:player_stats/y:coverage_type", NS)
        window = (
            coverage.text.strip() if coverage is not None and coverage.text else None
        )
        if window not in ("season", "week", "date", "lastweek", "lastmonth"):
            window = None
        sources[resource] = {
            "sha256": hashlib.sha256(body).hexdigest(),
            "observed_at": observed_at,
            "source_updated_at": None,
            "granularity": window if resource == "stats" else "resource_snapshot",
            "schema_fields": sorted(
                {element.tag.split("}")[-1] for element in root.iter()}
            ),
        }
    for name, classification in UNPROBED.items():
        capabilities[name] = {
            "classification": classification,
            "field_present": None,
            "evidence": "not_probed",
        }
    return {
        "report_version": 1,
        "mode": client.mode,
        "synthetic": client.mode == "fixture",
        "observation_time_is_synthetic": client.mode == "fixture",
        "scope_verified": False,
        "request_policy": {
            "resources": 6,
            "max_attempts_per_resource": 3,
            "timeout_seconds": 10,
            "minimum_interval_seconds": 1,
        },
        "capabilities": capabilities,
        "sources": sources,
        "limitations": [
            "Fixture presence never confirms Yahoo capability.",
            "Source freshness unknown; observation time is not publication/event time.",
            "Scoring definitions do not by themselves prove this league uses 9-CAT.",
            "Player status cannot establish teammate injuries/lineups/on-off effects.",
            "Historical availability/player-game history unverified; do not invent it.",
            "Five-player/transaction samples are not full availability inventories.",
        ],
    }
