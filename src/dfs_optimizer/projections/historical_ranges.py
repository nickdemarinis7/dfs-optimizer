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
    snap_files: tuple[str | Path, ...] = (),
) -> tuple[Projection, ...]:
    """Add empirical outcome distributions using only games before the target."""
    scoring = nfl_scoring_for(slate.platform)
    offense = defaultdict(list)
    offense_rows = defaultdict(list)
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
        offense_rows[_normalize(row.get("player_display_name", ""))].append(row)

    snap_rows = defaultdict(list)
    for row in _rows(snap_files):
        if (
            row.get("game_type") == "REG"
            and _before(row, target_season, target_week)
        ):
            snap_rows[(_normalize(row.get("player", "")), row.get("team", ""))].append(row)

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
        usage_rows = sorted(
            (
                row for row in offense_rows.get(_normalize(projection.name), ())
                if int(row.get("season") or 0) == target_season
            ),
            key=lambda row: int(row.get("week") or 0),
            reverse=True,
        )[:games_used]
        opportunities = [
            _opportunities(player.primary_position, row) for row in usage_rows
        ] if player is not None else []
        opportunity_retention = _recent_retention(opportunities)
        player_snaps = sorted(
            snap_rows.get((_normalize(projection.name), player.team), ())
            if player is not None else (),
            key=lambda row: int(row.get("week") or 0),
            reverse=True,
        )[:games_used]
        snap_retention = _recent_retention([
            _number(row, "offense_pct") for row in player_snaps
        ])
        stability_signals = [
            value for value in (opportunity_retention, snap_retention)
            if value is not None
        ]
        opportunity_stability = min(stability_signals) if stability_signals else None
        latest_week = max(
            (int(row.get("week") or 0) for row in usage_rows), default=0
        )
        metadata = {
            "sample_size": len(scores),
            "opportunity_stability": opportunity_stability,
            "data_age_periods": max(0, target_week - 1 - latest_week) if latest_week else None,
        }
        if not scores:
            point = projection.projected_points
            enriched.append(replace(
                projection, floor=point, ceiling=point,
                p10=point, p25=point, p75=point, p90=point,
                **metadata,
            ))
            continue
        historical_mean = sum(scores) / len(scores)
        context_scale = projection.projected_points / historical_mean if historical_mean > 0 else 1
        # A role-change projection must also pull down the historical ceiling.
        # The old 0.75 floor preserved too much upside from temporary starts.
        context_scale = max(0.35, min(1.25, context_scale))
        raw_p10 = _quantile(scores, 0.10) * context_scale
        raw_p25 = _quantile(scores, 0.25) * context_scale
        raw_p75 = _quantile(scores, 0.75) * context_scale
        raw_p90 = _quantile(scores, 0.90) * context_scale
        p10 = max(0, min(raw_p10, projection.projected_points))
        p25 = max(p10, min(raw_p25, projection.projected_points))
        p90 = max(projection.projected_points, raw_p90)
        p75 = min(p90, max(projection.projected_points, raw_p75))
        bust_line = max(2.0, projection.projected_points * 0.5)
        bust_probability = sum(score <= bust_line for score in scores) / len(scores)
        enriched.append(replace(
            projection,
            floor=p25,
            ceiling=p90,
            p10=p10,
            p25=p25,
            p75=p75,
            p90=p90,
            bust_probability=bust_probability,
            **metadata,
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


def _opportunities(position: Position, row) -> float:
    if position == Position.QB:
        return _number(row, "attempts") + _number(row, "carries")
    if position == Position.K:
        return _number(row, "fg_att") + _number(row, "pat_att")
    return _number(row, "carries") + _number(row, "targets")


def _recent_retention(values: list[float]) -> float | None:
    if len(values) < 3:
        return None
    recent = values[:2]
    prior = [value for value in values[2:] if value > 0]
    if not prior:
        return None
    prior_average = sum(prior) / len(prior)
    return min(1.0, max(0.0, (sum(recent) / len(recent)) / prior_average))


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
