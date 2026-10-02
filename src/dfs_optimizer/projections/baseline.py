from __future__ import annotations

from dfs_optimizer.models import Projection, Slate


UNAVAILABLE_STATUSES = frozenset({"IR", "O", "OUT"})


def build_platform_average_projections(slate: Slate) -> tuple[Projection, ...]:
    """Create a simple baseline from each platform's historical fantasy average.

    This is useful for proving the complete optimization pipeline. It is not a
    forward-looking projection model and should not be treated as one.
    """
    projections: list[Projection] = []
    for player in slate.players:
        status = (player.status or "").strip().upper()
        if status in UNAVAILABLE_STATUSES or player.platform_average is None:
            continue
        projections.append(
            Projection(
                name=player.name,
                team=player.team,
                projected_points=max(0.0, player.platform_average),
                platform_id=player.platform_id,
            )
        )
    return tuple(projections)

