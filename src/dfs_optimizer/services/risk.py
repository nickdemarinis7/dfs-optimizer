from __future__ import annotations

from dfs_optimizer.models import Projection, Slate


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
