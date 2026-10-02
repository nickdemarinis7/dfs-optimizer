from __future__ import annotations

import csv
import math
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

from dfs_optimizer.importers import PlayerStatProjection, TeamDefenseProjection
from dfs_optimizer.models import Position, ProjectedDefenseStats, ProjectedKickerStats, ProjectedOffensiveStats, Slate


def forecast_from_nflverse(
    slate: Slate,
    player_files: tuple[str | Path, ...],
    team_files: tuple[str | Path, ...],
    games_file: str | Path,
    target_season: int,
    target_week: int,
    games_used: int = 8,
    half_life_games: float = 4,
) -> tuple[tuple[PlayerStatProjection, ...], tuple[TeamDefenseProjection, ...]]:
    player_rows = _read_rows(player_files)
    team_rows = _read_rows(team_files)
    game_rows = _read_rows((games_file,))
    offense = _forecast_players(
        slate, player_rows, team_rows, target_season, target_week, games_used, half_life_games
    )
    defenses = _forecast_defenses(
        slate, team_rows, game_rows, target_season, target_week, games_used, half_life_games
    )
    return offense, defenses


def _forecast_players(slate, rows, team_rows, season, week, games_used, half_life):
    history = defaultdict(list)
    eligible_rows = []
    for row in rows:
        if row.get("season_type") != "REG" or not _before(row, season, week):
            continue
        history[_normalize(row.get("player_display_name", ""))].append(row)
        eligible_rows.append(row)
    position_rates = _position_efficiency_rates(eligible_rows)
    current_team_weeks = defaultdict(set)
    for row in team_rows:
        if row.get("season_type") == "REG" and int(row["season"]) == season and _before(row, season, week):
            current_team_weeks[row["team"]].add((int(row["season"]), int(row["week"])))
    forecasts = []
    for player in slate.players:
        if player.primary_position == Position.DST:
            continue
        player_history = history.get(_normalize(player.name), [])
        if not player_history:
            # Team-week padding represents games in which a known player had no
            # usage. It must not manufacture a zero forecast for an unmatched name.
            continue
        by_game = {(int(row["season"]), int(row["week"])): row for row in player_history}
        # A current-team game with no box-score usage is real evidence of a zero role.
        for game_key in current_team_weeks.get(player.team, set()):
            by_game.setdefault(game_key, {"season": str(game_key[0]), "week": str(game_key[1])})
        current_games = [
            by_game[game_key]
            for game_key in sorted(current_team_weeks.get(player.team, set()), reverse=True)[:3]
        ]
        if (
            len(current_games) >= 2
            and player.platform_average is not None
            and player.platform_average <= 2
            and sum(_opportunities(player.primary_position, row) for row in current_games)
            / len(current_games) < 2
        ):
            # Do not let a previous starter role create a current-week projection
            # when both recent usage and the platform's slate average indicate a backup.
            continue
        games = sorted(
            by_game.values(),
            key=lambda row: (int(row["season"]), int(row["week"])),
            reverse=True,
        )[:games_used]
        if not games:
            continue
        weights = _weights(len(games), half_life)
        avg = lambda column: _weighted(games, weights, lambda row: _float(row, column))
        if player.primary_position == Position.K:
            forecasts.append(PlayerStatProjection(player.name, player.team, ProjectedKickerStats(
                field_goals_0_to_39=avg("fg_made_0_19") + avg("fg_made_20_29") + avg("fg_made_30_39"),
                field_goals_40_to_49=avg("fg_made_40_49"),
                field_goals_50_plus=avg("fg_made_50_59") + avg("fg_made_60_"),
                extra_points=avg("pat_made"),
            )))
            continue
        rates = position_rates.get(player.primary_position.value, position_rates["ALL"])
        attempts, carries, targets = avg("attempts"), avg("carries"), avg("targets")
        role_trend = _role_trend_factor(player.primary_position, current_games)
        attempts *= role_trend
        carries *= role_trend
        targets *= role_trend
        pass_ypa = _shrunk_rate(games, weights, "passing_yards", "attempts", rates["pass_ypa"], 100)
        pass_td_rate = _shrunk_rate(games, weights, "passing_tds", "attempts", rates["pass_td_rate"], 100)
        interception_rate = _shrunk_rate(games, weights, "passing_interceptions", "attempts", rates["interception_rate"], 100)
        rush_ypc = _shrunk_rate(games, weights, "rushing_yards", "carries", rates["rush_ypc"], 30)
        rush_td_rate = _shrunk_rate(games, weights, "rushing_tds", "carries", rates["rush_td_rate"], 30)
        catch_rate = _shrunk_rate(games, weights, "receptions", "targets", rates["catch_rate"], 30)
        receiving_ypt = _shrunk_rate(games, weights, "receiving_yards", "targets", rates["receiving_ypt"], 30)
        receiving_td_rate = _shrunk_rate(games, weights, "receiving_tds", "targets", rates["receiving_td_rate"], 30)
        forecasts.append(PlayerStatProjection(player.name, player.team, ProjectedOffensiveStats(
            passing_yards=attempts * pass_ypa, passing_touchdowns=attempts * pass_td_rate,
            interceptions_thrown=attempts * interception_rate, rushing_yards=carries * rush_ypc,
            rushing_touchdowns=carries * rush_td_rate, receptions=targets * catch_rate,
            receiving_yards=targets * receiving_ypt, receiving_touchdowns=targets * receiving_td_rate,
            return_touchdowns=avg("special_teams_tds"), fumbles_lost=avg("fumbles_lost_total"),
            two_point_conversions=avg("passing_2pt_conversions") + avg("rushing_2pt_conversions") + avg("receiving_2pt_conversions"),
            passing_bonus_probability=_weighted(games, weights, lambda row: _float(row, "passing_yards") >= 300),
            rushing_bonus_probability=_weighted(games, weights, lambda row: _float(row, "rushing_yards") >= 100),
            receiving_bonus_probability=_weighted(games, weights, lambda row: _float(row, "receiving_yards") >= 100),
        )))
    return tuple(forecasts)


def _position_efficiency_rates(rows):
    grouped = defaultdict(lambda: defaultdict(float))
    columns = ("passing_yards", "attempts", "passing_tds", "passing_interceptions", "rushing_yards", "carries", "rushing_tds", "receptions", "targets", "receiving_yards", "receiving_tds")
    for row in rows:
        position = row.get("position", "ALL")
        for group in (position, "ALL"):
            for column in columns:
                grouped[group][column] += _float(row, column)
    rates = {}
    for group, values in grouped.items():
        rates[group] = {
            "pass_ypa": _ratio(values["passing_yards"], values["attempts"], 7.0),
            "pass_td_rate": _ratio(values["passing_tds"], values["attempts"], 0.045),
            "interception_rate": _ratio(values["passing_interceptions"], values["attempts"], 0.025),
            "rush_ypc": _ratio(values["rushing_yards"], values["carries"], 4.2),
            "rush_td_rate": _ratio(values["rushing_tds"], values["carries"], 0.035),
            "catch_rate": _ratio(values["receptions"], values["targets"], 0.65),
            "receiving_ypt": _ratio(values["receiving_yards"], values["targets"], 7.5),
            "receiving_td_rate": _ratio(values["receiving_tds"], values["targets"], 0.05),
        }
    rates.setdefault("ALL", {"pass_ypa": 7.0, "pass_td_rate": .045, "interception_rate": .025, "rush_ypc": 4.2, "rush_td_rate": .035, "catch_rate": .65, "receiving_ypt": 7.5, "receiving_td_rate": .05})
    return rates


def _shrunk_rate(rows, weights, numerator, denominator, prior_rate, prior_opportunities):
    numerator_total = sum(weight * _float(row, numerator) for row, weight in zip(rows, weights, strict=True))
    denominator_total = sum(weight * _float(row, denominator) for row, weight in zip(rows, weights, strict=True))
    return (numerator_total + prior_rate * prior_opportunities) / (denominator_total + prior_opportunities)


def _ratio(numerator, denominator, fallback):
    return numerator / denominator if denominator else fallback


def _forecast_defenses(slate, rows, games_rows, season, week, games_used, half_life):
    scores = {}
    for game in games_rows:
        if not game.get("home_score") or not game.get("away_score"):
            continue
        scores[(game["game_id"], game["home_team"])] = int(float(game["away_score"]))
        scores[(game["game_id"], game["away_team"])] = int(float(game["home_score"]))
    history = defaultdict(list)
    for row in rows:
        if row.get("season_type") != "REG" or not _before(row, season, week):
            continue
        if (row.get("game_id"), row.get("team")) in scores:
            history[row["team"]].append(row)
    forecasts = []
    for team in sorted({p.team for p in slate.players if p.primary_position == Position.DST}):
        games = sorted(history.get(team, []), key=lambda r: (int(r["season"]), int(r["week"])), reverse=True)[:games_used]
        if not games:
            continue
        weights = _weights(len(games), half_life)
        avg = lambda column: _weighted(games, weights, lambda row: _float(row, column))
        band = lambda low, high: _weighted(games, weights, lambda row: low <= scores[(row["game_id"], row["team"])] <= high)
        forecasts.append(TeamDefenseProjection(team, ProjectedDefenseStats(
            sacks=avg("def_sacks"), interceptions=avg("def_interceptions"),
            fumble_recoveries=avg("fumble_recovery_opp"),
            return_touchdowns=avg("def_tds") + avg("special_teams_tds") + avg("fumble_recovery_tds"),
            safeties=avg("def_safeties"),
            blocked_kicks=avg("def_punt_blocks") + avg("def_pat_blocks") + avg("def_fg_blocks"),
            probability_allow_0=band(0, 0), probability_allow_1_to_6=band(1, 6),
            probability_allow_7_to_13=band(7, 13), probability_allow_14_to_20=band(14, 20),
            probability_allow_21_to_27=band(21, 27), probability_allow_28_to_34=band(28, 34),
            probability_allow_35_plus=_weighted(games, weights, lambda row: scores[(row["game_id"], row["team"])] >= 35),
        )))
    return tuple(forecasts)


def _read_rows(paths):
    rows = []
    for path in paths:
        with Path(path).open(encoding="utf-8-sig", newline="") as handle:
            rows.extend(csv.DictReader(handle))
    return rows


def _before(row, target_season, target_week):
    return (int(row["season"]), int(row["week"])) < (target_season, target_week)


def _weights(count, half_life):
    return [math.pow(0.5, age / half_life) for age in range(count)]


def _weighted(rows, weights, value):
    return sum(weight * float(value(row)) for row, weight in zip(rows, weights, strict=True)) / sum(weights)


def _float(row, column):
    value = row.get(column, "")
    return float(value) if value not in (None, "") else 0.0


def _opportunities(position, row):
    if position == Position.QB:
        return _float(row, "attempts") + _float(row, "carries")
    if position == Position.K:
        return _float(row, "fg_att") + _float(row, "pat_att")
    return _float(row, "carries") + _float(row, "targets")


def _role_trend_factor(position, current_games):
    """Bound current-season volume trends without treating absences as role changes."""
    opportunities = [_opportunities(position, row) for row in current_games]
    active = [value for value in opportunities if value > 0]
    if len(active) < 2 or len(opportunities) < 3:
        return 1.0
    recent = sum(opportunities[:2]) / 2
    baseline = sum(opportunities) / len(opportunities)
    if baseline <= 0:
        return 1.0
    return max(0.75, min(1.15, recent / baseline))


def _normalize(value):
    ascii_name = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    parts = re.findall(r"[a-z0-9]+", ascii_name.lower())
    if parts and parts[-1] in {"jr", "sr", "ii", "iii", "iv", "v"}:
        parts.pop()
    return "".join(parts)
