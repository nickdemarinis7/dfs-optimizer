from __future__ import annotations

from dataclasses import dataclass, replace
import re
import unicodedata

from dfs_optimizer.data_sources.nfl_props import NFLPropConsensus
from dfs_optimizer.models import Platform, Position, Projection, Slate


@dataclass(frozen=True, slots=True)
class NFLPropAdjustment:
    """Audit record for a deliberately bounded market-based uplift."""

    platform_id: str
    player: str
    implied_points: float
    original_projection: float
    adjusted_projection: float
    markets: tuple[str, ...]


def apply_nfl_prop_role_signals(
    slate: Slate,
    projections: tuple[Projection, ...],
    props: tuple[NFLPropConsensus, ...],
) -> tuple[tuple[Projection, ...], int]:
    """Attach market role evidence without treating betting lines as truth."""
    adjusted, matched, _ = apply_nfl_prop_projection_signals(slate, projections, props)
    return adjusted, matched


def apply_nfl_prop_projection_signals(
    slate: Slate,
    projections: tuple[Projection, ...],
    props: tuple[NFLPropConsensus, ...],
) -> tuple[tuple[Projection, ...], int, tuple[NFLPropAdjustment, ...]]:
    """Attach role evidence and apply only well-supported, capped prop uplifts.

    Prop-derived fantasy points omit touchdowns and several position-specific
    scoring paths, so they are never used to lower a projection. An uplift
    requires both volume and yardage markets and is capped at 20 percent.
    """
    props_by_name = {_normalize(item.player): item for item in props}
    players = {player.platform_id: player for player in slate.players}
    matched = 0
    output = []
    adjustments = []
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
        updated = replace(
            projection, prop_market_count=count, prop_coverage_checked=checked,
        )
        implied_points = _implied_non_touchdown_points(slate, player, signal)
        if implied_points is not None and implied_points > projection.projected_points:
            target = min(
                projection.projected_points * 1.20,
                projection.projected_points
                + .50 * (implied_points - projection.projected_points),
            )
            factor = target / projection.projected_points
            updated = replace(
                updated,
                projected_points=target,
                floor=_scaled(projection.floor, factor),
                p10=_scaled(projection.p10, factor),
                p25=_scaled(projection.p25, factor),
                p75=_scaled(projection.p75, factor),
                p90=_scaled(projection.p90, factor),
                ceiling=_market_supported_ceiling(
                    projection.ceiling, factor, implied_points
                ),
            )
            adjustments.append(NFLPropAdjustment(
                platform_id=projection.platform_id or "",
                player=projection.name,
                implied_points=implied_points,
                original_projection=projection.projected_points,
                adjusted_projection=target,
                markets=tuple(key for key, _ in signal.markets),
            ))
        output.append(updated)
    return tuple(output), matched, tuple(adjustments)


def _implied_non_touchdown_points(slate, player, signal) -> float | None:
    if player is None or signal is None:
        return None
    markets = dict(signal.markets)
    if player.primary_position == Position.QB:
        yards = markets.get("player_pass_yds")
        touchdowns = markets.get("player_pass_tds")
        if yards is None or touchdowns is None:
            return None
        return yards / 25 + touchdowns * 4
    yards = markets.get("player_rush_reception_yds")
    receptions = markets.get("player_receptions")
    if yards is None or receptions is None:
        return None
    ppr = 1.0 if slate.platform == Platform.DRAFTKINGS else .5
    return yards / 10 + receptions * ppr


def _scaled(value: float | None, factor: float) -> float | None:
    return None if value is None else value * factor


def _market_supported_ceiling(
    ceiling: float | None, factor: float, implied_points: float
) -> float | None:
    if ceiling is None:
        return None
    return max(ceiling * factor, min(ceiling * 1.25, implied_points * 1.8))


def _normalize(value: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", ascii_name.casefold())
