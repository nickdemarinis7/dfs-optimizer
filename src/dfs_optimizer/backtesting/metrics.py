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


def evaluate_projections(
    projections: tuple[Projection, ...], actuals: tuple[PlayerResult, ...]
) -> ProjectionMetrics:
    actual_by_key = {(_normalize(item.name), item.position): item for item in actuals}
    pairs = []
    for projection in projections:
        candidates = [item for (name, _), item in actual_by_key.items() if name == _normalize(projection.name)]
        if len(candidates) == 1:
            pairs.append((projection.projected_points, candidates[0].fantasy_points))
    if not pairs:
        raise ValueError("no projections matched contest player results")
    errors = [projected - actual for projected, actual in pairs]
    correlation = _correlation([pair[0] for pair in pairs], [pair[1] for pair in pairs])
    return ProjectionMetrics(
        matched_players=len(pairs),
        mean_absolute_error=sum(abs(error) for error in errors) / len(errors),
        root_mean_squared_error=math.sqrt(sum(error * error for error in errors) / len(errors)),
        mean_error=sum(errors) / len(errors),
        correlation=correlation,
    )


def _correlation(left, right):
    if len(left) < 2:
        return None
    left_mean, right_mean = sum(left) / len(left), sum(right) / len(right)
    numerator = sum((x - left_mean) * (y - right_mean) for x, y in zip(left, right, strict=True))
    denominator = math.sqrt(sum((x - left_mean) ** 2 for x in left) * sum((y - right_mean) ** 2 for y in right))
    return numerator / denominator if denominator else None


def _normalize(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())

