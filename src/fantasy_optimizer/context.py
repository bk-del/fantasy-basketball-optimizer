"""Count-only shift diagnostics and preregistered labels; no injury inference."""

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from math import isfinite, sqrt
from statistics import mean, variance
from typing import Any

from fantasy_optimizer.forecasting import Window, known_windows
from fantasy_optimizer.storage import canonical, digest, timestamp


@dataclass(frozen=True)
class BreakoutProtocol:
    version: str = "weekly-production-breakout-v1"
    baseline_weeks: int = 4
    recent_weeks: int = 2
    horizon_weeks: int = 2
    minimum_future_games: int = 4
    minimum_availability: float = 0.75
    sustained_gain: float = 0.25
    minimum_baseline_points: float = 10.0
    shift_standard_errors: float = 2.0

    def __post_init__(self) -> None:
        if not self.version or any(
            type(v) is not int or v < 1
            for v in (
                self.baseline_weeks,
                self.recent_weeks,
                self.horizon_weeks,
                self.minimum_future_games,
            )
        ):
            raise ValueError("Invalid breakout protocol counts/version.")
        if any(
            not isfinite(v)
            for v in (
                self.minimum_availability,
                self.sustained_gain,
                self.minimum_baseline_points,
                self.shift_standard_errors,
            )
        ):
            raise ValueError("Protocol thresholds must be finite.")
        if (
            not 0 <= self.minimum_availability <= 1
            or self.sustained_gain <= 0
            or self.minimum_baseline_points <= 0
            or self.shift_standard_errors <= 0
        ):
            raise ValueError("Invalid breakout thresholds.")


PROTOCOL = BreakoutProtocol()


@dataclass(frozen=True)
class ExposureEvidence:
    """Proposed label metadata, not a claim about Yahoo field availability."""

    player_key: str
    window_start: datetime
    games_played: int
    scheduled_games: int
    observed_at: datetime
    ingested_at: datetime
    source: str

    def __post_init__(self) -> None:
        for value in (self.window_start, self.observed_at, self.ingested_at):
            timestamp(value.isoformat())
        if (
            not self.player_key
            or not self.source
            or type(self.games_played) is not int
            or type(self.scheduled_games) is not int
            or not 0 <= self.games_played <= self.scheduled_games
            or self.scheduled_games < 1
            or self.window_start + timedelta(days=7) > self.observed_at
            or self.observed_at > self.ingested_at
        ):
            raise ValueError("Invalid observed game/availability evidence.")


def _contiguous(rows: list[Window], origin: datetime, weeks: int) -> bool:
    return (
        len(rows) == weeks
        and rows[-1].end == origin
        and all(a.end == b.start for a, b in zip(rows, rows[1:], strict=False))
    )


def shift_features(
    windows: list[Window],
    player_key: str,
    as_of: datetime,
    protocol: BreakoutProtocol = PROTOCOL,
) -> dict[str, Any]:
    """A diagnostic alarm, never a calibrated breakout probability."""
    origin = timestamp(as_of.isoformat())
    selected = [r for r in known_windows(windows, origin) if r.player_key == player_key]
    needed = protocol.baseline_weeks + protocol.recent_weeks
    rows = selected[-needed:]
    result: dict[str, Any] = {
        "player_key": player_key,
        "as_of": origin.isoformat(),
        "protocol_version": protocol.version,
        "protocol_hash": digest(canonical(asdict(protocol))),
        "input_hash": digest(canonical([r.payload() for r in rows])),
        "known_windows": len(selected),
        "required_windows": needed,
        "usable_points_windows": sum(r.counts[5] is not None for r in rows),
        "baseline_points": None,
        "recent_points": None,
        "relative_gain": None,
        "shift_standard_errors": None,
        "shift_detected": None,
        "breakout_probability": None,
        "coverage": {
            "weekly_counts": "synthetic_only",
            "minutes": "unverified",
            "availability_status": "unverified",
            "game_exposure": "unverified",
            "transactions": "unverified",
            "opponent_role": "unverified",
            "teammate_injury_on_off": "unverified",
            "usage_rate": "unverified",
        },
        "skipped_features": [
            "minutes",
            "availability_status",
            "game_exposure",
            "transactions",
            "opponent_role",
            "teammate_injury_on_off",
            "usage_rate",
        ],
        "ambiguity": (
            "Weekly count changes can reflect "
            "games/exposure, variance or production; "
            "no role/injury cause is identified."
        ),
    }
    if not _contiguous(rows, origin, needed):
        result["skip_reason"] = (
            "Insufficient contiguous known-at-origin weekly history."
        )
        return result
    if any(r.counts[5] is None for r in rows):
        result["skip_reason"] = "Missing weekly PTS is not imputed as zero."
        return result
    values = [float(r.counts[5]) for r in rows if r.counts[5] is not None]
    baseline, recent = (
        values[: protocol.baseline_weeks],
        values[protocol.baseline_weeks :],
    )
    old, new = mean(baseline), mean(recent)
    noise = sqrt(
        (variance(baseline) if len(baseline) > 1 else 0) / len(baseline)
        + (variance(recent) if len(recent) > 1 else 0) / len(recent)
    )
    # The one-point floor avoids infinite evidence from constant synthetic counts.
    shift = (new - old) / max(noise, 1.0)
    gain = new / old - 1 if old >= protocol.minimum_baseline_points else None
    result.update(
        baseline_points=old,
        recent_points=new,
        relative_gain=gain,
        shift_standard_errors=shift,
        shift_detected=(
            gain is not None
            and gain >= protocol.sustained_gain
            and shift >= protocol.shift_standard_errors
            and all(v >= old * (1 + protocol.sustained_gain) for v in recent)
        ),
    )
    return result


def breakout_label(
    windows: list[Window],
    exposures: tuple[ExposureEvidence, ...],
    player_key: str,
    origin: datetime,
    evaluated_at: datetime,
    protocol: BreakoutProtocol = PROTOCOL,
) -> dict[str, Any]:
    """Future outcomes label the case; origin features remain immutable."""
    origin = timestamp(origin.isoformat())
    evaluated_at = timestamp(evaluated_at.isoformat())
    if evaluated_at < origin:
        raise ValueError("Label evaluation precedes feature origin.")
    horizon = origin + timedelta(weeks=protocol.horizon_weeks)
    features = shift_features(windows, player_key, origin, protocol)
    result: dict[str, Any] = {
        "player_key": player_key,
        "origin": origin.isoformat(),
        "evaluated_at": evaluated_at.isoformat(),
        "horizon_end": horizon.isoformat(),
        "protocol_hash": features["protocol_hash"],
        "feature_input_hash": features["input_hash"],
        "label": None,
        "outcome_input_hash": None,
    }
    if (
        features["baseline_points"] is None
        or features["baseline_points"] < protocol.minimum_baseline_points
    ):
        result["skip_reason"] = "Insufficient nontrivial origin baseline."
        return result
    targets = [
        r
        for r in known_windows(windows, evaluated_at)
        if r.player_key == player_key and origin <= r.start < horizon
    ]
    if (
        not _contiguous(targets, horizon, protocol.horizon_weeks)
        or targets[0].start != origin
    ):
        result["skip_reason"] = "Future label horizon is incomplete at evaluation time."
        return result
    if any(r.counts[5] is None for r in targets):
        result["skip_reason"] = "Future PTS counts are incomplete."
        return result
    selected: dict[datetime, ExposureEvidence] = {}
    for evidence in exposures:
        if (
            evidence.player_key != player_key
            or evidence.ingested_at > evaluated_at
            or not origin <= evidence.window_start < horizon
        ):
            continue
        previous = selected.get(evidence.window_start)
        if previous is not None and previous != evidence:
            raise ValueError(
                "Conflicting label exposure; resolve revisions explicitly."
            )
        selected[evidence.window_start] = evidence
    if any(r.start not in selected for r in targets):
        result["skip_reason"] = (
            "Games and scheduled-availability evidence is missing; no breakout label."
        )
        return result
    evidence_rows = [selected[r.start] for r in targets]
    result["outcome_input_hash"] = digest(
        canonical(
            {
                "windows": [r.payload() for r in targets],
                "exposure": [
                    dict(
                        asdict(e),
                        window_start=e.window_start.isoformat(),
                        observed_at=e.observed_at.isoformat(),
                        ingested_at=e.ingested_at.isoformat(),
                    )
                    for e in evidence_rows
                ],
            }
        )
    )
    if sum(
        e.games_played for e in evidence_rows
    ) < protocol.minimum_future_games or any(
        e.games_played / e.scheduled_games < protocol.minimum_availability
        for e in evidence_rows
    ):
        result["skip_reason"] = (
            "Future game/availability minimum not met; case excluded."
        )
        return result
    threshold = features["baseline_points"] * (1 + protocol.sustained_gain)
    result["label"] = all(
        r.counts[5] is not None and r.counts[5] >= threshold for r in targets
    )
    return result
