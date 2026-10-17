from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
import math

from dfs_optimizer.models import ContestFormat, Position, Projection, Slate, Sport
from dfs_optimizer.rules import single_game_rules_for


NFL_SHOWDOWN_OWNERSHIP_MODEL_VERSION = "nfl-showdown-v1"


def estimate_nfl_showdown_ownership(
    slate: Slate,
    projections: tuple[Projection, ...],
) -> tuple[Projection, ...]:
    """Estimate any-roster-slot ownership when no external forecast exists.

    The estimate is deliberately slate-relative and conservative. It ranks
    projection, value, salary, upper range, and position strength, then scales
    ownership to the exact number of roster slots filled by the field. This is
    a duplication-risk proxy, not reported or sportsbook-derived ownership.
    Existing uploaded ownership values are never overwritten.
    """
    if (
        slate.sport != Sport.NFL
        or slate.contest_format != ContestFormat.SINGLE_GAME
    ):
        return projections

    players = {
        player.platform_id: player
        for player in slate.players
        if player.platform_id
    }
    eligible = tuple(
        projection for projection in projections
        if projection.platform_id in players and projection.projected_points > 0
    )
    if not eligible or any(item.projected_ownership is not None for item in eligible):
        return projections

    points = _percentile_ranks({
        item.platform_id: item.projected_points for item in eligible
    })
    values = _percentile_ranks({
        item.platform_id: item.projected_points
        / max(1, players[item.platform_id].salary / 1000)
        for item in eligible
    })
    salaries = _percentile_ranks({
        item.platform_id: float(players[item.platform_id].salary)
        for item in eligible
    })
    ceilings = _percentile_ranks({
        item.platform_id: item.p90 or item.ceiling or item.projected_points
        for item in eligible
    })
    position_scores: dict[str, float] = {}
    by_position: dict[Position, dict[str, float]] = defaultdict(dict)
    for item in eligible:
        player = players[item.platform_id]
        by_position[player.primary_position][item.platform_id] = item.projected_points
    for position_values in by_position.values():
        position_scores.update(_percentile_ranks(position_values))

    weights = {
        item.platform_id: math.exp(
            1.65 * points[item.platform_id]
            + 1.20 * values[item.platform_id]
            + .35 * salaries[item.platform_id]
            + .70 * ceilings[item.platform_id]
            + .35 * position_scores[item.platform_id]
        )
        for item in eligible
    }
    roster_slots = single_game_rules_for(slate.platform).lineup_size
    ownership = _scale_with_cap(weights, roster_slots * 100.0, cap=85.0)
    return tuple(
        replace(
            item,
            projected_ownership=round(ownership.get(item.platform_id, 0.0), 2),
        )
        for item in projections
    )


def _percentile_ranks(values: dict[str, float]) -> dict[str, float]:
    ordered = sorted(values.items(), key=lambda item: (item[1], item[0]))
    denominator = max(1, len(ordered) - 1)
    return {
        key: index / denominator
        for index, (key, _) in enumerate(ordered)
    }


def _scale_with_cap(
    weights: dict[str, float], target: float, *, cap: float
) -> dict[str, float]:
    remaining = set(weights)
    result: dict[str, float] = {}
    remaining_target = min(target, cap * len(weights))
    while remaining:
        total_weight = sum(weights[key] for key in remaining)
        if total_weight <= 0:
            equal = remaining_target / len(remaining)
            result.update({key: equal for key in remaining})
            break
        newly_capped = {
            key for key in remaining
            if remaining_target * weights[key] / total_weight >= cap
        }
        if not newly_capped:
            result.update({
                key: remaining_target * weights[key] / total_weight
                for key in remaining
            })
            break
        for key in newly_capped:
            result[key] = cap
            remaining_target -= cap
        remaining -= newly_capped
    return result
