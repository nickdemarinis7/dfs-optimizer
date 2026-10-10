from __future__ import annotations

import csv
from collections import Counter, defaultdict
from dataclasses import dataclass
from dataclasses import replace
import math
from pathlib import Path
import re
import statistics
import unicodedata

from dfs_optimizer.data_sources import download_cfb_player_stats
from dfs_optimizer.models import OffensiveStatLine, Player, Position, Projection, Slate, Sport
from dfs_optimizer.rules import nfl_scoring_for


CFB_FORECAST_MODEL_VERSION = "cfb-recent-usage-v2"


@dataclass(slots=True)
class _GameStats:
    passing_yards: float = 0
    passing_touchdowns: float = 0
    interceptions_thrown: float = 0
    rushing_yards: float = 0
    rushing_attempts: float = 0
    rushing_touchdowns: float = 0
    receptions: float = 0
    receiving_yards: float = 0
    receiving_touchdowns: float = 0
    targets: float = 0


def infer_cfb_season(slate: Slate) -> int | None:
    for value in (slate.source_name, *slate.games):
        if match := re.search(r"\b(20\d{2})\b", value):
            return int(match.group(1))
    return None


def build_cfb_projections(
    slate: Slate,
    season: int,
    cache_dir: str | Path = "data/cache/cfb",
    *,
    refresh: bool = False,
) -> tuple[Projection, ...]:
    if slate.sport != Sport.CFB:
        raise ValueError("CFB projections require a college-football slate")
    source = download_cfb_player_stats(
        season, cache_dir, refresh=refresh
    )
    return build_cfb_projections_from_file(slate, source)


def build_cfb_projections_from_file(
    slate: Slate, source: str | Path
) -> tuple[Projection, ...]:
    available = tuple(
        player for player in slate.players
        if (player.status or "").strip().upper() not in {"IR", "O", "OUT"}
        and player.platform_average is not None
    )
    players_by_name: dict[str, list[Player]] = defaultdict(list)
    for player in available:
        players_by_name[_normalize(player.name)].append(player)

    games: dict[tuple[str, str, str, str, int], _GameStats] = defaultdict(_GameStats)
    team_votes: dict[str, Counter[str]] = defaultdict(Counter)
    with Path(source).open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            team = row.get("team", "")
            opponent = row.get("opponent", "")
            game_id = row.get("game_id", "")
            week = int(_number(row.get("week")))
            names = {
                _normalize(row.get(column, ""))
                for column in (
                    "completion_player", "rush_player", "reception_player",
                    "target_player", "interception_thrown_player",
                )
                if _valid_name(row.get(column))
            }
            relevant = names & players_by_name.keys()
            if not relevant:
                continue
            for normalized in relevant:
                for player in players_by_name[normalized]:
                    team_votes[player.team][team] += 1

            completion = _normalized_value(row, "completion_player")
            rush = _normalized_value(row, "rush_player")
            reception = _normalized_value(row, "reception_player")
            target = _normalized_value(row, "target_player")
            interception = _normalized_value(row, "interception_thrown_player")
            touchdown = _normalized_value(row, "touchdown_player")
            identities = {completion, rush, reception, target, interception} - {""}
            for normalized in identities & players_by_name.keys():
                stats = games[(normalized, team, opponent, game_id, week)]
                if normalized == completion:
                    stats.passing_yards += _number(row.get("completion_yds"))
                    if touchdown:
                        stats.passing_touchdowns += 1
                if normalized == interception:
                    stats.interceptions_thrown += _number(
                        row.get("interception_thrown_stat"), default=1
                    )
                if normalized == rush:
                    stats.rushing_attempts += 1
                    stats.rushing_yards += _number(row.get("rush_yds"))
                    if touchdown == rush:
                        stats.rushing_touchdowns += 1
                if normalized == reception:
                    stats.receptions += 1
                    stats.receiving_yards += _number(row.get("reception_yds"))
                    if touchdown == reception:
                        stats.receiving_touchdowns += 1
                if normalized == target:
                    stats.targets += 1

    team_names = {
        abbreviation: votes.most_common(1)[0][0]
        for abbreviation, votes in team_votes.items()
        if votes
    }
    game_points: dict[str, list[tuple[int, float, float]]] = defaultdict(list)
    defense_points: dict[tuple[str, Position], list[float]] = defaultdict(list)
    scoring = nfl_scoring_for(slate.platform)
    for player in available:
        normalized = _normalize(player.name)
        expected_team = team_names.get(player.team)
        records = [
            (key, stats) for key, stats in games.items()
            if key[0] == normalized and (expected_team is None or key[1] == expected_team)
        ]
        if not records:
            records = [(key, stats) for key, stats in games.items() if key[0] == normalized]
        for (_, team, opponent, game_id, week), stats in records:
            points = scoring.score_offense(OffensiveStatLine(
                passing_yards=stats.passing_yards,
                passing_touchdowns=stats.passing_touchdowns,
                interceptions_thrown=stats.interceptions_thrown,
                rushing_yards=stats.rushing_yards,
                rushing_touchdowns=stats.rushing_touchdowns,
                receptions=stats.receptions,
                receiving_yards=stats.receiving_yards,
                receiving_touchdowns=stats.receiving_touchdowns,
            ))
            opportunity = stats.rushing_attempts + max(
                stats.targets, stats.receptions
            )
            game_points[player.platform_id].append((week, points, float(opportunity)))
            defense_points[(opponent, player.primary_position)].append(points)

    # Opponent adjustments use only matched slate players, keeping the model
    # position-aware without requiring a separate team-name crosswalk.
    position_means = {
        position: statistics.fmean(
            points for player in available if player.primary_position == position
            for _, points, _ in game_points.get(player.platform_id, ())
        )
        for position in {player.primary_position for player in available}
        if any(
            game_points.get(player.platform_id)
            for player in available if player.primary_position == position
        )
    }

    projections = []
    for player in available:
        observed = sorted(game_points.get(player.platform_id, ()), key=lambda item: item[0])
        platform_average = max(0.0, player.platform_average or 0)
        if observed:
            recent = observed[-5:]
            weights = tuple(range(1, len(recent) + 1))
            recent_mean = sum(item[1] * weight for item, weight in zip(recent, weights)) / sum(weights)
            reliability = min(1.0, len(observed) / 4)
            projected = recent_mean * (.45 + .35 * reliability) + platform_average * (.55 - .35 * reliability)
            season_opportunity = statistics.fmean(item[2] for item in observed)
            recent_opportunity = statistics.fmean(item[2] for item in observed[-2:])
            if season_opportunity > 0:
                projected *= min(
                    1.10,
                    max(.90, recent_opportunity / season_opportunity),
                )
            values = [item[1] for item in observed]
            matchup = team_names.get(player.opponent)
            allowed = defense_points.get((matchup, player.primary_position), ())
            position_mean = position_means.get(player.primary_position, 0)
            if allowed and position_mean > 0:
                projected *= min(1.15, max(.85, statistics.fmean(allowed) / position_mean))
            projected = max(0.0, projected)
            p10 = min(projected, max(0.0, _percentile(values, .10)))
            p25 = min(projected, max(p10, _percentile(values, .25)))
            p75 = max(projected, _percentile(values, .75))
            p90 = max(p75, _percentile(values, .90))
            bust = (sum(value < projected * .6 for value in values) + 1) / (len(values) + 3)
        else:
            projected = platform_average
            p10, p25 = projected * .4, projected * .7
            p75, p90 = projected * 1.3, projected * 1.65
            bust = .30
        projections.append(Projection(
            name=player.name,
            team=player.team,
            platform_id=player.platform_id,
            projected_points=round(projected, 3),
            floor=round(p25, 3),
            ceiling=round(p90, 3),
            p10=round(p10, 3),
            p25=round(p25, 3),
            p75=round(p75, 3),
            p90=round(p90, 3),
            bust_probability=min(1.0, max(0.0, bust)),
        ))
    return estimate_cfb_ownership(slate, tuple(projections))


def estimate_cfb_ownership(
    slate: Slate,
    projections: tuple[Projection, ...],
) -> tuple[Projection, ...]:
    """Add a transparent slate-relative ownership estimate.

    This is deliberately a proxy rather than a claim about contest-field data.
    It rewards projection, value, salary, ceiling, and position-relative rank,
    then scales the field to the number of roster slots that must be filled.
    """
    players = {
        player.platform_id: player
        for player in slate.players
        if player.platform_id
    }
    eligible = tuple(
        projection for projection in projections
        if projection.platform_id in players and projection.projected_points > 0
    )
    if not eligible:
        return projections

    points = _percentile_ranks({
        item.platform_id: item.projected_points for item in eligible
    })
    values = _percentile_ranks({
        item.platform_id: item.projected_points
        / max(1, players[item.platform_id].salary / 1000)
        for item in eligible
    })
    salaries = _percentile_ranks({
        item.platform_id: float(players[item.platform_id].salary)
        for item in eligible
    })
    ceilings = _percentile_ranks({
        item.platform_id: item.p90 or item.ceiling or item.projected_points
        for item in eligible
    })
    position_scores: dict[str, float] = {}
    by_position: dict[Position, dict[str, float]] = defaultdict(dict)
    for item in eligible:
        player = players[item.platform_id]
        by_position[player.primary_position][item.platform_id] = item.projected_points
    for position_values in by_position.values():
        position_scores.update(_percentile_ranks(position_values))

    raw = {
        item.platform_id: max(.02, math.exp(
            2.50 * points[item.platform_id]
            + 1.80 * values[item.platform_id]
            + .50 * salaries[item.platform_id]
            + 1.00 * ceilings[item.platform_id]
            + .60 * position_scores[item.platform_id]
        ))
        for item in eligible
    }
    roster_slots = 6 if slate.contest_format.value == "single_game" else (
        8 if slate.platform.value == "fanduel" else 9
    )
    ownership = _scale_with_cap(raw, roster_slots * 100.0, cap=55.0)
    return tuple(
        replace(
            item,
            projected_ownership=round(ownership.get(item.platform_id, 0.0), 2),
        )
        for item in projections
    )


def _percentile_ranks(values: dict[str, float]) -> dict[str, float]:
    ordered = sorted(values.items(), key=lambda item: (item[1], item[0]))
    denominator = max(1, len(ordered) - 1)
    return {
        key: index / denominator
        for index, (key, _) in enumerate(ordered)
    }


def _scale_with_cap(
    weights: dict[str, float], target: float, *, cap: float
) -> dict[str, float]:
    remaining = set(weights)
    result: dict[str, float] = {}
    remaining_target = min(target, cap * len(weights))
    while remaining:
        total_weight = sum(weights[key] for key in remaining)
        if total_weight <= 0:
            equal = remaining_target / len(remaining)
            result.update({key: equal for key in remaining})
            break
        newly_capped = {
            key for key in remaining
            if remaining_target * weights[key] / total_weight >= cap
        }
        if not newly_capped:
            result.update({
                key: remaining_target * weights[key] / total_weight
                for key in remaining
            })
            break
        for key in newly_capped:
            result[key] = cap
            remaining_target -= cap
        remaining -= newly_capped
    return result


def _valid_name(value: str | None) -> bool:
    return bool(value and value not in {"NA", "N/A"})


def _normalized_value(row: dict[str, str], key: str) -> str:
    value = row.get(key)
    return _normalize(value) if _valid_name(value) else ""


def _number(value: str | None, *, default: float = 0) -> float:
    if value in {None, "", "NA", "N/A"}:
        return default
    try:
        number = float(value)
        return number if math.isfinite(number) else default
    except ValueError:
        return default


def _normalize(value: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    normalized = re.sub(r"[^a-z0-9]", "", ascii_name.casefold())
    return re.sub(r"(?:jr|sr|ii|iii|iv)$", "", normalized)


def _percentile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)
