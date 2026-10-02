from __future__ import annotations

import re
import unicodedata

from dfs_optimizer.importers import PlayerStatProjection, TeamDefenseProjection
from dfs_optimizer.models import Position, Projection, Slate
from dfs_optimizer.rules import nfl_scoring_for

from .baseline import UNAVAILABLE_STATUSES


def build_stat_based_projections(
    slate: Slate,
    stat_projections: tuple[PlayerStatProjection, ...],
    defense_projections: tuple[TeamDefenseProjection, ...] = (),
) -> tuple[Projection, ...]:
    """Score platform-neutral offensive forecasts for one salary slate."""
    forecasts = {
        (_normalize(item.name), item.team): item for item in stat_projections
    }
    scoring = nfl_scoring_for(slate.platform)
    defenses = {item.team: item for item in defense_projections}
    results: list[Projection] = []
    for player in slate.players:
        if (player.status or "").strip().upper() in UNAVAILABLE_STATUSES:
            continue
        if player.primary_position == Position.DST:
            defense = defenses.get(player.team)
            if defense is None:
                continue
            points = scoring.project_defense(defense.stats)
        else:
            forecast = forecasts.get((_normalize(player.name), player.team))
            if forecast is None:
                continue
            points = (
                scoring.project_kicker(forecast.stats)
                if player.primary_position == Position.K
                else scoring.project_offense(forecast.stats)
            )
        results.append(
            Projection(
                name=player.name,
                team=player.team,
                platform_id=player.platform_id,
                projected_points=points,
            )
        )
    return tuple(results)


def _normalize(value: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    parts = re.findall(r"[a-z0-9]+", ascii_name.lower())
    if parts and parts[-1] in {"jr", "sr", "ii", "iii", "iv", "v"}:
        parts.pop()
    return "".join(parts)
