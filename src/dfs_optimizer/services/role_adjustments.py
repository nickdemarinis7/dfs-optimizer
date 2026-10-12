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
    pre-lock facts that a temporary starter may now sit behind a healthy player
    and that a replacement quarterback's relief appearances may understate a
    confirmed start. Skill-player penalties intentionally target only TE2+ and
    RB3/WR3+ roles.
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
    unavailable_qb1_by_team: dict[str, Projection] = {}
    for player in slate.players:
        context = context_by_id.get(player.platform_id)
        if context is None or context.depth_chart_position != 1:
            continue
        status = (context.injury_status or player.status or "").strip().upper()
        if context.active is not False and status not in unavailable:
            healthy_leaders.add((player.team, player.primary_position))
        elif player.primary_position == Position.QB:
            projection = projection_by_id.get(player.platform_id)
            if projection is not None:
                unavailable_qb1_by_team[player.team] = projection

    replacement_qb_ids: set[str] = set()
    for team in unavailable_qb1_by_team:
        candidates = []
        for player in slate.players:
            context = context_by_id.get(player.platform_id)
            status = (
                context.injury_status if context and context.injury_status else player.status
            )
            if (
                player.team == team
                and player.primary_position == Position.QB
                and context is not None
                and (context.depth_chart_position or 1) > 1
                and context.active is not False
                and (status or "").strip().upper() not in unavailable
                and player.platform_id in projection_by_id
            ):
                candidates.append(player)
        if candidates:
            replacement_qb_ids.add(min(
                candidates,
                key=lambda player: context_by_id[player.platform_id].depth_chart_position or 99,
            ).platform_id)

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
        if projection.platform_id in replacement_qb_ids:
            player = player_by_id[projection.platform_id]
            starter = unavailable_qb1_by_team[player.team]

            def promoted(current, starter_value):
                if starter_value is None:
                    return current
                target = starter_value * .70
                return target if current is None else max(current, target)

            target = max(projection.projected_points, starter.projected_points * .70)
            factor = target / projection.projected_points if projection.projected_points else 1.0
            bust = projection.bust_probability
            if starter.bust_probability is not None:
                replacement_bust = min(1.0, starter.bust_probability + .15)
                bust = replacement_bust if bust is None else max(bust, replacement_bust)
            updated = replace(
                projection,
                projected_points=target,
                floor=promoted(projection.floor, starter.floor),
                ceiling=promoted(projection.ceiling, starter.ceiling),
                p10=promoted(projection.p10, starter.p10),
                p25=promoted(projection.p25, starter.p25),
                p75=promoted(projection.p75, starter.p75),
                p90=promoted(projection.p90, starter.p90),
                bust_probability=bust,
            )
            adjusted.append(updated)
            audit.append(RoleAdjustment(
                platform_id=player.platform_id,
                player=player.name,
                team=player.team,
                position=player.primary_position.value,
                depth_order=context_by_id[player.platform_id].depth_chart_position or 2,
                factor=factor,
                original_projection=projection.projected_points,
                adjusted_projection=updated.projected_points,
                reason="replacement QB behind an unavailable QB1",
            ))
            continue
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
