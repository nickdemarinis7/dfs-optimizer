from __future__ import annotations

import csv
from dataclasses import replace
from pathlib import Path

from dfs_optimizer.importers import PlayerStatProjection, TeamDefenseProjection
from dfs_optimizer.models import Position, Slate


def apply_pregame_context(
    slate: Slate,
    offense: tuple[PlayerStatProjection, ...],
    defenses: tuple[TeamDefenseProjection, ...],
    team_files: tuple[str | Path, ...],
    games_file: str | Path,
    target_season: int,
    target_week: int,
) -> tuple[tuple[PlayerStatProjection, ...], tuple[TeamDefenseProjection, ...]]:
    """Apply bounded matchup, market, game-script, and weather adjustments."""
    team_rows = _rows(team_files)
    games = _rows((games_file,))
    target_games = {
        team: game
        for game in games
        if int(game.get("season") or 0) == target_season
        and int(game.get("week") or 0) == target_week
        for team in (game["home_team"], game["away_team"])
    }
    eligible = [
        row for row in team_rows
        if row.get("season_type") == "REG"
        and (int(row["season"]), int(row["week"])) < (target_season, target_week)
    ]
    league_pass = _ratio_sum(eligible, "passing_yards", "attempts", 7.0)
    league_rush = _ratio_sum(eligible, "rushing_yards", "carries", 4.2)
    defense_rates = {}
    for opponent in {row.get("opponent_team") for row in eligible}:
        against = [row for row in eligible if row.get("opponent_team") == opponent]
        defense_rates[opponent] = (
            _ratio_sum(against, "passing_yards", "attempts", league_pass),
            _ratio_sum(against, "rushing_yards", "carries", league_rush),
        )

    adjusted = []
    player_by_name = {(item.name, item.team): item for item in offense}
    for player in slate.players:
        item = player_by_name.get((player.name, player.team))
        if item is None:
            continue
        if player.primary_position == Position.K:
            adjusted.append(item)
            continue
        game = target_games.get(player.team)
        if game is None:
            adjusted.append(item)
            continue
        opponent = game["away_team"] if player.team == game["home_team"] else game["home_team"]
        pass_rate, rush_rate = defense_rates.get(opponent, (league_pass, league_rush))
        pass_matchup = _bound(pass_rate / league_pass, 0.85, 1.15)
        rush_matchup = _bound(rush_rate / league_rush, 0.85, 1.15)
        implied, spread = _implied_points(game, player.team)
        market = _bound(implied / 22.5, 0.80, 1.20) if implied else 1.0
        pass_script = _bound(1 - spread * 0.006, 0.92, 1.08)
        rush_script = _bound(1 + spread * 0.008, 0.90, 1.10)
        wind = _number(game.get("wind"))
        outdoors = (game.get("roof") or "").lower() in {"outdoors", "open"}
        wind_factor = _bound(1 - max(0, wind - 14) * 0.012, 0.82, 1.0) if outdoors else 1.0
        stats = item.stats
        adjusted.append(replace(item, stats=replace(
            stats,
            passing_yards=stats.passing_yards * pass_matchup * pass_script * wind_factor,
            passing_touchdowns=stats.passing_touchdowns * market * pass_script * wind_factor,
            interceptions_thrown=stats.interceptions_thrown * _bound(2 - pass_matchup, .85, 1.15),
            rushing_yards=stats.rushing_yards * rush_matchup * rush_script,
            rushing_touchdowns=stats.rushing_touchdowns * market * rush_script,
            receiving_yards=stats.receiving_yards * pass_matchup * pass_script * wind_factor,
            receiving_touchdowns=stats.receiving_touchdowns * market * pass_script * wind_factor,
            passing_bonus_probability=_bound(stats.passing_bonus_probability * pass_matchup * wind_factor, 0, 1),
            rushing_bonus_probability=_bound(stats.rushing_bonus_probability * rush_matchup, 0, 1),
            receiving_bonus_probability=_bound(stats.receiving_bonus_probability * pass_matchup * wind_factor, 0, 1),
        )))
    return tuple(adjusted), defenses


def _implied_points(game, team):
    total, home_edge = _number(game.get("total_line")), _number(game.get("spread_line"))
    if not total:
        return 0.0, 0.0
    is_home = team == game["home_team"]
    implied = total / 2 + home_edge / 2 if is_home else total / 2 - home_edge / 2
    team_spread = home_edge if is_home else -home_edge
    return implied, team_spread


def _ratio_sum(rows, numerator, denominator, fallback):
    top = sum(_number(row.get(numerator)) for row in rows)
    bottom = sum(_number(row.get(denominator)) for row in rows)
    return top / bottom if bottom else fallback


def _rows(paths):
    result = []
    for path in paths:
        with Path(path).open(encoding="utf-8-sig", newline="") as handle:
            result.extend(csv.DictReader(handle))
    return result


def _number(value):
    return float(value) if value not in (None, "") else 0.0


def _bound(value, low, high):
    return max(low, min(high, value))
