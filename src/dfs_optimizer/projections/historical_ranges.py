from __future__ import annotations

import csv
import re
import unicodedata
from collections import defaultdict
from dataclasses import replace
from pathlib import Path

from dfs_optimizer.models import DefenseStatLine, OffensiveStatLine, Position, Projection, Slate
from dfs_optimizer.rules import nfl_scoring_for


def add_historical_ranges(
    slate: Slate,
    projections: tuple[Projection, ...],
    player_files: tuple[str | Path, ...],
    team_files: tuple[str | Path, ...],
    games_file: str | Path,
    target_season: int,
    target_week: int,
    games_used: int = 8,
) -> tuple[Projection, ...]:
    """Add empirical 20th/80th-percentile ranges using only prior games."""
    scoring = nfl_scoring_for(slate.platform)
    offense = defaultdict(list)
    for row in _rows(player_files):
        if row.get("season_type") != "REG" or not _before(row, target_season, target_week):
            continue
        stats = OffensiveStatLine(
            passing_yards=_number(row, "passing_yards"),
            passing_touchdowns=_number(row, "passing_tds"),
            interceptions_thrown=_number(row, "passing_interceptions"),
            rushing_yards=_number(row, "rushing_yards"),
            rushing_touchdowns=_number(row, "rushing_tds"),
            receptions=_number(row, "receptions"),
            receiving_yards=_number(row, "receiving_yards"),
            receiving_touchdowns=_number(row, "receiving_tds"),
            return_touchdowns=_number(row, "special_teams_tds"),
            fumbles_lost=_number(row, "fumbles_lost_total"),
            two_point_conversions=sum(_number(row, column) for column in (
                "passing_2pt_conversions", "rushing_2pt_conversions", "receiving_2pt_conversions"
            )),
        )
        offense[_normalize(row.get("player_display_name", ""))].append(
            ((int(row["season"]), int(row["week"])), scoring.score_offense(stats))
        )

    games = _rows((games_file,))
    points_allowed = {}
    for game in games:
        if game.get("home_score") in (None, "") or game.get("away_score") in (None, ""):
            continue
        points_allowed[(game.get("game_id"), game.get("home_team"))] = int(float(game["away_score"]))
        points_allowed[(game.get("game_id"), game.get("away_team"))] = int(float(game["home_score"]))
    defenses = defaultdict(list)
    for row in _rows(team_files):
        if row.get("season_type") != "REG" or not _before(row, target_season, target_week):
            continue
        key = (row.get("game_id"), row.get("team"))
        if key not in points_allowed:
            continue
        stats = DefenseStatLine(
            sacks=_number(row, "def_sacks"),
            interceptions=_number(row, "def_interceptions"),
            fumble_recoveries=_number(row, "fumble_recovery_opp"),
            return_touchdowns=sum(_number(row, column) for column in (
                "def_tds", "special_teams_tds", "fumble_recovery_tds"
            )),
            safeties=_number(row, "def_safeties"),
            blocked_kicks=sum(_number(row, column) for column in (
                "def_punt_blocks", "def_pat_blocks", "def_fg_blocks"
            )),
            points_allowed=points_allowed[key],
        )
        defenses[row["team"]].append(
            ((int(row["season"]), int(row["week"])), scoring.score_defense(stats))
        )

    players = {player.platform_id: player for player in slate.players}
    enriched = []
    for projection in projections:
        player = players.get(projection.platform_id or "")
        history = defenses.get(player.team, []) if player and player.primary_position == Position.DST else offense.get(_normalize(projection.name), [])
        scores = [score for _, score in sorted(history, reverse=True)[:games_used]]
        if not scores:
            enriched.append(replace(projection, floor=projection.projected_points, ceiling=projection.projected_points))
            continue
        historical_mean = sum(scores) / len(scores)
        context_scale = projection.projected_points / historical_mean if historical_mean > 0 else 1
        context_scale = max(0.75, min(1.25, context_scale))
        floor = _quantile(scores, 0.20) * context_scale
        ceiling = _quantile(scores, 0.80) * context_scale
        enriched.append(replace(
            projection,
            floor=min(floor, projection.projected_points),
            ceiling=max(ceiling, projection.projected_points),
        ))
    return tuple(enriched)


def _rows(paths):
    result = []
    for path in paths:
        with Path(path).open(encoding="utf-8-sig", newline="") as handle:
            result.extend(csv.DictReader(handle))
    return result


def _before(row, season, week):
    return (int(row["season"]), int(row["week"])) < (season, week)


def _number(row, column):
    value = row.get(column, "")
    return float(value) if value not in (None, "") else 0.0


def _normalize(value):
    ascii_name = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    parts = re.findall(r"[a-z0-9]+", ascii_name.lower())
    if parts and parts[-1] in {"jr", "sr", "ii", "iii", "iv", "v"}:
        parts.pop()
    return "".join(parts)


def _quantile(values, probability):
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    location = (len(ordered) - 1) * probability
    lower = int(location)
    fraction = location - lower
    return ordered[lower] + (ordered[min(lower + 1, len(ordered) - 1)] - ordered[lower]) * fraction
