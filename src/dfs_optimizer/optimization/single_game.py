from __future__ import annotations

from dataclasses import dataclass, replace
import math
from ortools.sat.python import cp_model
from dfs_optimizer.importers import ProjectionMatchResult
from dfs_optimizer.models import ContestFormat, Player, Position, Projection, Slate
from dfs_optimizer.rules import SingleGameRules, single_game_rules_for
from .classic import LineupOptimizationError


@dataclass(frozen=True, slots=True)
class SingleGameEntry:
    slot: str
    player: Player
    projection: Projection
    salary: int
    point_multiplier: float

    @property
    def projected_points(self) -> float:
        return self.projection.projected_points * self.point_multiplier

    @property
    def platform_id(self) -> str:
        return (self.player.multiplier_platform_id or self.player.platform_id) if self.point_multiplier > 1 else self.player.platform_id


@dataclass(frozen=True, slots=True)
class OptimizedSingleGameLineup:
    entries: tuple[SingleGameEntry, ...]
    salary: int
    projected_points: float
    salary_cap: int


@dataclass(frozen=True, slots=True)
class SingleGameOptimizationSettings:
    multiplier_positions: frozenset[Position] | None = None
    minimum_multiplier_ceiling: float = 0.0
    minimum_quarterbacks: int = 0
    minimum_quarterback_projection: float = 0.0
    minimum_player_projection: float = 0.0
    maximum_players_per_team: int | None = None
    maximum_kickers_and_defenses: int | None = None
    maximum_dst_opponents: int | None = None
    require_multiplier_receiver_qb: bool = False
    ceiling_weight: float = 0.0
    excluded_player_ids: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if self.minimum_multiplier_ceiling < 0:
            raise ValueError("minimum_multiplier_ceiling cannot be negative")
        if self.minimum_quarterbacks < 0:
            raise ValueError("minimum_quarterbacks cannot be negative")
        if self.minimum_quarterback_projection < 0 or self.minimum_player_projection < 0:
            raise ValueError("minimum projection thresholds cannot be negative")
        if self.maximum_players_per_team is not None and self.maximum_players_per_team < 1:
            raise ValueError("maximum_players_per_team must be positive")
        if self.maximum_kickers_and_defenses is not None and self.maximum_kickers_and_defenses < 0:
            raise ValueError("maximum_kickers_and_defenses cannot be negative")
        if self.maximum_dst_opponents is not None and self.maximum_dst_opponents < 0:
            raise ValueError("maximum_dst_opponents cannot be negative")
        if not 0 <= self.ceiling_weight <= 1:
            raise ValueError("ceiling_weight must be between 0 and 1")


def optimize_single_game_lineup(slate: Slate, projection_matches: ProjectionMatchResult, rules: SingleGameRules | None = None, settings: SingleGameOptimizationSettings | None = None) -> OptimizedSingleGameLineup:
    return _optimize_single_game_lineup(slate, projection_matches, rules, (), frozenset(), frozenset(), settings=settings)


def generate_single_game_lineups(
    slate: Slate,
    projection_matches: ProjectionMatchResult,
    count: int,
    minimum_unique_players: int = 1,
    maximum_player_exposure: float = 1.0,
    maximum_multiplier_exposure: float = 1.0,
    rules: SingleGameRules | None = None,
    settings: SingleGameOptimizationSettings | None = None,
    lineup_ceiling_weights: tuple[float, ...] | None = None,
) -> tuple[OptimizedSingleGameLineup, ...]:
    if count < 1 or not 1 <= minimum_unique_players <= 6:
        raise ValueError("invalid lineup count or uniqueness")
    if not 0 < maximum_player_exposure <= 1 or not 0 < maximum_multiplier_exposure <= 1:
        raise ValueError("exposures must be greater than 0 and at most 1")
    if lineup_ceiling_weights is not None and (
        len(lineup_ceiling_weights) != count
        or any(not 0 <= weight <= 1 for weight in lineup_ceiling_weights)
    ):
        raise ValueError("lineup_ceiling_weights must contain one value between 0 and 1 per lineup")
    base_settings = settings or SingleGameOptimizationSettings()
    max_player = max(1, math.floor(count * maximum_player_exposure))
    max_multiplier = max(1, math.floor(count * maximum_multiplier_exposure))
    player_counts: dict[str, int] = {}
    multiplier_counts: dict[str, int] = {}
    lineups = []
    for lineup_index in range(count):
        excluded = frozenset(key for key, value in player_counts.items() if value >= max_player)
        multiplier_excluded = frozenset(key for key, value in multiplier_counts.items() if value >= max_multiplier)
        previous = tuple(frozenset(entry.player.platform_id for entry in lineup.entries) for lineup in lineups)
        try:
            iteration_settings = replace(
                base_settings,
                ceiling_weight=(
                    lineup_ceiling_weights[lineup_index]
                    if lineup_ceiling_weights is not None
                    else base_settings.ceiling_weight
                ),
            )
            lineup = _optimize_single_game_lineup(slate, projection_matches, rules, previous, excluded, multiplier_excluded, minimum_unique_players, iteration_settings)
        except LineupOptimizationError:
            break
        lineups.append(lineup)
        for entry in lineup.entries:
            key = entry.player.platform_id
            player_counts[key] = player_counts.get(key, 0) + 1
            if entry.point_multiplier > 1:
                multiplier_counts[key] = multiplier_counts.get(key, 0) + 1
    return tuple(lineups)


def generate_single_game_3max_portfolio(
    slate: Slate,
    projection_matches: ProjectionMatchResult,
    settings: SingleGameOptimizationSettings,
    minimum_unique_players: int = 2,
    candidate_count: int = 24,
    maximum_median_spread: float = 12.0,
) -> tuple[OptimizedSingleGameLineup, ...]:
    """Select two balanced builds and one highest-ceiling build jointly."""
    balanced_settings = replace(settings, ceiling_weight=0.30)
    ceiling_settings = replace(settings, ceiling_weight=0.70)
    candidates_by_key = {}
    for candidate_settings in (balanced_settings, ceiling_settings):
        for lineup in generate_single_game_lineups(
            slate,
            projection_matches,
            candidate_count,
            minimum_unique_players=1,
            maximum_player_exposure=0.50,
            maximum_multiplier_exposure=0.50,
            settings=candidate_settings,
        ):
            key = (
                lineup.entries[0].player.platform_id,
                frozenset(entry.player.platform_id for entry in lineup.entries),
            )
            candidates_by_key.setdefault(key, lineup)
    candidates = tuple(candidates_by_key.values())
    if len(candidates) < 3:
        raise LineupOptimizationError("not enough Showdown candidates for a 3-max portfolio")

    model = cp_model.CpModel()
    balanced = [model.new_bool_var(f"balanced_{i}") for i in range(len(candidates))]
    ceiling = [model.new_bool_var(f"ceiling_{i}") for i in range(len(candidates))]
    selected = []
    player_sets = []
    captain_ids = []
    ceilings = []
    for i, lineup in enumerate(candidates):
        model.add(balanced[i] + ceiling[i] <= 1)
        chosen = model.new_bool_var(f"selected_{i}")
        model.add(chosen == balanced[i] + ceiling[i])
        selected.append(chosen)
        player_sets.append({entry.player.platform_id for entry in lineup.entries})
        captain_ids.append(lineup.entries[0].player.platform_id)
        ceilings.append(sum(
            (entry.projection.ceiling or entry.projection.projected_points)
            * entry.point_multiplier for entry in lineup.entries
        ))
    model.add(sum(balanced) == 2)
    model.add(sum(ceiling) == 1)

    for player_id in set().union(*player_sets):
        model.add(sum(
            selected[i] for i, ids in enumerate(player_sets) if player_id in ids
        ) <= 2)
    for captain_id in set(captain_ids):
        model.add(sum(
            selected[i] for i, value in enumerate(captain_ids) if value == captain_id
        ) <= 2)

    pair_penalties = []
    lineup_size = len(candidates[0].entries)
    for left in range(len(candidates)):
        for right in range(left + 1, len(candidates)):
            overlap = len(player_sets[left] & player_sets[right])
            if (
                overlap > lineup_size - minimum_unique_players
                or abs(candidates[left].projected_points - candidates[right].projected_points)
                > maximum_median_spread
            ):
                model.add(selected[left] + selected[right] <= 1)
                continue
            pair = model.new_bool_var(f"pair_{left}_{right}")
            model.add(pair <= selected[left])
            model.add(pair <= selected[right])
            model.add(pair >= selected[left] + selected[right] - 1)
            pair_penalties.append(((overlap - 2) ** 2, pair))

    # The ceiling-designated lineup must actually have at least as much modeled
    # upside as either balanced lineup.
    for ceiling_index in range(len(candidates)):
        for balanced_index in range(len(candidates)):
            if ceilings[ceiling_index] < ceilings[balanced_index]:
                model.add(ceiling[ceiling_index] + balanced[balanced_index] <= 1)

    def role_score(lineup, role_settings) -> float:
        total = 0.0
        for entry in lineup.entries:
            projection = entry.projection
            upper = projection.ceiling or projection.projected_points
            total += (
                projection.projected_points * (1 - role_settings.ceiling_weight)
                + upper * role_settings.ceiling_weight
            ) * entry.point_multiplier
        return total

    scale = 1_000
    model.maximize(
        sum(
            round(role_score(lineup, balanced_settings) * scale) * balanced[i]
            + round(role_score(lineup, ceiling_settings) * scale) * ceiling[i]
            for i, lineup in enumerate(candidates)
        )
        - sum(cost * 100 * variable for cost, variable in pair_penalties)
    )
    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 8
    solver.parameters.max_time_in_seconds = 15
    status = solver.solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise LineupOptimizationError("no valid joint Showdown portfolio was found")
    balanced_lineups = [candidates[i] for i in range(len(candidates)) if solver.value(balanced[i])]
    ceiling_lineup = next(candidates[i] for i in range(len(candidates)) if solver.value(ceiling[i]))
    return tuple(balanced_lineups + [ceiling_lineup])


def _optimize_single_game_lineup(slate: Slate, projection_matches: ProjectionMatchResult, rules: SingleGameRules | None, previous_lineups: tuple[frozenset[str], ...], excluded: frozenset[str], multiplier_excluded: frozenset[str], minimum_unique: int = 1, settings: SingleGameOptimizationSettings | None = None) -> OptimizedSingleGameLineup:
    if slate.contest_format != ContestFormat.SINGLE_GAME:
        raise LineupOptimizationError("single-game optimizer requires a single-game slate")
    rules = rules or single_game_rules_for(slate.platform)
    settings = settings or SingleGameOptimizationSettings()
    players = tuple(
        player for player in slate.players
        if player.platform_id in projection_matches.by_player_id
        and projection_matches.by_player_id[player.platform_id].projected_points
        >= settings.minimum_player_projection
        and player.multiplier_salary is not None
        and player.platform_id not in settings.excluded_player_ids
    )
    if len(players) < rules.lineup_size:
        raise LineupOptimizationError(f"only {len(players)} single-game players have projections; at least {rules.lineup_size} are required")
    model = cp_model.CpModel()
    multiplier = [model.new_bool_var(f"multiplier_{i}") for i in range(len(players))]
    flex = [model.new_bool_var(f"flex_{i}") for i in range(len(players))]
    model.add_exactly_one(multiplier)
    model.add(sum(flex) == rules.flex_slots)
    for i in range(len(players)):
        model.add(multiplier[i] + flex[i] <= 1)
        if players[i].platform_id in excluded:
            model.add(multiplier[i] + flex[i] == 0)
        if players[i].platform_id in multiplier_excluded:
            model.add(multiplier[i] == 0)
        projection = projection_matches.by_player_id[players[i].platform_id]
        multiplier_ceiling = (
            projection.ceiling if projection.ceiling is not None else projection.projected_points
        ) * rules.multiplier
        if (
            settings.multiplier_positions is not None
            and players[i].primary_position not in settings.multiplier_positions
        ) or multiplier_ceiling < settings.minimum_multiplier_ceiling:
            model.add(multiplier[i] == 0)
    for previous in previous_lineups:
        model.add(sum(multiplier[i] + flex[i] for i, player in enumerate(players) if player.platform_id in previous) <= rules.lineup_size - minimum_unique)
    model.add(sum((players[i].multiplier_salary or 0) * multiplier[i] + players[i].salary * flex[i] for i in range(len(players))) <= rules.salary_cap)
    used_teams = []
    for team in sorted({p.team for p in players}):
        used = model.new_bool_var(f"team_{team}")
        selections = [multiplier[i] + flex[i] for i, p in enumerate(players) if p.team == team]
        for selection in selections:
            model.add(selection <= used)
        model.add(used <= sum(selections))
        if settings.maximum_players_per_team is not None:
            model.add(sum(selections) <= settings.maximum_players_per_team)
        used_teams.append(used)
    model.add(sum(used_teams) >= rules.minimum_teams)
    if settings.minimum_quarterbacks:
        model.add(sum(
            multiplier[i] + flex[i]
            for i, player in enumerate(players)
            if player.primary_position == Position.QB
            and projection_matches.by_player_id[player.platform_id].projected_points
            >= settings.minimum_quarterback_projection
        ) >= settings.minimum_quarterbacks)
    if settings.maximum_kickers_and_defenses is not None:
        model.add(sum(
            multiplier[i] + flex[i]
            for i, player in enumerate(players)
            if player.primary_position in {Position.K, Position.DST}
        ) <= settings.maximum_kickers_and_defenses)
    if settings.require_multiplier_receiver_qb:
        for index, player in enumerate(players):
            if player.primary_position not in {Position.WR, Position.TE}:
                continue
            teammate_qbs = [
                multiplier[qb_index] + flex[qb_index]
                for qb_index, quarterback in enumerate(players)
                if quarterback.team == player.team
                and quarterback.primary_position == Position.QB
                and projection_matches.by_player_id[quarterback.platform_id].projected_points
                >= settings.minimum_quarterback_projection
            ]
            model.add(sum(teammate_qbs) >= multiplier[index])
    if settings.maximum_dst_opponents is not None:
        for dst_index, defense in enumerate(players):
            if defense.primary_position != Position.DST:
                continue
            opposing_offense = [
                multiplier[index] + flex[index]
                for index, player in enumerate(players)
                if player.team == defense.opponent
                and player.primary_position in {Position.QB, Position.RB, Position.WR, Position.TE}
            ]
            model.add(
                sum(opposing_offense)
                <= settings.maximum_dst_opponents
                + rules.lineup_size * (1 - multiplier[dst_index] - flex[dst_index])
            )
    scale = 1_000
    def objective_points(player: Player) -> float:
        projection = projection_matches.by_player_id[player.platform_id]
        ceiling = projection.ceiling if projection.ceiling is not None else projection.projected_points
        return (
            projection.projected_points * (1 - settings.ceiling_weight)
            + ceiling * settings.ceiling_weight
        )
    model.maximize(sum(round(objective_points(p) * rules.multiplier * scale) * multiplier[i] + round(objective_points(p) * scale) * flex[i] for i, p in enumerate(players)))
    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 8
    solver.parameters.max_time_in_seconds = 15
    status = solver.solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise LineupOptimizationError("no valid single-game lineup satisfies the constraints")
    entries = []
    for i, player in enumerate(players):
        if solver.value(multiplier[i]):
            entries.append(SingleGameEntry(rules.multiplier_slot, player, projection_matches.by_player_id[player.platform_id], player.multiplier_salary or player.salary, rules.multiplier))
    flex_number = 1
    for i, player in enumerate(players):
        if solver.value(flex[i]):
            entries.append(SingleGameEntry(f"FLEX{flex_number}", player, projection_matches.by_player_id[player.platform_id], player.salary, 1.0))
            flex_number += 1
    return OptimizedSingleGameLineup(tuple(entries), sum(e.salary for e in entries), sum(e.projected_points for e in entries), rules.salary_cap)
