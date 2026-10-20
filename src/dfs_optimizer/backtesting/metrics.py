from __future__ import annotations

import math
from dataclasses import dataclass

from dfs_optimizer.models import Projection

from .contest_results import PlayerResult


@dataclass(frozen=True, slots=True)
class ProjectionMetrics:
    matched_players: int
    mean_absolute_error: float
    root_mean_squared_error: float
    mean_error: float
    correlation: float | None
    range_samples: int = 0
    interval_coverage: float | None = None
    ceiling_exceed_rate: float | None = None
    ownership_samples: int = 0
    ownership_mean_absolute_error: float | None = None
    ownership_mean_error: float | None = None
    ownership_correlation: float | None = None
    zero_point_players: int = 0
    zero_point_rate: float = 0.0


@dataclass(frozen=True, slots=True)
class ProjectionEvaluationRow:
    name: str
    position: str
    projected: float
    actual: float
    error: float
    absolute_error: float
    floor: float | None
    ceiling: float | None
    projected_ownership: float | None = None
    actual_ownership: float | None = None
    bust_probability: float | None = None
    confidence_score: float | None = None
    confidence_tier: str | None = None


def evaluate_projections(
    projections: tuple[Projection, ...],
    actuals: tuple[PlayerResult, ...],
    excluded_player_names: frozenset[str] = frozenset(),
) -> ProjectionMetrics:
    rows = evaluate_projection_rows(
        projections, actuals, excluded_player_names=excluded_player_names
    )
    if not rows:
        raise ValueError("no projections matched contest player results")
    errors = [row.error for row in rows]
    ranged = [row for row in rows if row.floor is not None and row.ceiling is not None]
    correlation = _correlation(
        [row.projected for row in rows], [row.actual for row in rows]
    )
    ownership_rows = [
        row for row in rows
        if row.projected_ownership is not None and row.actual_ownership is not None
    ]
    ownership_errors = [
        row.projected_ownership - row.actual_ownership
        for row in ownership_rows
    ]
    return ProjectionMetrics(
        matched_players=len(rows),
        mean_absolute_error=sum(abs(error) for error in errors) / len(errors),
        root_mean_squared_error=math.sqrt(sum(error * error for error in errors) / len(errors)),
        mean_error=sum(errors) / len(errors),
        correlation=correlation,
        range_samples=len(ranged),
        interval_coverage=(
            sum(row.floor <= row.actual <= row.ceiling for row in ranged) / len(ranged)
            if ranged else None
        ),
        ceiling_exceed_rate=(
            sum(row.actual > row.ceiling for row in ranged) / len(ranged)
            if ranged else None
        ),
        ownership_samples=len(ownership_rows),
        ownership_mean_absolute_error=(
            sum(abs(error) for error in ownership_errors) / len(ownership_errors)
            if ownership_errors else None
        ),
        ownership_mean_error=(
            sum(ownership_errors) / len(ownership_errors)
            if ownership_errors else None
        ),
        ownership_correlation=(
            _correlation(
                [row.projected_ownership for row in ownership_rows],
                [row.actual_ownership for row in ownership_rows],
            )
            if ownership_rows else None
        ),
        zero_point_players=sum(row.actual == 0 for row in rows),
        zero_point_rate=sum(row.actual == 0 for row in rows) / len(rows),
    )


def evaluate_projection_rows(
    projections: tuple[Projection, ...],
    actuals: tuple[PlayerResult, ...],
    excluded_player_names: frozenset[str] = frozenset(),
) -> tuple[ProjectionEvaluationRow, ...]:
    excluded = {_normalize(name) for name in excluded_player_names}
    actual_by_name: dict[str, list[PlayerResult]] = {}
    for item in actuals:
        actual_by_name.setdefault(_normalize(item.name), []).append(item)
    rows = []
    for projection in projections:
        if _normalize(projection.name) in excluded:
            continue
        candidates = actual_by_name.get(_normalize(projection.name), [])
        if len(candidates) != 1:
            continue
        actual = candidates[0]
        error = projection.projected_points - actual.fantasy_points
        rows.append(ProjectionEvaluationRow(
            name=projection.name,
            position=actual.position,
            projected=projection.projected_points,
            actual=actual.fantasy_points,
            error=error,
            absolute_error=abs(error),
            floor=projection.floor,
            ceiling=projection.ceiling,
            projected_ownership=projection.projected_ownership,
            actual_ownership=actual.drafted_percent,
            bust_probability=projection.bust_probability,
            confidence_score=projection.confidence_score,
            confidence_tier=projection.confidence_tier,
        ))
    return tuple(rows)


def _correlation(left, right):
    if len(left) < 2:
        return None
    left_mean, right_mean = sum(left) / len(left), sum(right) / len(right)
    numerator = sum((x - left_mean) * (y - right_mean) for x, y in zip(left, right, strict=True))
    denominator = math.sqrt(sum((x - left_mean) ** 2 for x in left) * sum((y - right_mean) ** 2 for y in right))
    return numerator / denominator if denominator else None


def _normalize(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())
