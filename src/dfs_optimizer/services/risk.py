from __future__ import annotations

from dfs_optimizer.models import Position, Projection, Slate


UNAVAILABLE_STATUSES = frozenset({"IR", "O", "OUT"})


def suggest_default_excluded_player_ids(
    slate: Slate,
    projections: tuple[Projection, ...],
) -> frozenset[str]:
    """Suggest players who should not enter a lineup without an override.

    Definitively unavailable players are always suggested. A quarterback is
    also suggested when another available QB on the same team has both a
    materially stronger projection and salary signal. This prevents prior
    spot-start production from making a current backup look like cheap value.
    """
    by_id = {
        projection.platform_id: projection
        for projection in projections
        if projection.platform_id
    }
    unavailable = {
        player.platform_id
        for player in slate.players
        if (player.status or "").strip().upper() in UNAVAILABLE_STATUSES
    }
    quarterbacks_by_team: dict[str, list] = {}
    for player in slate.players:
        if (
            player.primary_position == Position.QB
            and player.platform_id in by_id
            and player.platform_id not in unavailable
        ):
            quarterbacks_by_team.setdefault(player.team, []).append(player)

    backups: set[str] = set()
    for quarterbacks in quarterbacks_by_team.values():
        if len(quarterbacks) < 2:
            continue
        starter = max(
            quarterbacks,
            key=lambda player: (
                by_id[player.platform_id].projected_points,
                player.salary,
            ),
        )
        starter_projection = by_id[starter.platform_id].projected_points
        if starter_projection < 8:
            continue
        for quarterback in quarterbacks:
            if quarterback.platform_id == starter.platform_id:
                continue
            projection_ratio = (
                by_id[quarterback.platform_id].projected_points / starter_projection
            )
            salary_ratio = quarterback.salary / starter.salary
            if projection_ratio < .65 and salary_ratio < .80:
                backups.add(quarterback.platform_id)

    return frozenset(unavailable | backups)


def suggest_max_once_player_ids(
    slate: Slate,
    projections: tuple[Projection, ...],
) -> frozenset[str]:
    """Identify fragile values that should not become a multi-lineup core.

    This is deliberately conservative: a player is suggested only when a
    historical floor near zero is paired with a usable but sub-10-point median.
    Projections without floor evidence remain visible signals but are not
    automatically constrained. Users can remove any suggestion in the builder.
    """
    by_id = {
        projection.platform_id: projection
        for projection in projections
        if projection.platform_id
    }
    return frozenset(
        player.platform_id
        for player in slate.players
        if (projection := by_id.get(player.platform_id)) is not None
        and projection.floor is not None
        and projection.floor <= 1
        and 2 <= projection.projected_points < 10
    )
