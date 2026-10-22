from __future__ import annotations

from dataclasses import dataclass, replace

from dfs_optimizer.models import Player, Position, Projection, Slate, Sport

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
    """Apply evidence-backed role changes behind healthy starters.

    Historical usage remains the primary projection. This layer handles the
    pre-lock facts that a temporary starter may now sit behind a healthy player
    and that a replacement quarterback's relief appearances may understate a
    confirmed start. Depth order alone is too noisy to lower a skill player's
    median: multi-TE packages, slot receivers, and committee backs can all be
    productive below the first row of a depth chart. A TE2+, RB3+, or WR4+
    median is reduced only when recent opportunity or snap evidence also shows
    a material role decline. The risk layer may still flag and cap exposure to
    a deep player whose median is left unchanged here.

    A structured pre-lock role report takes precedence over nominal depth
    order. The adjustment remains bounded: expanded workload raises the
    distribution 25%, committee usage lowers it 15%, and a clearly limited
    role lowers it 40%. ``normal`` suppresses a stale chart penalty without
    changing the projection.

    Finally, a healthy QB/RB/WR/TE listed first on the current depth chart is
    protected from an extreme historical-data collapse. When that player's
    median falls below 50% of the platform's slate average, the distribution
    is scaled to a conservative 60% floor. Questionable, limited, and
    committee players are deliberately excluded from this safeguard.

    When a higher-usage RB, WR, or TE is unavailable, the first healthy reserve
    is instead given a modest 10% promotion above the stronger of his current
    forecast and platform average. A player's old per-game history is a poor
    median after a material promotion; this bounded uplift recognizes the new
    opportunity without assigning all of the missing starter's production to
    one replacement.
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

    # An unavailable lead skill player can make a modest historical sample
    # misleading. Depth feeds sometimes omit the unavailable player entirely,
    # so also use the salary file's status and platform average to identify the
    # higher-usage player. Only the first healthy reserve is raised, and only to
    # his own platform average. This remains below automatically inheriting all
    # of the unavailable starter's production.
    replacement_skill_ids: set[str] = set()
    unavailable_skills: dict[tuple[str, Position], list[Player]] = {}
    for player in slate.players:
        context = context_by_id.get(player.platform_id)
        status = (
            context.injury_status if context and context.injury_status else player.status
        )
        if (
            player.primary_position in {Position.RB, Position.WR, Position.TE}
            and (status or "").strip().upper() in unavailable
        ):
            unavailable_skills.setdefault(
                (player.team, player.primary_position), []
            ).append(player)
    minimum_platform_average = {
        Position.RB: 5.0,
        Position.WR: 4.0,
        Position.TE: 3.0,
    }
    for (team, position), unavailable_players in unavailable_skills.items():
        candidates = []
        for player in slate.players:
            context = context_by_id.get(player.platform_id)
            status = (
                context.injury_status if context and context.injury_status else player.status
            )
            expected_role = (
                (context.expected_role or "").strip().casefold() if context else ""
            )
            if (
                player.team == team
                and player.primary_position == position
                and context is not None
                and (context.depth_chart_position or 1) > 1
                and context.active is not False
                and (status or "").strip().upper() not in unavailable
                and not expected_role
                and (player.platform_average or 0)
                >= minimum_platform_average[position]
                and player.platform_id in projection_by_id
                and any(
                    (unavailable_player.platform_average or 0)
                    > (player.platform_average or 0)
                    for unavailable_player in unavailable_players
                )
            ):
                candidates.append(player)
        if candidates:
            replacement_skill_ids.add(min(
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
        expected_role = (context.expected_role or "").strip().casefold()
        if expected_role:
            role_factors = {
                "expanded": 1.25,
                "normal": 1.0,
                "committee": .85,
                "limited": .60,
            }
            factor = role_factors[expected_role]
            note = f": {context.role_note}" if context.role_note else ""
            factors[player.platform_id] = (
                factor,
                f"confirmed pre-lock {expected_role} role{note}",
                depth,
            )
            continue
        if (player.team, player.primary_position) not in healthy_leaders:
            continue
        deep_skill_role = player.primary_position == Position.TE and depth >= 2
        deep_skill_role = deep_skill_role or (
            player.primary_position == Position.RB and depth >= 3
            or player.primary_position == Position.WR and depth >= 4
        )
        stability = projection.opportunity_stability
        if deep_skill_role and stability is not None and stability < .60:
            factor = .75 if stability < .35 else .85
            factors[player.platform_id] = (
                factor,
                (
                    f"{player.primary_position.value}{depth} behind an active starter "
                    f"with confirmed recent opportunity decline ({stability:.0%} retained)"
                ),
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
        if projection.platform_id in replacement_skill_ids:
            player = player_by_id[projection.platform_id]
            promoted_baseline = max(
                projection.projected_points,
                player.platform_average or 0,
            )
            target = promoted_baseline * 1.10
            factor = target / projection.projected_points
            scale = lambda value: value * factor if value is not None else None
            updated = replace(
                projection,
                projected_points=target,
                floor=scale(projection.floor),
                ceiling=scale(projection.ceiling),
                p10=scale(projection.p10),
                p25=scale(projection.p25),
                p75=scale(projection.p75),
                p90=scale(projection.p90),
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
                reason=(
                    f"next healthy {player.primary_position.value} behind a "
                    "higher-usage unavailable player; bounded opportunity uplift"
                ),
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
    guarded: list[Projection] = []
    uncertain = {"Q", "QUESTIONABLE", "D", "DOUBTFUL"}
    guardrail_positions = {Position.QB, Position.RB, Position.WR, Position.TE}
    for projection in adjusted:
        platform_id = projection.platform_id or ""
        player = player_by_id.get(platform_id)
        context = context_by_id.get(platform_id)
        if player is None or context is None:
            guarded.append(projection)
            continue
        status = (context.injury_status or player.status or "").strip().upper()
        expected_role = (context.expected_role or "").strip().casefold()
        platform_average = player.platform_average or 0.0
        minimum_starter_average = 5.0 if player.primary_position == Position.RB else 0.0
        eligible = (
            player.primary_position in guardrail_positions
            and context.depth_chart_position == 1
            and context.active is not False
            and status not in unavailable | uncertain
            and expected_role not in {"committee", "limited"}
            and platform_average >= minimum_starter_average
            and platform_average > 0
            and projection.projected_points > 0
        )
        trigger = platform_average * .50
        if not eligible or projection.projected_points >= trigger:
            guarded.append(projection)
            continue

        target = platform_average * .60
        factor = target / projection.projected_points
        scale = lambda value: value * factor if value is not None else None
        updated = replace(
            projection,
            projected_points=target,
            floor=scale(projection.floor),
            ceiling=scale(projection.ceiling),
            p10=scale(projection.p10),
            p25=scale(projection.p25),
            p75=scale(projection.p75),
            p90=scale(projection.p90),
        )
        guarded.append(updated)
        audit.append(RoleAdjustment(
            platform_id=player.platform_id,
            player=player.name,
            team=player.team,
            position=player.primary_position.value,
            depth_order=1,
            factor=factor,
            original_projection=projection.projected_points,
            adjusted_projection=updated.projected_points,
            reason=(
                "healthy depth-chart starter guardrail: projection was below "
                "50% of the platform slate average"
            ),
        ))
    return tuple(guarded), tuple(audit)
