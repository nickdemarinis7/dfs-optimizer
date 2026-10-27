from __future__ import annotations

from dataclasses import dataclass, replace

from dfs_optimizer.models import Position, Projection, Slate

from .weekly_context import PracticeTrajectory, TeamWeeklyContext


@dataclass(frozen=True, slots=True)
class WeeklyProjectionAdjustment:
    platform_id: str
    player: str
    factor: float
    reasons: tuple[str, ...]


def apply_weekly_projection_context(
    slate: Slate,
    projections: tuple[Projection, ...],
    contexts: tuple[TeamWeeklyContext, ...] = (),
    trajectories: tuple[PracticeTrajectory, ...] = (),
) -> tuple[tuple[Projection, ...], tuple[WeeklyProjectionAdjustment, ...]]:
    """Apply only calibrated-enough, hard weekly facts to projections.

    Live wind has a bounded effect on passing production. Practice history is
    attached as auditable confidence evidence; current injury/role services
    already handle its numeric risk, so it is not double-counted here.
    """
    players = {player.platform_id: player for player in slate.players}
    team_context = {item.team: item for item in contexts}
    trajectory_by_id = {item.platform_id: item for item in trajectories}
    output = []
    adjustments = []
    for projection in projections:
        player_id = projection.platform_id or ""
        player = players.get(player_id)
        if player is None:
            output.append(projection)
            continue
        weekly = team_context.get(player.team)
        trajectory = trajectory_by_id.get(player_id)
        factor = 1.0
        reasons = list(projection.confidence_reasons)
        adjustment_reasons = []
        if weekly and weekly.weather_source and weekly.wind_mph is not None:
            wind = weekly.wind_mph
            if player.primary_position in {Position.QB, Position.WR, Position.TE}:
                factor = .90 if wind >= 25 else .95 if wind >= 20 else .98 if wind >= 16 else 1.0
            elif player.primary_position == Position.K and wind >= 20:
                factor = .97
            if factor < 1:
                message = f"live kickoff wind {wind:.0f} mph"
                reasons.append(message)
                adjustment_reasons.append(message)
        if trajectory and len(trajectory.observations) >= 2:
            if trajectory.improving:
                reasons.append("practice participation improved during week")
            elif trajectory.latest in {"DNP", "LP", "OUT", "DOUBTFUL"}:
                reasons.append("practice participation did not fully recover")

        if factor < 1:
            def scaled(value):
                return value * factor if value is not None else None

            bust = projection.bust_probability
            if bust is not None:
                bust = min(1.0, bust + (1.0 - factor))
            projection = replace(
                projection,
                projected_points=projection.projected_points * factor,
                floor=scaled(projection.floor),
                ceiling=scaled(projection.ceiling),
                p10=scaled(projection.p10),
                p25=scaled(projection.p25),
                p75=scaled(projection.p75),
                p90=scaled(projection.p90),
                bust_probability=bust,
            )
            adjustments.append(WeeklyProjectionAdjustment(
                player_id, player.name, factor, tuple(adjustment_reasons)
            ))
        output.append(replace(
            projection,
            confidence_reasons=tuple(dict.fromkeys(reasons)),
        ))
    return tuple(output), tuple(adjustments)
