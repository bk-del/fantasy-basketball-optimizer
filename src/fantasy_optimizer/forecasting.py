"""Point-in-time weekly count baselines and a joint empirical predictive contract."""

import math
import random
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from statistics import mean, variance
from typing import Any

from fantasy_optimizer.storage import canonical, digest, timestamp

STATS = ("FGM", "FGA", "FTM", "FTA", "3PM", "PTS", "REB", "AST", "STL", "BLK", "TO")
MODEL_VERSION = "weekly-counts-v1"
FEATURE_VERSION = "weekly-aggregates-v1"
MODELS = ("long_run", "recency", "shrinkage")
CONFIG = {"half_life_days": 28.0, "prior_strength_min": 2.0, "prior_strength_max": 20.0}


@dataclass(frozen=True)
class ForecastConfig:
    half_life_days: float = 28.0
    prior_strength_min: float = 2.0
    prior_strength_max: float = 20.0

    def __post_init__(self) -> None:
        values = asdict(self).values()
        if any(type(v) not in (int, float) or not math.isfinite(v) for v in values):
            raise ForecastError("Forecast configuration must be finite numeric values.")
        if not 1 <= self.half_life_days <= 365:
            raise ForecastError("Half-life must be 1..365 days.")
        if not 0 < self.prior_strength_min <= self.prior_strength_max <= 100:
            raise ForecastError("Invalid prior strength bounds.")


def count(value: int | None) -> int:
    if value is None:
        raise ForecastError("Missing count cannot be used as zero.")
    return value


class ForecastError(Exception):
    """Safe contract diagnostic."""


def validate_counts(counts: tuple[int | None, ...]) -> None:
    if len(counts) != len(STATS):
        raise ForecastError("Invalid player/count contract.")
    if any(
        value is not None and (type(value) is not int or value < 0) for value in counts
    ):
        raise ForecastError("Counts must be nonnegative integers or missing.")
    stats = dict(zip(STATS, counts, strict=True))
    for made, attempted in (("FGM", "FGA"), ("FTM", "FTA"), ("3PM", "FGM")):
        if stats[made] is not None and stats[attempted] is not None:
            if count(stats[made]) > count(stats[attempted]):
                raise ForecastError("Makes exceed attempts or threes exceed makes.")
    if all(stats[key] is not None for key in ("FGM", "FTM", "3PM", "PTS")):
        if stats["PTS"] != 2 * count(stats["FGM"]) + count(stats["3PM"]) + count(
            stats["FTM"]
        ):
            raise ForecastError("Points disagree with makes.")


@dataclass(frozen=True)
class Window:
    player_key: str
    start: datetime
    end: datetime
    observed_at: datetime
    ingested_at: datetime
    counts: tuple[int | None, ...]

    def __post_init__(self) -> None:
        for value in (self.start, self.end, self.observed_at, self.ingested_at):
            if value.tzinfo is None:
                raise ForecastError("Forecast timestamps must have timezones.")
        if self.end - self.start != timedelta(days=7):
            raise ForecastError("This baseline requires disjoint seven-day windows.")
        if self.end > self.observed_at or self.observed_at > self.ingested_at:
            raise ForecastError("Invalid event/observation/ingestion ordering.")
        if not self.player_key:
            raise ForecastError("Missing player key.")
        validate_counts(self.counts)

    def payload(self) -> dict[str, Any]:
        return {
            "player_key": self.player_key,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "observed_at": self.observed_at.isoformat(),
            "ingested_at": self.ingested_at.isoformat(),
            "counts": dict(zip(STATS, self.counts, strict=True)),
        }


def known_windows(windows: list[Window], as_of: datetime) -> list[Window]:
    """Filter before resolving revisions, so later corrections cannot leak backwards."""
    as_of = timestamp(as_of.isoformat())
    selected: dict[tuple[str, datetime], Window] = {}
    for window in windows:
        if max(window.end, window.observed_at, window.ingested_at) > as_of:
            continue
        key = (window.player_key, window.start)
        previous = selected.get(key)
        order = (window.observed_at, window.ingested_at)
        if previous and order == (previous.observed_at, previous.ingested_at):
            if previous != window:
                raise ForecastError("Conflicting revision at the same timestamp.")
        if previous is None or order > (previous.observed_at, previous.ingested_at):
            selected[key] = window
    result = sorted(selected.values(), key=lambda row: (row.player_key, row.start))
    for previous, current in zip(result, result[1:], strict=False):
        if previous.player_key == current.player_key and previous.end > current.start:
            raise ForecastError("Overlapping windows cannot be treated as independent.")
    return result


@dataclass
class RunningAggregate:
    """O(stats) updates for newly completed windows; rebuild selected revisions."""

    count: int = 0
    latest_end: datetime | None = None
    totals: list[float] = field(default_factory=lambda: [0.0] * len(STATS))
    weights: list[float] = field(default_factory=lambda: [0.0] * len(STATS))
    decayed_totals: list[float] = field(default_factory=lambda: [0.0] * len(STATS))
    decayed_weights: list[float] = field(default_factory=lambda: [0.0] * len(STATS))

    config: ForecastConfig = field(default_factory=ForecastConfig)

    def update(self, window: Window) -> None:
        if self.latest_end and window.end <= self.latest_end:
            raise ForecastError("Aggregate updates must be chronological and unique.")
        days = (
            0.0
            if self.latest_end is None
            else (window.end - self.latest_end).total_seconds() / 86400
        )
        decay = 2 ** (-days / self.config.half_life_days)
        for index, value in enumerate(window.counts):
            self.decayed_totals[index] *= decay
            self.decayed_weights[index] *= decay
            if value is not None:
                self.totals[index] += value
                self.weights[index] += 1
                self.decayed_totals[index] += value
                self.decayed_weights[index] += 1
        self.latest_end = window.end
        self.count += 1

    def features(self) -> dict[str, Any]:
        return {
            "count": self.count,
            "latest_end": self.latest_end.isoformat() if self.latest_end else None,
            "totals": self.totals.copy(),
            "weights": self.weights.copy(),
            "decayed_totals": self.decayed_totals.copy(),
            "decayed_weights": self.decayed_weights.copy(),
        }


def recency_weights(
    ends: list[datetime], as_of: datetime, half_life: float
) -> list[float]:
    """Normalize relative ages to avoid underflow for stale historical support."""
    latest = max(ends)
    weights = [
        2 ** (-(latest - end).total_seconds() / 86400 / half_life) for end in ends
    ]
    total = sum(weights)
    return [weight / total for weight in weights]


def strength_from_moments(
    within: list[float],
    between: list[float],
    inverse_sizes: list[float],
    config: ForecastConfig,
) -> float:
    ratios = []
    for noise, dispersion, inverse in zip(within, between, inverse_sizes, strict=True):
        signal = max(0.0, dispersion - noise * inverse)
        ratios.append(config.prior_strength_max if signal == 0 else noise / signal)
    estimate = mean(ratios) if ratios else config.prior_strength_min
    return min(config.prior_strength_max, max(config.prior_strength_min, estimate))


def joint_count_draw(
    values: tuple[int | None, ...], shock: float
) -> dict[str, int | None]:
    """Shared whole-vector exposure and points identity for every horizon."""
    draw = {
        s: None if x is None else round(x * shock)
        for s, x in zip(STATS, values, strict=True)
    }
    if all(draw[k] is not None for k in ("FGM", "FTM", "3PM", "PTS")):
        draw["PTS"] = 2 * count(draw["FGM"]) + count(draw["3PM"]) + count(draw["FTM"])
    return draw


def prior_strength(peers: list[Window], config: ForecastConfig | None = None) -> float:
    """Moment estimate of within-player noise / between-player signal, clipped."""
    config = config or ForecastConfig()
    groups: dict[str, list[Window]] = {}
    for row in peers:
        groups.setdefault(row.player_key, []).append(row)
    ratios: list[float] = []
    for index in range(len(STATS)):
        values = [
            [count(row.counts[index]) for row in group if row.counts[index] is not None]
            for group in groups.values()
        ]
        samples = [sample for sample in values if len(sample) >= 2]
        if len(samples) < 2:
            continue
        within = mean(variance(sample) for sample in samples)
        between = variance(mean(sample) for sample in samples)
        signal = max(0.0, between - mean(within / len(sample) for sample in samples))
        ratios.append(config.prior_strength_max if signal == 0 else within / signal)
    estimate = mean(ratios) if ratios else config.prior_strength_min
    return min(config.prior_strength_max, max(config.prior_strength_min, estimate))


@dataclass(frozen=True)
class Forecast:
    contract_version: int
    model_version: str
    model: str
    player_key: str
    as_of: str
    horizon_start: str
    horizon_end: str
    granularity: str
    input_hash: str
    config_hash: str
    seed: int
    expected_counts: dict[str, float | None]
    intervals_80: dict[str, list[int] | None]
    mean_mc_standard_error: dict[str, float | None]
    joint_samples: list[dict[str, int | None]]
    feature_snapshot: dict[str, Any]
    assumptions: dict[str, Any]
    warnings: list[str]

    def payload(self) -> dict[str, Any]:
        return asdict(self)


def forecast(
    windows: list[Window],
    player_key: str,
    as_of: datetime,
    *,
    model: str = "recency",
    seed: int = 42,
    samples: int = 256,
    config: ForecastConfig | None = None,
) -> Forecast:
    if model not in MODELS or not 32 <= samples <= 10000:
        raise ForecastError("Invalid baseline or sample count (32..10000).")
    config = config or ForecastConfig()
    as_of = timestamp(as_of.isoformat())
    known = known_windows(windows, as_of)
    own = [row for row in known if row.player_key == player_key]
    peers = [row for row in known if row.player_key != player_key]
    if not own:
        raise ForecastError("No player windows known at forecast time.")
    own_weights = [
        1.0
        if model == "long_run"
        else 2 ** (-(as_of - row.end).total_seconds() / 86400 / config.half_life_days)
        for row in own
    ]
    total = sum(own_weights)
    own_weights = [weight / total for weight in own_weights]
    effective_n = 1 / sum(weight * weight for weight in own_weights)
    strength = prior_strength(peers, config) if model == "shrinkage" and peers else 0.0
    alpha = effective_n / (effective_n + strength)
    # Each peer contributes equal mass regardless of its available history length.
    peer_sizes = Counter(row.player_key for row in peers)
    peer_weights = [1 / len(peer_sizes) / peer_sizes[row.player_key] for row in peers]
    support = own + (peers if strength else [])
    weights = [alpha * weight for weight in own_weights] + (
        [(1 - alpha) * weight for weight in peer_weights] if strength else []
    )
    missing = {
        stat
        for index, stat in enumerate(STATS)
        if any(row.counts[index] is None for row in support)
    }
    for made, attempted in (("FGM", "FGA"), ("FTM", "FTA")):
        if made in missing or attempted in missing:
            missing.update((made, attempted))
    expected: dict[str, float | None] = {}
    for index, stat in enumerate(STATS):
        expected[stat] = (
            None
            if stat in missing
            else sum(
                weight * float(count(row.counts[index]))
                for row, weight in zip(support, weights, strict=True)
            )
        )
    aggregate = RunningAggregate(config=config)
    for row in own:
        aggregate.update(row)
    input_hash = digest(canonical([row.payload() for row in known]))
    rng = random.Random(int(digest(canonical([seed, player_key])), 16))
    draws: list[dict[str, int | None]] = []
    for _ in range(samples):
        row = rng.choices(support, weights=weights, k=1)[0]
        # One shared exposure shock preserves dependence; it is an explicit proxy.
        shock = rng.choice((0.5, 1.0, 1.5) if len(own) < 3 else (0.75, 1.0, 1.25))
        draw = joint_count_draw(
            tuple(
                None if stat in missing else row.counts[index]
                for index, stat in enumerate(STATS)
            ),
            shock,
        )
        draws.append(draw)
    intervals: dict[str, list[int] | None] = {}
    mc_errors: dict[str, float | None] = {}
    for stat in STATS:
        values = sorted(count(draw[stat]) for draw in draws if draw[stat] is not None)
        intervals[stat] = (
            [values[int(0.1 * (samples - 1))], values[int(0.9 * (samples - 1))]]
            if values
            else None
        )
        mc_errors[stat] = (
            math.sqrt(variance(values) / len(values)) if len(values) > 1 else None
        )
    warnings = [
        "Synthetic/weekly contract; no verified Yahoo game-level history.",
        "Empirical intervals are uncalibrated outside the toy fixture.",
        "No verified game schedule, minutes or availability probability.",
        "Unknown exposure: shared shock; heuristic, not calibrated.",
    ]
    if len(own) < 3:
        warnings.append("Small sample: shared 0.5/1/1.5 exposure uncertainty proxy.")
    if model == "shrinkage" and not peers:
        warnings.append("No contemporaneous peer prior; falling back to recency.")
    if missing:
        warnings.append("Missing counts remain null: " + ", ".join(sorted(missing)))
    return Forecast(
        1,
        MODEL_VERSION,
        model,
        player_key,
        as_of.isoformat(),
        as_of.isoformat(),
        (as_of + timedelta(days=7)).isoformat(),
        "weekly_aggregate",
        input_hash,
        digest(canonical(asdict(config))),
        seed,
        expected,
        intervals,
        mc_errors,
        draws,
        {
            "version": FEATURE_VERSION,
            "as_of": as_of.isoformat(),
            "input_hash": input_hash,
            "aggregate": aggregate.features(),
            "effective_windows": effective_n,
            "prior_strength": strength,
            "own_weight": alpha,
            "missing_stats": sorted(missing),
        },
        {
            "exposure_multipliers": [0.5, 1.0, 1.5]
            if len(own) < 3
            else [0.75, 1.0, 1.25],
            "game_count": None,
            "availability_probability": None,
            "minutes": None,
            "sampling": "joint empirical count vectors; equal-player peer mixture",
            "interval": "central empirical 80%; mean MC SE is sampling error only",
        },
        warnings,
    )
