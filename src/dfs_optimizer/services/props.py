from __future__ import annotations

from dataclasses import replace
import re
import unicodedata

from dfs_optimizer.data_sources.nfl_props import NFLPropConsensus
from dfs_optimizer.models import Position, Projection, Slate


def apply_nfl_prop_role_signals(
    slate: Slate,
    projections: tuple[Projection, ...],
    props: tuple[NFLPropConsensus, ...],
) -> tuple[tuple[Projection, ...], int]:
    """Attach market role evidence without treating betting lines as truth."""
    props_by_name = {_normalize(item.player): item for item in props}
    players = {player.platform_id: player for player in slate.players}
    matched = 0
    output = []
    matched_by_game: dict[str, int] = {}
    prop_for_projection: dict[str, NFLPropConsensus] = {}
    for projection in projections:
        signal = props_by_name.get(_normalize(projection.name))
        player = players.get(projection.platform_id or "")
        if signal is not None and player is not None:
            prop_for_projection[projection.platform_id or ""] = signal
            matched_by_game[player.game] = matched_by_game.get(player.game, 0) + 1
    covered_games = {game for game, count in matched_by_game.items() if count >= 5}
    for projection in projections:
        player = players.get(projection.platform_id or "")
        signal = prop_for_projection.get(projection.platform_id or "")
        count = len(signal.markets) if signal else 0
        checked = bool(player and player.game in covered_games)
        if signal:
            matched += 1
        output.append(replace(
            projection,
            prop_market_count=count,
            prop_coverage_checked=checked,
        ))
    return tuple(output), matched


def _normalize(value: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", ascii_name.casefold())
