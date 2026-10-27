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
    script_type: str
    focal_team: str | None
    multiplier_player: str | None
    multiplier_position: str | None
    rationale: str


@dataclass(frozen=True, slots=True)
class ScriptValidation:
    lineup_number: int
    predicted_script: str
    verdict: str
    evidence: str


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
        script_factors = {}
        for player, _ in players.values():
            if player.team in script_factors:
                continue
            factor = randomizer.gauss(0, 1)
            script_factors[player.team] = factor
            script_factors.setdefault(player.opponent, -factor)
        receiver_ids_by_team = {}
        for player_id, (player, _) in players.items():
            if player.primary_position in {Position.WR, Position.TE}:
                receiver_ids_by_team.setdefault(player.team, []).append(player_id)
        receiver_share_factors = {}
        for player_ids in receiver_ids_by_team.values():
            raw = [randomizer.gauss(0, 1) for _ in player_ids]
            average = sum(raw) / len(raw)
            receiver_share_factors.update({
                player_id: value - average
                for player_id, value in zip(player_ids, raw, strict=True)
            })
        outcomes = {}
        for player_id, (player, projection) in players.items():
            independent = randomizer.gauss(0, 1)
            game = game_factors[player.game]
            team = team_factors[player.team]
            script = script_factors[player.team]
            if player.primary_position == Position.QB:
                components = ((.25, game), (.15, team), (.60, pass_factors[player.team]), (.20, script), (.30, independent))
            elif player.primary_position in {Position.WR, Position.TE}:
                # Passing volume can lift several teammates together. Target
                # share still differentiates receivers, but it should not
                # dominate the shared ceiling—as it did when a QB supported
                # multiple tournament-winning pass catchers on the same slate.
                components = ((.25, game), (.10, team), (.60, pass_factors[player.team]), (.15, script), (.18, receiver_share_factors[player_id]), (.35, independent))
            elif player.primary_position == Position.RB:
                components = ((.25, game), (.20, team), (.50, rush_factors[player.team]), (-.20, script), (.45, independent))
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
            **_scenario_profile(lineup),
            mean=sum(values) / len(values),
            p75=_quantile(values, .75),
            p90=_quantile(values, .90),
            top_rate=wins[index] / simulations,
        )
        for index, (lineup, values) in enumerate(zip(lineups, scores, strict=True))
    )


def validate_lineup_scripts(
    lineups,
    analyses: tuple[LineupScenarioAnalysis, ...],
    actuals,
    team_scores: dict[str, int] | None = None,
) -> tuple[ScriptValidation, ...]:
    """Grade broad lineup theses against final fantasy outcomes.

    This intentionally validates only claims supported by contest results.
    A low-scoring football script needs a supplied final score; kicker or DST
    fantasy results alone are not treated as proof that the game was low scoring.
    """
    actual_by_name = {
        _normalize_name(item.name): item.fantasy_points for item in actuals
    }
    # Salary pools contain many inactive or unused players whose zeroes would
    # make almost any multiplier look like a successful ceiling call. Compare
    # against players who recorded a positive outcome, while a selected zero
    # still grades below that benchmark and is therefore contradicted.
    all_points = sorted(value for value in actual_by_name.values() if value > 0)
    if not all_points:
        return ()
    median = _quantile(all_points, .50)
    upper_quartile = _quantile(all_points, .75)
    results = []
    for lineup, analysis in zip(lineups, analyses, strict=True):
        multiplier = lineup.entries[0]
        multiplier_points = actual_by_name.get(
            _normalize_name(multiplier.player.name)
        )
        script_type = analysis.script_type
        verdict = "Inconclusive"
        evidence = "Final player results do not directly prove this game script."
        if script_type == "low_scoring_special_teams":
            if team_scores and all(team in team_scores for team in lineup.entries[0].player.game.split("@")):
                teams = lineup.entries[0].player.game.split("@")
                total = sum(team_scores[team] for team in teams)
                verdict = "Supported" if total <= 44 else "Contradicted" if total >= 52 else "Inconclusive"
                evidence = f"The final game total was {total} points."
            else:
                specialists = [
                    entry.player.name for entry in lineup.entries
                    if entry.player.primary_position in {Position.K, Position.DST}
                ]
                specialist_points = [
                    actual_by_name[_normalize_name(name)] for name in specialists
                    if _normalize_name(name) in actual_by_name
                ]
                evidence = (
                    f"Final score was not entered; selected K/DST averaged "
                    f"{sum(specialist_points) / len(specialist_points):.1f} fantasy points."
                    if specialist_points else "Final score was not entered."
                )
        elif multiplier_points is not None:
            if script_type in {
                "multiplier_ceiling", "team_rushing_control", "team_passing_eruption",
                "quarterback_rushing_ceiling",
            }:
                verdict = (
                    "Supported" if multiplier_points >= upper_quartile
                    else "Contradicted" if multiplier_points < median
                    else "Inconclusive"
                )
                evidence = (
                    f"{multiplier.player.name} scored {multiplier_points:.1f}; "
                    f"the slate median was {median:.1f} and upper quartile was "
                    f"{upper_quartile:.1f}."
                )
        results.append(ScriptValidation(
            analysis.lineup_number, analysis.label, verdict, evidence
        ))
    return tuple(results)


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


def _scenario_profile(lineup) -> dict:
    entries = lineup.entries
    multiplier = entries[0] if hasattr(entries[0], "point_multiplier") else None
    kickers_and_defenses = sum(
        entry.player.primary_position in {Position.K, Position.DST} for entry in entries
    )
    if kickers_and_defenses >= 2:
        return {
            "label": "Low-scoring special-teams game",
            "script_type": "low_scoring_special_teams",
            "focal_team": None,
            "multiplier_player": multiplier.player.name if multiplier else None,
            "multiplier_position": multiplier.player.primary_position.value if multiplier else None,
            "rationale": "The lineup uses at least two kickers or defenses and benefits from stalled drives or defensive scoring.",
        }
    if multiplier is not None:
        player = multiplier.player
        if player.primary_position == Position.RB:
            label, script_type = f"{player.team} controls through {player.name}", "team_rushing_control"
            rationale = f"{player.name} occupies the multiplier slot in a rushing-led {player.team} construction."
        if player.primary_position == Position.QB:
            receivers = sum(
                entry.player.team == player.team
                and entry.player.primary_position in {Position.WR, Position.TE}
                for entry in entries[1:]
            )
            label = f"{player.team} passing eruption" if receivers else f"{player.name} rushing ceiling"
            script_type = "team_passing_eruption" if receivers else "quarterback_rushing_ceiling"
            rationale = (
                f"{player.name} is multiplied with {receivers} same-team pass catcher(s)."
                if receivers else f"{player.name} is multiplied without a same-team pass catcher."
            )
        if player.primary_position not in {Position.RB, Position.QB}:
            label, script_type = f"{player.name} Captain/MVP ceiling", "multiplier_ceiling"
            rationale = f"The lineup requires a ceiling outcome from multiplier {player.name}."
        return {
            "label": label,
            "script_type": script_type,
            "focal_team": player.team,
            "multiplier_player": player.name,
            "multiplier_position": player.primary_position.value,
            "rationale": rationale,
        }
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
            label = f"{quarterback.team}–{quarterback.opponent} passing shootout"
            script_type = "passing_shootout"
            rationale = "The lineup pairs a quarterback stack with an opposing bring-back."
            return {"label": label, "script_type": script_type, "focal_team": quarterback.team, "multiplier_player": None, "multiplier_position": None, "rationale": rationale}
        if receivers:
            return {"label": f"{quarterback.team} passing stack", "script_type": "team_passing_stack", "focal_team": quarterback.team, "multiplier_player": None, "multiplier_position": None, "rationale": "The lineup pairs a quarterback with same-team pass catchers."}
    return {"label": "Balanced ceiling build", "script_type": "balanced", "focal_team": None, "multiplier_player": None, "multiplier_position": None, "rationale": "No single scoring path dominates the construction."}


def _normalize_name(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())


def _quantile(values, probability: float) -> float:
    ordered = sorted(values)
    location = (len(ordered) - 1) * probability
    lower = int(location)
    fraction = location - lower
    return ordered[lower] + (ordered[min(lower + 1, len(ordered) - 1)] - ordered[lower]) * fraction
