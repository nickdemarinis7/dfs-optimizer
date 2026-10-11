from __future__ import annotations

from dataclasses import dataclass, replace

from dfs_optimizer.models import Position, Projection, Slate, Sport

from .player_context import PlayerContext


@dataclass(frozen=True, slots=True)
class RoleAdjustment:
    platform_id: str
    player: str
    team: str
    position: str
    depth_order: int
    factor: float
    original_projection: float
    adjusted_projection: float
    reason: str


def apply_current_role_adjustments(
    slate: Slate,
    projections: tuple[Projection, ...],
    contexts: tuple[PlayerContext, ...],
) -> tuple[tuple[Projection, ...], tuple[RoleAdjustment, ...]]:
    """Apply conservative depth-chart penalties behind healthy starters.

    Historical usage remains the primary projection. This layer handles the
    pre-lock fact that a temporary starter may now sit behind a healthy player.
    It intentionally targets only TE2+ and RB3/WR3+ roles.
    """
    if slate.sport != Sport.NFL or not contexts:
        return projections, ()
    context_by_id = {item.platform_id: item for item in contexts}
    projection_by_id = {
        item.platform_id: item for item in projections if item.platform_id
    }
    player_by_id = {item.platform_id: item for item in slate.players}
    unavailable = {"IR", "O", "OUT", "INACTIVE", "INJURED RESERVE"}
    healthy_leaders: set[tuple[str, Position]] = set()
    for player in slate.players:
        context = context_by_id.get(player.platform_id)
        if context is None or context.depth_chart_position != 1:
            continue
        status = (context.injury_status or player.status or "").strip().upper()
        if context.active is not False and status not in unavailable:
            healthy_leaders.add((player.team, player.primary_position))

    factors: dict[str, tuple[float, str, int]] = {}
    for player in slate.players:
        context = context_by_id.get(player.platform_id)
        projection = projection_by_id.get(player.platform_id)
        if context is None or projection is None:
            continue
        depth = context.depth_chart_position or 0
        if (player.team, player.primary_position) not in healthy_leaders:
            continue
        if player.primary_position == Position.TE and depth >= 2:
            factors[player.platform_id] = (
                .65,
                "TE2 or deeper behind an active TE1",
                depth,
            )
        elif player.primary_position in {Position.RB, Position.WR} and depth >= 3:
            factors[player.platform_id] = (
                .75,
                f"{player.primary_position.value}{depth} behind an active starter",
                depth,
            )

    adjusted: list[Projection] = []
    audit: list[RoleAdjustment] = []
    for projection in projections:
        detail = factors.get(projection.platform_id or "")
        if detail is None:
            adjusted.append(projection)
            continue
        factor, reason, depth = detail
        scale = lambda value: value * factor if value is not None else None
        bust = projection.bust_probability
        if bust is not None:
            bust = min(1.0, 1 - (1 - bust) * factor)
        updated = replace(
            projection,
            projected_points=projection.projected_points * factor,
            floor=scale(projection.floor),
            ceiling=scale(projection.ceiling),
            p10=scale(projection.p10),
            p25=scale(projection.p25),
            p75=scale(projection.p75),
            p90=scale(projection.p90),
            bust_probability=bust,
        )
        adjusted.append(updated)
        player = player_by_id[projection.platform_id]
        audit.append(RoleAdjustment(
            platform_id=player.platform_id,
            player=player.name,
            team=player.team,
            position=player.primary_position.value,
            depth_order=depth,
            factor=factor,
            original_projection=projection.projected_points,
            adjusted_projection=updated.projected_points,
            reason=reason,
        ))
    return tuple(adjusted), tuple(audit)
