from __future__ import annotations

import math
import random
from dataclasses import dataclass

from dfs_optimizer.models import Position


@dataclass(frozen=True, slots=True)
class LineupScenarioAnalysis:
    lineup_number: int
    label: str
    mean: float
    p75: float
    p90: float
    top_rate: float


def simulate_lineups(
    lineups,
    simulations: int = 2_000,
    seed: int = 2_026,
) -> tuple[LineupScenarioAnalysis, ...]:
    """Simulate correlated outcomes while preserving each player's distribution."""
    if not lineups or simulations < 100:
        raise ValueError("lineups and at least 100 simulations are required")
    players = {
        entry.player.platform_id: (entry.player, entry.projection)
        for lineup in lineups for entry in lineup.entries
    }
    scores = [[] for _ in lineups]
    wins = [0 for _ in lineups]
    randomizer = random.Random(seed)
    for _ in range(simulations):
        game_factors = {
            player.game: randomizer.gauss(0, 1) for player, _ in players.values()
        }
        team_factors = {
            player.team: randomizer.gauss(0, 1) for player, _ in players.values()
        }
        pass_factors = {
            player.team: randomizer.gauss(0, 1) for player, _ in players.values()
        }
        rush_factors = {
            player.team: randomizer.gauss(0, 1) for player, _ in players.values()
        }
        outcomes = {}
        for player_id, (player, projection) in players.items():
            independent = randomizer.gauss(0, 1)
            game = game_factors[player.game]
            team = team_factors[player.team]
            if player.primary_position == Position.QB:
                components = ((.25, game), (.15, team), (.55, pass_factors[player.team]), (.35, independent))
            elif player.primary_position in {Position.WR, Position.TE}:
                components = ((.25, game), (.10, team), (.55, pass_factors[player.team]), (.45, independent))
            elif player.primary_position == Position.RB:
                components = ((.25, game), (.20, team), (.55, rush_factors[player.team]), (.45, independent))
            elif player.primary_position == Position.K:
                components = ((.30, game), (.30, team), (.65, independent))
            elif player.primary_position == Position.DST:
                components = ((-.20, game), (-.25, team_factors.get(player.opponent, 0)), (.70, independent))
            else:
                components = ((.20, game), (.20, team), (.70, independent))
            scale = math.sqrt(sum(weight * weight for weight, _ in components))
            z_score = sum(weight * value for weight, value in components) / scale
            probability = .5 * (1 + math.erf(z_score / math.sqrt(2)))
            outcomes[player_id] = _outcome_at(projection, probability)
        simulation_scores = []
        for lineup in lineups:
            score = sum(
                outcomes[entry.player.platform_id]
                * getattr(entry, "point_multiplier", 1)
                for entry in lineup.entries
            )
            simulation_scores.append(score)
        best = max(simulation_scores)
        winners = [index for index, score in enumerate(simulation_scores) if score == best]
        for index in winners:
            wins[index] += 1 / len(winners)
        for values, score in zip(scores, simulation_scores, strict=True):
            values.append(score)
    return tuple(
        LineupScenarioAnalysis(
            lineup_number=index + 1,
            label=_scenario_label(lineup),
            mean=sum(values) / len(values),
            p75=_quantile(values, .75),
            p90=_quantile(values, .90),
            top_rate=wins[index] / simulations,
        )
        for index, (lineup, values) in enumerate(zip(lineups, scores, strict=True))
    )


def _outcome_at(projection, probability: float) -> float:
    median = projection.projected_points
    p10 = projection.p10 if projection.p10 is not None else max(0, projection.floor or median * .4)
    p25 = projection.p25 if projection.p25 is not None else max(p10, projection.floor or median * .7)
    p75 = projection.p75 if projection.p75 is not None else max(median, (projection.ceiling or median * 1.3) * .8)
    p90 = projection.p90 if projection.p90 is not None else max(p75, projection.ceiling or median * 1.6)
    points = ((0.0, max(0, p10 - (p25 - p10))), (.10, p10), (.25, p25), (.50, median), (.75, p75), (.90, p90), (1.0, p90 + (p90 - p75)))
    for (left_probability, left), (right_probability, right) in zip(points, points[1:], strict=True):
        if probability <= right_probability:
            fraction = (probability - left_probability) / (right_probability - left_probability)
            return max(0, left + fraction * (right - left))
    return points[-1][1]


def _scenario_label(lineup) -> str:
    entries = lineup.entries
    multiplier = entries[0] if hasattr(entries[0], "point_multiplier") else None
    kickers_and_defenses = sum(
        entry.player.primary_position in {Position.K, Position.DST} for entry in entries
    )
    if kickers_and_defenses >= 2:
        return "Low-scoring special-teams game"
    if multiplier is not None:
        player = multiplier.player
        if player.primary_position == Position.RB:
            return f"{player.team} controls through {player.name}"
        if player.primary_position == Position.QB:
            receivers = sum(
                entry.player.team == player.team
                and entry.player.primary_position in {Position.WR, Position.TE}
                for entry in entries[1:]
            )
            return f"{player.team} passing eruption" if receivers else f"{player.name} rushing ceiling"
        return f"{player.name} Captain/MVP ceiling"
    quarterback = next(
        (entry.player for entry in entries if entry.player.primary_position == Position.QB),
        None,
    )
    if quarterback:
        receivers = sum(
            entry.player.team == quarterback.team
            and entry.player.primary_position in {Position.WR, Position.TE}
            for entry in entries
        )
        bring_back = any(entry.player.team == quarterback.opponent for entry in entries)
        if receivers and bring_back:
            return f"{quarterback.team}–{quarterback.opponent} passing shootout"
        if receivers:
            return f"{quarterback.team} passing stack"
    return "Balanced ceiling build"


def _quantile(values, probability: float) -> float:
    ordered = sorted(values)
    location = (len(ordered) - 1) * probability
    lower = int(location)
    fraction = location - lower
    return ordered[lower] + (ordered[min(lower + 1, len(ordered) - 1)] - ordered[lower]) * fraction
