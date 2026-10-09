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


def evaluate_projections(
    projections: tuple[Projection, ...], actuals: tuple[PlayerResult, ...]
) -> ProjectionMetrics:
    rows = evaluate_projection_rows(projections, actuals)
    if not rows:
        raise ValueError("no projections matched contest player results")
    errors = [row.error for row in rows]
    ranged = [row for row in rows if row.floor is not None and row.ceiling is not None]
    correlation = _correlation(
        [row.projected for row in rows], [row.actual for row in rows]
    )
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
    )


def evaluate_projection_rows(
    projections: tuple[Projection, ...], actuals: tuple[PlayerResult, ...]
) -> tuple[ProjectionEvaluationRow, ...]:
    actual_by_name: dict[str, list[PlayerResult]] = {}
    for item in actuals:
        actual_by_name.setdefault(_normalize(item.name), []).append(item)
    rows = []
    for projection in projections:
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
