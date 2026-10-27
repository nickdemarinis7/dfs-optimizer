from __future__ import annotations

from dataclasses import dataclass, replace
import math
from ortools.sat.python import cp_model
from dfs_optimizer.importers import ProjectionMatchResult
from dfs_optimizer.models import ContestFormat, Player, Position, Projection, Slate
from dfs_optimizer.rules import SingleGameRules, single_game_rules_for
from .classic import LineupOptimizationError


# Three of the first six verified DK/FD Showdown winners used either two
# kickers or a kicker/defense pairing. One remains a useful user-selected
# constraint, but it is too restrictive as the tournament default.
DEFAULT_SHOWDOWN_MAX_KICKERS_AND_DEFENSES = 2
# Both DK and FD Week 7 winners used 5-1 builds, and the verified top-one-percent
# bands averaged well above four players from their most-used team. Keep 4-2
# available as an expert choice without making it the tournament default.
DEFAULT_SHOWDOWN_MAX_PLAYERS_PER_TEAM = 5


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
    maximum_multiplier_bust_probability: float | None = None
    minimum_quarterbacks: int = 0
    minimum_quarterback_projection: float = 0.0
    minimum_player_projection: float = 0.0
    maximum_players_per_team: int | None = None
    maximum_kickers_and_defenses: int | None = None
    maximum_dst_opponents: int | None = None
    require_multiplier_receiver_qb: bool = False
    ceiling_weight: float = 0.0
    ownership_penalty: float = 0.0
    bust_probability_penalty: float = 0.0
    excluded_player_ids: frozenset[str] = frozenset()
    limited_player_ids: frozenset[str] = frozenset()
    player_exposure_limits: tuple[tuple[str, float], ...] = ()
    fragile_player_ids: frozenset[str] = frozenset()
    maximum_fragile_players: int | None = None

    def __post_init__(self) -> None:
        if self.minimum_multiplier_ceiling < 0:
            raise ValueError("minimum_multiplier_ceiling cannot be negative")
        if (
            self.maximum_multiplier_bust_probability is not None
            and not 0 <= self.maximum_multiplier_bust_probability <= 1
        ):
            raise ValueError(
                "maximum multiplier bust probability must be between 0 and 1"
            )
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
        if self.ownership_penalty < 0:
            raise ValueError("ownership_penalty cannot be negative")
        if self.bust_probability_penalty < 0:
            raise ValueError("bust_probability_penalty cannot be negative")
        exposure_ids = [player_id for player_id, _ in self.player_exposure_limits]
        if len(exposure_ids) != len(set(exposure_ids)):
            raise ValueError("player exposure limits cannot contain duplicate player ids")
        if any(not 0 < limit <= 1 for _, limit in self.player_exposure_limits):
            raise ValueError("player exposure limits must be greater than 0 and at most 1")
        if self.maximum_fragile_players is not None and self.maximum_fragile_players < 0:
            raise ValueError("maximum_fragile_players cannot be negative")


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
    player_exposure_limits = dict(base_settings.player_exposure_limits)
    max_player = max(1, math.floor(count * maximum_player_exposure))
    max_multiplier = max(1, math.floor(count * maximum_multiplier_exposure))
    player_counts: dict[str, int] = {}
    multiplier_counts: dict[str, int] = {}
    lineups = []
    for lineup_index in range(count):
        excluded = frozenset(
            key for key, value in player_counts.items()
            if value >= max_player
            or (key in base_settings.limited_player_ids and value >= 1)
            or (
                key in player_exposure_limits
                and value >= max(
                    1, math.floor(count * player_exposure_limits[key])
                )
            )
        )
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
    maximum_median_spread: float = 30.0,
    minimum_p90_ratio: float = .80,
    universal_core_player_ids: frozenset[str] = frozenset(),
) -> tuple[OptimizedSingleGameLineup, ...]:
    """Select two balanced builds and one highest-ceiling build jointly."""
    if not 0 < minimum_p90_ratio <= 1:
        raise ValueError("minimum_p90_ratio must be greater than 0 and at most 1")
    balanced_settings = replace(settings, ceiling_weight=0.30)
    ceiling_settings = replace(settings, ceiling_weight=0.70)
    candidates_by_key = {}
    for candidate_settings in (balanced_settings, ceiling_settings):
        unrestricted_settings = replace(
            candidate_settings, limited_player_ids=frozenset()
        )
        for lineup in generate_single_game_lineups(
            slate,
            projection_matches,
            candidate_count,
            minimum_unique_players=1,
            maximum_player_exposure=0.50,
            maximum_multiplier_exposure=0.34,
            settings=unrestricted_settings,
        ):
            key = (
                lineup.entries[0].player.platform_id,
                frozenset(entry.player.platform_id for entry in lineup.entries),
            )
            candidates_by_key.setdefault(key, lineup)
        # Sequential candidate generation tends to spend every elite player in
        # the same early lineups. Add the best build for each eligible Captain
        # so the joint solver can distribute the core across three genuinely
        # competitive constructions instead of inheriting that ordering bias.
        candidate_player_ids = {
            player.platform_id
            for player in slate.players
            if player.platform_id in projection_matches.by_player_id
        }
        core_ids = tuple(
            player_id
            for player_id, _ in sorted(
                projection_matches.by_player_id.items(),
                key=lambda item: item[1].projected_points,
                reverse=True,
            )[:4]
        )
        for captain_id in candidate_player_ids:
            exclusion_variants = (None,) + tuple(
                player_id for player_id in core_ids if player_id != captain_id
            )
            for excluded_core_id in exclusion_variants:
                try:
                    lineup = _optimize_single_game_lineup(
                        slate,
                        projection_matches,
                        None,
                        (),
                        (
                            frozenset({excluded_core_id})
                            if excluded_core_id else frozenset()
                        ),
                        frozenset(candidate_player_ids - {captain_id}),
                        settings=unrestricted_settings,
                    )
                except LineupOptimizationError:
                    continue
                key = (
                    lineup.entries[0].player.platform_id,
                    frozenset(entry.player.platform_id for entry in lineup.entries),
                )
                candidates_by_key.setdefault(key, lineup)
    # The Captain-specific search can produce several nearly identical variants
    # for every player. Feeding all of them into the joint model creates a
    # quadratic number of overlap variables and can exhaust the solver limit
    # before it finds even a feasible portfolio. Retain the strongest five for
    # each Captain so every multiplier path remains represented without hundreds
    # of redundant pairwise constraints.
    candidates_by_captain: dict[str, list[OptimizedSingleGameLineup]] = {}
    for lineup in candidates_by_key.values():
        candidates_by_captain.setdefault(
            lineup.entries[0].player.platform_id, []
        ).append(lineup)

    def seed_score(lineup: OptimizedSingleGameLineup) -> float:
        return sum(
            (
                entry.projection.projected_points * .55
                + (entry.projection.ceiling or entry.projection.projected_points) * .45
            ) * entry.point_multiplier
            for entry in lineup.entries
        )

    candidates = tuple(
        lineup
        for captain_id in sorted(candidates_by_captain)
        for lineup in sorted(
            candidates_by_captain[captain_id],
            key=seed_score,
            reverse=True,
        )[:5]
    )
    if len(candidates) < 3:
        raise LineupOptimizationError("not enough Showdown candidates for a 3-max portfolio")
    from dfs_optimizer.services.scenarios import simulate_lineups
    scenario_analysis = simulate_lineups(candidates, simulations=750)
    minimum_candidate_p90 = (
        max(item.p90 for item in scenario_analysis) * minimum_p90_ratio
    )

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
        ceilings.append(scenario_analysis[i].p90)
        if scenario_analysis[i].p90 < minimum_candidate_p90:
            model.add(chosen == 0)
    model.add(sum(balanced) == 2)
    model.add(sum(ceiling) == 1)

    # A three-entry tournament portfolio should represent a genuine receiver
    # eruption when the slate offers one. Require one WR/TE Captain from the
    # stable, asymmetric-ceiling candidates; shallow returners and merely
    # salary-efficient pass catchers do not qualify. The constraint is skipped
    # when the slate has no such candidate.
    players_by_id = {player.platform_id: player for player in slate.players}
    stable_receiver_captains = {
        player_id
        for player_id, projection in projection_matches.by_player_id.items()
        if players_by_id[player_id].primary_position in {Position.WR, Position.TE}
        and (projection.bust_probability or 0) <= .45
        and (projection.opportunity_stability or 0) >= .70
        and (projection.ceiling or projection.projected_points)
        >= projection.projected_points * 1.40
    }
    eligible_receiver_captain_indexes = [
        i for i, captain_id in enumerate(captain_ids)
        if captain_id in stable_receiver_captains
        and scenario_analysis[i].p90 >= minimum_candidate_p90
    ]
    if eligible_receiver_captain_indexes:
        model.add(sum(
            selected[i] for i in eligible_receiver_captain_indexes
        ) >= 1)

    for player_id in set().union(*player_sets):
        appearance_limit = (
            1
            if player_id in settings.limited_player_ids
            else 3 if player_id in universal_core_player_ids else 2
        )
        model.add(sum(
            selected[i] for i, ids in enumerate(player_sets) if player_id in ids
        ) <= appearance_limit)
    for captain_id in set(captain_ids):
        model.add(sum(
            selected[i] for i, value in enumerate(captain_ids) if value == captain_id
        ) <= 1)

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
            ownership = projection.projected_ownership or 0
            bust_probability = projection.bust_probability or 0
            total += (
                projection.projected_points * (1 - role_settings.ceiling_weight)
                + upper * role_settings.ceiling_weight
                - ownership * role_settings.ownership_penalty
                - bust_probability * role_settings.bust_probability_penalty
            ) * entry.point_multiplier
        return total

    scale = 1_000
    model.maximize(
        sum(
            round((role_score(lineup, balanced_settings) + scenario_analysis[i].p75 * .05) * scale) * balanced[i]
            + round((role_score(lineup, ceiling_settings) + scenario_analysis[i].p90 * .15) * scale) * ceiling[i]
            for i, lineup in enumerate(candidates)
        )
        - sum(cost * 100 * variable for cost, variable in pair_penalties)
    )
    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 0
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
        raw_multiplier_ceiling = (
            projection.ceiling
            if projection.ceiling is not None
            else projection.projected_points
        )
        multiplier_ceiling = raw_multiplier_ceiling * rules.multiplier
        if (
            settings.multiplier_positions is not None
            and players[i].primary_position not in settings.multiplier_positions
        ) or multiplier_ceiling < settings.minimum_multiplier_ceiling or (
            settings.maximum_multiplier_bust_probability is not None
            and (projection.bust_probability or 0)
            > settings.maximum_multiplier_bust_probability
        ):
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
    if settings.maximum_fragile_players is not None:
        model.add(sum(
            multiplier[i] + flex[i]
            for i, player in enumerate(players)
            if player.platform_id in settings.fragile_player_ids
        ) <= settings.maximum_fragile_players)
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
        ownership = projection.projected_ownership or 0
        bust_probability = projection.bust_probability or 0
        return (
            projection.projected_points * (1 - settings.ceiling_weight)
            + ceiling * settings.ceiling_weight
            - ownership * settings.ownership_penalty
            - bust_probability * settings.bust_probability_penalty
        )
    model.maximize(sum(round(objective_points(p) * rules.multiplier * scale) * multiplier[i] + round(objective_points(p) * scale) * flex[i] for i, p in enumerate(players)))
    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 0
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
