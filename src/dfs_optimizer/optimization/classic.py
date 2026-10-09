from __future__ import annotations

from dataclasses import dataclass, replace
import math

from ortools.sat.python import cp_model

from dfs_optimizer.importers import ProjectionMatchResult
from dfs_optimizer.models import Player, Position, Projection, Slate
from dfs_optimizer.rules import RosterRules, RosterSlot, classic_rules_for


class LineupOptimizationError(ValueError):
    """Raised when inputs cannot produce a valid Classic lineup."""


@dataclass(frozen=True, slots=True)
class ClassicOptimizationSettings:
    locked_player_ids: frozenset[str] = frozenset()
    excluded_player_ids: frozenset[str] = frozenset()
    limited_player_ids: frozenset[str] = frozenset()
    qb_stack_size: int = 0
    require_opponent_bring_back: bool = False
    avoid_dst_opponents: bool = True
    ceiling_weight: float = 0.0
    ownership_penalty: float = 0.0
    minimum_bring_back_projection: float = 0.0
    minimum_stack_projection: float = 0.0
    minimum_stack_ceiling: float = 0.0
    minimum_bring_back_ceiling: float = 0.0
    unique_primary_stacks: bool = False

    def __post_init__(self) -> None:
        if self.locked_player_ids & self.excluded_player_ids:
            raise ValueError("a player cannot be both locked and excluded")
        if self.locked_player_ids & self.limited_player_ids:
            raise ValueError("a locked player cannot be limited to one lineup")
        if self.qb_stack_size not in (0, 1, 2):
            raise ValueError("qb_stack_size must be 0, 1, or 2")
        if not 0 <= self.ceiling_weight <= 1:
            raise ValueError("ceiling_weight must be between 0 and 1")
        if self.ownership_penalty < 0:
            raise ValueError("ownership_penalty cannot be negative")
        if self.minimum_bring_back_projection < 0:
            raise ValueError("minimum_bring_back_projection cannot be negative")
        if self.minimum_stack_projection < 0:
            raise ValueError("minimum_stack_projection cannot be negative")
        if self.minimum_stack_ceiling < 0 or self.minimum_bring_back_ceiling < 0:
            raise ValueError("minimum stack and bring-back ceilings cannot be negative")


@dataclass(frozen=True, slots=True)
class LineupEntry:
    slot: str
    player: Player
    projection: Projection


@dataclass(frozen=True, slots=True)
class OptimizedLineup:
    entries: tuple[LineupEntry, ...]
    salary: int
    projected_points: float
    salary_cap: int

    @property
    def remaining_salary(self) -> int:
        return self.salary_cap - self.salary


def optimize_classic_lineup(
    slate: Slate,
    projection_matches: ProjectionMatchResult,
    rules: RosterRules | None = None,
    settings: ClassicOptimizationSettings | None = None,
) -> OptimizedLineup:
    return _optimize_classic_lineup(
        slate, projection_matches, rules, settings or ClassicOptimizationSettings(), (), (), {}
    )


def generate_classic_lineups(
    slate: Slate,
    projection_matches: ProjectionMatchResult,
    count: int,
    minimum_unique_players: int = 1,
    rules: RosterRules | None = None,
    settings: ClassicOptimizationSettings | None = None,
    maximum_player_exposure: float = 1.0,
    maximum_qb_exposure: float = 1.0,
    maximum_dst_exposure: float = 1.0,
    lineup_ceiling_weights: tuple[float, ...] | None = None,
) -> tuple[OptimizedLineup, ...]:
    if count < 1:
        raise ValueError("lineup count must be at least 1")
    resolved_rules = rules or classic_rules_for(slate.platform)
    if not 1 <= minimum_unique_players <= resolved_rules.lineup_size:
        raise ValueError("minimum_unique_players must be between 1 and lineup size")
    if not 0 < maximum_player_exposure <= 1:
        raise ValueError("maximum_player_exposure must be greater than 0 and at most 1")
    if not 0 < maximum_qb_exposure <= 1:
        raise ValueError("maximum_qb_exposure must be greater than 0 and at most 1")
    if not 0 < maximum_dst_exposure <= 1:
        raise ValueError("maximum_dst_exposure must be greater than 0 and at most 1")
    if lineup_ceiling_weights is not None:
        if len(lineup_ceiling_weights) != count:
            raise ValueError("lineup_ceiling_weights must contain one value per lineup")
        if any(not 0 <= weight <= 1 for weight in lineup_ceiling_weights):
            raise ValueError("lineup ceiling weights must be between 0 and 1")
    base_settings = settings or ClassicOptimizationSettings()
    maximum_appearances = max(1, math.floor(count * maximum_player_exposure))
    maximum_qb_appearances = max(1, math.floor(count * maximum_qb_exposure))
    maximum_dst_appearances = max(1, math.floor(count * maximum_dst_exposure))
    positions_by_id = {
        player.platform_id: player.primary_position for player in slate.players
    }
    appearances: dict[str, int] = {}
    lineups: list[OptimizedLineup] = []
    for lineup_index in range(count):
        exposure_exclusions = {
            player_id for player_id, appearances_so_far in appearances.items()
            if (
                appearances_so_far >= maximum_appearances
                or (
                    positions_by_id.get(player_id) == Position.QB
                    and appearances_so_far >= maximum_qb_appearances
                )
                or (
                    positions_by_id.get(player_id) == Position.DST
                    and appearances_so_far >= maximum_dst_appearances
                )
                or (
                    player_id in base_settings.limited_player_ids
                    and appearances_so_far >= 1
                )
            )
            and player_id not in base_settings.locked_player_ids
        }
        iteration_settings = replace(
            base_settings,
            excluded_player_ids=base_settings.excluded_player_ids | exposure_exclusions,
            ceiling_weight=(
                lineup_ceiling_weights[lineup_index]
                if lineup_ceiling_weights is not None
                else base_settings.ceiling_weight
            ),
        )
        try:
            lineup = _optimize_classic_lineup(
                slate,
                projection_matches,
                resolved_rules,
                iteration_settings,
                tuple((frozenset(e.player.platform_id for e in prior.entries), minimum_unique_players) for prior in lineups),
                tuple(
                    combination
                    for prior in lineups
                    for combination in _stack_combinations(prior)
                ) if base_settings.unique_primary_stacks else (),
                appearances,
            )
        except LineupOptimizationError:
            if not lineups:
                raise
            break
        lineups.append(lineup)
        for entry in lineup.entries:
            player_id = entry.player.platform_id
            appearances[player_id] = appearances.get(player_id, 0) + 1
    return tuple(lineups)


def generate_classic_3max_portfolio(
    slate: Slate,
    projection_matches: ProjectionMatchResult,
    settings: ClassicOptimizationSettings,
    minimum_unique_players: int = 3,
    maximum_player_appearances: int = 2,
    maximum_dst_appearances: int = 1,
    candidate_count: int = 20,
) -> tuple[OptimizedLineup, ...]:
    """Select two balanced lineups and one ceiling lineup as a single portfolio."""
    if candidate_count < 3:
        raise ValueError("candidate_count must be at least 3")
    rules = classic_rules_for(slate.platform)
    balanced_settings = replace(settings, ceiling_weight=0.30)
    ceiling_settings = replace(settings, ceiling_weight=0.70)
    candidates_by_ids: dict[frozenset[str], OptimizedLineup] = {}
    for candidate_settings in (balanced_settings, ceiling_settings):
        for lineup in generate_classic_lineups(
            slate,
            projection_matches,
            candidate_count,
            minimum_unique_players=1,
            rules=rules,
            settings=replace(candidate_settings, limited_player_ids=frozenset()),
            maximum_player_exposure=0.50,
            maximum_qb_exposure=0.50,
            maximum_dst_exposure=0.50,
        ):
            ids = frozenset(entry.player.platform_id for entry in lineup.entries)
            candidates_by_ids.setdefault(ids, lineup)
    candidates = tuple(candidates_by_ids.values())
    if len(candidates) < 3:
        raise LineupOptimizationError(
            "not enough distinct candidate lineups to build a 3-max portfolio"
        )
    from dfs_optimizer.services.scenarios import simulate_lineups
    scenario_analysis = simulate_lineups(candidates, simulations=750)

    model = cp_model.CpModel()
    balanced = [model.new_bool_var(f"balanced_{index}") for index in range(len(candidates))]
    ceiling = [model.new_bool_var(f"ceiling_{index}") for index in range(len(candidates))]
    selected = []
    player_sets = []
    for index, lineup in enumerate(candidates):
        model.add(balanced[index] + ceiling[index] <= 1)
        chosen = model.new_bool_var(f"selected_{index}")
        model.add(chosen == balanced[index] + ceiling[index])
        selected.append(chosen)
        player_sets.append({entry.player.platform_id for entry in lineup.entries})
    model.add(sum(balanced) == 2)
    model.add(sum(ceiling) == 1)

    all_player_ids = set().union(*player_sets)
    for player_id in all_player_ids - settings.locked_player_ids:
        player = next(item for item in slate.players if item.platform_id == player_id)
        appearance_limit = (
            1 if player_id in settings.limited_player_ids
            else maximum_dst_appearances if player.primary_position == Position.DST
            else maximum_player_appearances
        )
        model.add(
            sum(selected[index] for index, ids in enumerate(player_sets) if player_id in ids)
            <= appearance_limit
        )

    pair_penalties = []
    for left in range(len(candidates)):
        for right in range(left + 1, len(candidates)):
            overlap = len(player_sets[left] & player_sets[right])
            incompatible = overlap > rules.lineup_size - minimum_unique_players
            if settings.unique_primary_stacks:
                incompatible = incompatible or bool(
                    set(_stack_combinations(candidates[left]))
                    & set(_stack_combinations(candidates[right]))
                )
            if incompatible:
                model.add(selected[left] + selected[right] <= 1)
                continue
            pair_selected = model.new_bool_var(f"pair_{left}_{right}")
            model.add(pair_selected <= selected[left])
            model.add(pair_selected <= selected[right])
            model.add(pair_selected >= selected[left] + selected[right] - 1)
            pair_penalties.append(((overlap - 3) ** 2, pair_selected))

    score_scale = 1_000
    role_scores = []
    for index, lineup in enumerate(candidates):
        balanced_score = sum(
            _objective_points(entry.projection, balanced_settings) for entry in lineup.entries
        )
        ceiling_score = sum(
            _objective_points(entry.projection, ceiling_settings) for entry in lineup.entries
        )
        # Reward lineup-level correlated upside that a sum of independent player
        # ceilings cannot represent.
        balanced_score += scenario_analysis[index].p75 * .05
        ceiling_score += scenario_analysis[index].p90 * .15
        role_scores.extend((
            round(balanced_score * score_scale) * balanced[index],
            round(ceiling_score * score_scale) * ceiling[index],
        ))
    # A modest quadratic cost around three shared players discourages one pair
    # from consuming the core while another pair becomes needlessly disjoint.
    model.maximize(
        sum(role_scores)
        - sum(overlap_squared * 100 * variable for overlap_squared, variable in pair_penalties)
    )

    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 8
    solver.parameters.max_time_in_seconds = 15
    status = solver.solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise LineupOptimizationError(
            "no three-lineup portfolio satisfies the exposure and uniqueness constraints"
        )
    balanced_lineups = [
        candidates[index] for index in range(len(candidates)) if solver.value(balanced[index])
    ]
    ceiling_lineup = next(
        candidates[index] for index in range(len(candidates)) if solver.value(ceiling[index])
    )
    return tuple(balanced_lineups + [ceiling_lineup])


def _optimize_classic_lineup(
    slate: Slate,
    projection_matches: ProjectionMatchResult,
    rules: RosterRules | None,
    settings: ClassicOptimizationSettings,
    prior_lineups: tuple[tuple[frozenset[str], int], ...],
    prior_stack_combinations: tuple[tuple[str, str, str], ...],
    exposure_counts: dict[str, int],
) -> OptimizedLineup:
    rules = rules or classic_rules_for(slate.platform)
    if rules.platform != slate.platform:
        raise LineupOptimizationError("roster rules platform does not match the slate")
    if rules.contest_format != slate.contest_format:
        raise LineupOptimizationError("roster rules format does not match the slate")

    projected_players = tuple(
        player
        for player in slate.players
        if player.platform_id in projection_matches.by_player_id
        and player.platform_id not in settings.excluded_player_ids
    )
    if len(projected_players) < rules.lineup_size:
        raise LineupOptimizationError(
            f"only {len(projected_players)} salary players have projections; "
            f"at least {rules.lineup_size} are required"
        )

    model = cp_model.CpModel()
    assignments: dict[tuple[int, int], cp_model.IntVar] = {}

    for slot_index, slot in enumerate(rules.slots):
        eligible = []
        for player_index, player in enumerate(projected_players):
            if _eligible(player, slot):
                variable = model.new_bool_var(f"slot_{slot_index}_player_{player_index}")
                assignments[(slot_index, player_index)] = variable
                eligible.append(variable)
        if not eligible:
            raise LineupOptimizationError(f"no projected players are eligible for {slot.name}")
        model.add_exactly_one(eligible)

    for player_index in range(len(projected_players)):
        player_assignments = [
            variable
            for (slot_index, index), variable in assignments.items()
            if index == player_index
        ]
        model.add_at_most_one(player_assignments)

    selected: dict[int, cp_model.IntVar] = {}
    for player_index, player in enumerate(projected_players):
        variable = model.new_bool_var(f"selected_{player_index}")
        model.add(variable == sum(
            assignment for (slot_index, index), assignment in assignments.items()
            if index == player_index
        ))
        selected[player_index] = variable

    available_ids = {player.platform_id for player in projected_players}
    unknown_locks = settings.locked_player_ids - available_ids
    if unknown_locks:
        raise LineupOptimizationError(
            "locked players are unavailable or lack projections: " + ", ".join(sorted(unknown_locks))
        )
    for player_index, player in enumerate(projected_players):
        if player.platform_id in settings.locked_player_ids:
            model.add(selected[player_index] == 1)

    pass_catcher_positions = {"WR", "TE"}
    offensive_positions = {"QB", "RB", "WR", "TE"}
    for qb_index, qb in enumerate(projected_players):
        if qb.primary_position.value != "QB":
            continue
        if settings.qb_stack_size:
            teammates = [
                selected[index] for index, player in enumerate(projected_players)
                if player.team == qb.team and player.primary_position.value in pass_catcher_positions
                and projection_matches.by_player_id[player.platform_id].projected_points
                >= settings.minimum_stack_projection
                and (projection_matches.by_player_id[player.platform_id].ceiling
                     or projection_matches.by_player_id[player.platform_id].projected_points)
                >= settings.minimum_stack_ceiling
            ]
            model.add(sum(teammates) >= settings.qb_stack_size * selected[qb_index])
        if settings.require_opponent_bring_back:
            opponents = [
                selected[index] for index, player in enumerate(projected_players)
                if player.team == qb.opponent and player.primary_position.value in offensive_positions
                and projection_matches.by_player_id[player.platform_id].projected_points
                >= settings.minimum_bring_back_projection
                and (projection_matches.by_player_id[player.platform_id].ceiling
                     or projection_matches.by_player_id[player.platform_id].projected_points)
                >= settings.minimum_bring_back_ceiling
            ]
            model.add(sum(opponents) >= selected[qb_index])

    if settings.avoid_dst_opponents:
        for dst_index, dst in enumerate(projected_players):
            if dst.primary_position.value != "DST":
                continue
            for offense_index, offense in enumerate(projected_players):
                if offense.team == dst.opponent and offense.primary_position.value in offensive_positions:
                    model.add(selected[dst_index] + selected[offense_index] <= 1)

    for previous_ids, minimum_unique in prior_lineups:
        overlap = [
            selected[index] for index, player in enumerate(projected_players)
            if player.platform_id in previous_ids
        ]
        model.add(sum(overlap) <= rules.lineup_size - minimum_unique)

    player_indexes = {
        player.platform_id: index for index, player in enumerate(projected_players)
    }
    for quarterback_id, teammate_id, opponent_id in prior_stack_combinations:
        combination = (quarterback_id, teammate_id, opponent_id)
        if all(player_id in player_indexes for player_id in combination):
            model.add(
                sum(selected[player_indexes[player_id]] for player_id in combination) <= 2
            )

    model.add(
        sum(
            projected_players[player_index].salary * variable
            for (_, player_index), variable in assignments.items()
        )
        <= rules.salary_cap
    )

    team_variables = []
    for team in sorted({player.team for player in projected_players}):
        team_assignments = [
            variable
            for (_, player_index), variable in assignments.items()
            if projected_players[player_index].team == team
        ]
        used = model.new_bool_var(f"team_{team}")
        for variable in team_assignments:
            model.add(variable <= used)
        model.add(used <= sum(team_assignments))
        team_variables.append(used)
    model.add(sum(team_variables) >= rules.minimum_teams)

    points_scale = 1_000
    exposure_balance_penalty = round(0.25 * points_scale)
    model.maximize(
        sum(
            (
                round(_objective_points(
                    projection_matches.by_player_id[
                        projected_players[player_index].platform_id
                    ],
                    settings,
                ) * points_scale)
                - exposure_counts.get(
                    projected_players[player_index].platform_id, 0
                ) * exposure_balance_penalty
            )
            * variable
            for (_, player_index), variable in assignments.items()
        )
    )

    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 8
    solver.parameters.max_time_in_seconds = 15
    status = solver.solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise LineupOptimizationError(
            "no valid lineup satisfies the roster, team, salary, and projection constraints"
        )

    entries: list[LineupEntry] = []
    for slot_index, slot in enumerate(rules.slots):
        for player_index, player in enumerate(projected_players):
            variable = assignments.get((slot_index, player_index))
            if variable is not None and solver.value(variable):
                entries.append(
                    LineupEntry(
                        slot=slot.name,
                        player=player,
                        projection=projection_matches.by_player_id[player.platform_id],
                    )
                )
                break

    salary = sum(entry.player.salary for entry in entries)
    projected_points = sum(entry.projection.projected_points for entry in entries)
    return OptimizedLineup(
        entries=tuple(entries),
        salary=salary,
        projected_points=projected_points,
        salary_cap=rules.salary_cap,
    )


def _eligible(player: Player, slot: RosterSlot) -> bool:
    return slot.accepts(player.primary_position)


def _objective_points(projection: Projection, settings: ClassicOptimizationSettings) -> float:
    ceiling = projection.ceiling if projection.ceiling is not None else projection.projected_points
    ownership = projection.projected_ownership or 0
    return (
        projection.projected_points * (1 - settings.ceiling_weight)
        + ceiling * settings.ceiling_weight
        - ownership * settings.ownership_penalty
    )


def _stack_combinations(lineup: OptimizedLineup) -> tuple[tuple[str, str, str], ...]:
    quarterback = next(
        (entry.player for entry in lineup.entries if entry.player.primary_position == Position.QB),
        None,
    )
    if quarterback is None:
        return ()
    teammates = [
        entry.player.platform_id for entry in lineup.entries
        if entry.player.team == quarterback.team
        and entry.player.primary_position in {Position.WR, Position.TE}
    ]
    opponents = [
        entry.player.platform_id for entry in lineup.entries
        if entry.player.team == quarterback.opponent
        and entry.player.primary_position in {Position.RB, Position.WR, Position.TE}
    ]
    return tuple(
        (quarterback.platform_id, teammate_id, opponent_id)
        for teammate_id in teammates
        for opponent_id in opponents
    )
