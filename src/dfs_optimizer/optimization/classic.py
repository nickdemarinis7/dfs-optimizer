from __future__ import annotations

from dataclasses import dataclass, replace
import math

from ortools.sat.python import cp_model

from dfs_optimizer.importers import ProjectionMatchResult
from dfs_optimizer.models import Player, Position, Projection, Slate
from dfs_optimizer.rules import RosterRules, RosterSlot, classic_rules_for


CLASSIC_SOLVER_TIME_LIMIT_SECONDS = 5
CLASSIC_SOLVER_RELATIVE_GAP = .01


class LineupOptimizationError(ValueError):
    """Raised when inputs cannot produce a valid Classic lineup."""


@dataclass(frozen=True, slots=True)
class ClassicOptimizationSettings:
    locked_player_ids: frozenset[str] = frozenset()
    excluded_player_ids: frozenset[str] = frozenset()
    limited_player_ids: frozenset[str] = frozenset()
    player_exposure_limits: tuple[tuple[str, float], ...] = ()
    fragile_player_ids: frozenset[str] = frozenset()
    maximum_fragile_players: int | None = None
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
    minimum_quarterbacks: int = 0
    minimum_projected_points: float = 0.0
    maximum_bust_risk_players: int | None = None
    bust_risk_threshold: float = .375
    maximum_severe_bust_players: int | None = None
    severe_bust_risk_threshold: float = .60
    second_tight_end_minimum_projection: float = 0.0
    second_tight_end_minimum_floor: float = 0.0
    second_tight_end_maximum_bust_probability: float = 1.0
    require_bring_back_for_four_player_team: bool = False
    avoid_opposing_running_backs: bool = False

    def __post_init__(self) -> None:
        if self.locked_player_ids & self.excluded_player_ids:
            raise ValueError("a player cannot be both locked and excluded")
        if self.locked_player_ids & self.limited_player_ids:
            raise ValueError("a locked player cannot be limited to one lineup")
        exposure_ids = [player_id for player_id, _ in self.player_exposure_limits]
        if len(exposure_ids) != len(set(exposure_ids)):
            raise ValueError("player exposure limits cannot contain duplicate player ids")
        if any(not 0 < limit <= 1 for _, limit in self.player_exposure_limits):
            raise ValueError("player exposure limits must be greater than 0 and at most 1")
        if self.locked_player_ids & set(exposure_ids):
            raise ValueError("a locked player cannot have a player-specific exposure limit")
        if self.maximum_fragile_players is not None and self.maximum_fragile_players < 0:
            raise ValueError("maximum_fragile_players cannot be negative")
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
        if self.minimum_quarterbacks < 0:
            raise ValueError("minimum_quarterbacks cannot be negative")
        if self.minimum_projected_points < 0:
            raise ValueError("minimum_projected_points cannot be negative")
        if self.maximum_bust_risk_players is not None and self.maximum_bust_risk_players < 0:
            raise ValueError("maximum_bust_risk_players cannot be negative")
        if not 0 <= self.bust_risk_threshold <= 1:
            raise ValueError("bust_risk_threshold must be between 0 and 1")
        if self.maximum_severe_bust_players is not None and self.maximum_severe_bust_players < 0:
            raise ValueError("maximum_severe_bust_players cannot be negative")
        if not 0 <= self.severe_bust_risk_threshold <= 1:
            raise ValueError("severe_bust_risk_threshold must be between 0 and 1")
        if self.second_tight_end_minimum_projection < 0:
            raise ValueError("second_tight_end_minimum_projection cannot be negative")
        if self.second_tight_end_minimum_floor < 0:
            raise ValueError("second_tight_end_minimum_floor cannot be negative")
        if not 0 <= self.second_tight_end_maximum_bust_probability <= 1:
            raise ValueError(
                "second_tight_end_maximum_bust_probability must be between 0 and 1"
            )


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
    minimum_projection_ratio: float = 0.0,
) -> tuple[OptimizedLineup, ...]:
    if count < 1:
        raise ValueError("lineup count must be at least 1")
    resolved_rules = rules or classic_rules_for(slate.platform, slate.sport)
    if not 1 <= minimum_unique_players <= resolved_rules.lineup_size:
        raise ValueError("minimum_unique_players must be between 1 and lineup size")
    if not 0 < maximum_player_exposure <= 1:
        raise ValueError("maximum_player_exposure must be greater than 0 and at most 1")
    if not 0 < maximum_qb_exposure <= 1:
        raise ValueError("maximum_qb_exposure must be greater than 0 and at most 1")
    if not 0 < maximum_dst_exposure <= 1:
        raise ValueError("maximum_dst_exposure must be greater than 0 and at most 1")
    if not 0 <= minimum_projection_ratio <= 1:
        raise ValueError("minimum_projection_ratio must be between 0 and 1")
    if lineup_ceiling_weights is not None:
        if len(lineup_ceiling_weights) != count:
            raise ValueError("lineup_ceiling_weights must contain one value per lineup")
        if any(not 0 <= weight <= 1 for weight in lineup_ceiling_weights):
            raise ValueError("lineup ceiling weights must be between 0 and 1")
    base_settings = settings or ClassicOptimizationSettings()
    player_exposure_limits = dict(base_settings.player_exposure_limits)
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
                or (
                    player_id in player_exposure_limits
                    and appearances_so_far >= max(
                        1, math.floor(count * player_exposure_limits[player_id])
                    )
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
            minimum_projected_points=max(
                base_settings.minimum_projected_points,
                lineups[0].projected_points * minimum_projection_ratio
                if lineups else 0,
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
    candidate_count: int = 8,
    minimum_projection_ratio: float = .92,
    candidate_diagnostics: dict | None = None,
) -> tuple[OptimizedLineup, ...]:
    """Select two balanced lineups and one ceiling lineup as a single portfolio.

    Eight candidates per objective gives the joint selector sixteen distinct
    constructions to choose from.  The previous twenty-per-objective search
    could launch forty sequential CP-SAT solves for only three final entries,
    causing multi-minute waits with little practical portfolio benefit.
    """
    if candidate_count < 3:
        raise ValueError("candidate_count must be at least 3")
    if not 0 <= minimum_projection_ratio <= 1:
        raise ValueError("minimum_projection_ratio must be between 0 and 1")
    rules = classic_rules_for(slate.platform, slate.sport)
    balanced_settings = replace(
        settings,
        ceiling_weight=0.30,
        maximum_bust_risk_players=(
            4 if settings.maximum_bust_risk_players is None
            else settings.maximum_bust_risk_players
        ),
        maximum_severe_bust_players=(
            0 if settings.maximum_severe_bust_players is None
            else settings.maximum_severe_bust_players
        ),
    )
    ceiling_settings = replace(
        settings,
        ceiling_weight=0.70,
        # Most top Classic lineups use a bring-back, but not all do. Preserve
        # it in both balanced entries and let the dedicated ceiling entry win
        # without one when the slate's strongest construction demands it.
        require_opponent_bring_back=False,
        maximum_bust_risk_players=(
            5 if settings.maximum_bust_risk_players is None
            else settings.maximum_bust_risk_players
        ),
        maximum_severe_bust_players=(
            1 if settings.maximum_severe_bust_players is None
            else settings.maximum_severe_bust_players
        ),
    )
    ceiling_bring_back_settings = replace(
        ceiling_settings,
        require_opponent_bring_back=settings.require_opponent_bring_back,
    )
    candidates_by_ids: dict[frozenset[str], OptimizedLineup] = {}
    candidate_searches = [
        (balanced_settings, candidate_count),
        (ceiling_bring_back_settings, candidate_count),
    ]
    if settings.require_opponent_bring_back:
        # Add a small alternative pool rather than replacing the normal
        # ceiling search. This preserves strong bring-back constructions while
        # allowing the third entry to exploit the minority of winning scripts
        # that do not need one, without adding another full expensive search.
        candidate_searches.append((ceiling_settings, 3))
    for candidate_settings, search_count in candidate_searches:
        for lineup in generate_classic_lineups(
            slate,
            projection_matches,
            search_count,
            minimum_unique_players=1,
            rules=rules,
            settings=replace(candidate_settings, limited_player_ids=frozenset()),
            maximum_player_exposure=0.50,
            maximum_qb_exposure=0.50,
            # The final 3-max portfolio uses three different defenses. Seed
            # that diversity while building candidates; otherwise the first
            # several sequential candidates can all consume the same two
            # defenses and force the joint selector into a weak third lineup.
            maximum_dst_exposure=0.25,
        ):
            ids = frozenset(entry.player.platform_id for entry in lineup.entries)
            candidates_by_ids.setdefault(ids, lineup)
    candidates = tuple(candidates_by_ids.values())
    if len(candidates) < 3:
        raise LineupOptimizationError(
            "not enough distinct candidate lineups to build a 3-max portfolio"
        )
    if candidate_diagnostics is not None:
        candidate_player_ids = set().union(*(
            {entry.player.platform_id for entry in lineup.entries}
            for lineup in candidates
        ))
        projected_players = [
            (player, projection_matches.by_player_id.get(player.platform_id))
            for player in slate.players
            if player.platform_id not in settings.excluded_player_ids
        ]
        projected_players = [item for item in projected_players if item[1] is not None]
        absent = sorted(
            (
                (player.name, player.primary_position.value, projection.ceiling or 0)
                for player, projection in projected_players
                if player.platform_id not in candidate_player_ids
                and player.primary_position != Position.DST
            ),
            key=lambda item: item[2], reverse=True,
        )[:8]
        candidate_diagnostics.update({
            "candidate_count": len(candidates),
            "player_coverage": (
                len(candidate_player_ids) / max(1, len(projected_players))
            ),
            "quarterbacks_considered": len({
                entry.player.platform_id
                for lineup in candidates for entry in lineup.entries
                if entry.player.primary_position == Position.QB
            }),
            "high_ceiling_absences": tuple(
                {"player": name, "position": position, "ceiling": ceiling}
                for name, position, ceiling in absent
            ),
        })
    projection_floor = max(
        lineup.projected_points for lineup in candidates
    ) * minimum_projection_ratio
    from dfs_optimizer.services.scenarios import simulate_lineups
    scenario_analysis = simulate_lineups(candidates, simulations=750)

    model = cp_model.CpModel()
    balanced = [model.new_bool_var(f"balanced_{index}") for index in range(len(candidates))]
    ceiling = [model.new_bool_var(f"ceiling_{index}") for index in range(len(candidates))]
    selected = []
    player_sets = []
    for index, lineup in enumerate(candidates):
        model.add(balanced[index] + ceiling[index] <= 1)
        quarterback = next(
            (
                entry.player for entry in lineup.entries
                if entry.player.primary_position == Position.QB
            ),
            None,
        )
        has_bring_back = quarterback is not None and any(
            entry.player.team == quarterback.opponent
            and entry.player.primary_position in {
                Position.RB, Position.WR, Position.TE
            }
            for entry in lineup.entries
        )
        if settings.require_opponent_bring_back and not has_bring_back:
            model.add(balanced[index] == 0)
        balanced_bust_count = sum(
            (entry.projection.bust_probability or 0)
            >= balanced_settings.bust_risk_threshold
            for entry in lineup.entries
        )
        balanced_severe_count = sum(
            (entry.projection.bust_probability or 0)
            >= balanced_settings.severe_bust_risk_threshold
            for entry in lineup.entries
        )
        ceiling_bust_count = sum(
            (entry.projection.bust_probability or 0)
            >= ceiling_settings.bust_risk_threshold
            for entry in lineup.entries
        )
        ceiling_severe_count = sum(
            (entry.projection.bust_probability or 0)
            >= ceiling_settings.severe_bust_risk_threshold
            for entry in lineup.entries
        )
        if (
            balanced_settings.maximum_bust_risk_players is not None
            and balanced_bust_count > balanced_settings.maximum_bust_risk_players
        ) or (
            balanced_settings.maximum_severe_bust_players is not None
            and balanced_severe_count > balanced_settings.maximum_severe_bust_players
        ):
            model.add(balanced[index] == 0)
        if (
            ceiling_settings.maximum_bust_risk_players is not None
            and ceiling_bust_count > ceiling_settings.maximum_bust_risk_players
        ) or (
            ceiling_settings.maximum_severe_bust_players is not None
            and ceiling_severe_count > ceiling_settings.maximum_severe_bust_players
        ):
            model.add(ceiling[index] == 0)
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
        specific_limit = dict(settings.player_exposure_limits).get(player_id)
        if specific_limit is not None:
            appearance_limit = min(
                appearance_limit, max(1, math.floor(3 * specific_limit))
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
    quality_penalties = []
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
        projection_shortfall = max(0.0, projection_floor - lineup.projected_points)
        quality_penalties.append(
            round(projection_shortfall * score_scale * 5) * selected[index]
        )
    # A modest quadratic cost around three shared players discourages one pair
    # from consuming the core while another pair becomes needlessly disjoint.
    model.maximize(
        sum(role_scores)
        - sum(overlap_squared * 100 * variable for overlap_squared, variable in pair_penalties)
        - sum(quality_penalties)
    )

    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 0
    solver.parameters.max_time_in_seconds = CLASSIC_SOLVER_TIME_LIMIT_SECONDS
    solver.parameters.relative_gap_limit = CLASSIC_SOLVER_RELATIVE_GAP
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
    if candidate_diagnostics is not None:
        candidate_diagnostics["selected_projection_range"] = (
            min(lineup.projected_points for lineup in balanced_lineups + [ceiling_lineup]),
            max(lineup.projected_points for lineup in balanced_lineups + [ceiling_lineup]),
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
    rules = rules or classic_rules_for(slate.platform, slate.sport)
    if rules.platform != slate.platform:
        raise LineupOptimizationError("roster rules platform does not match the slate")
    if rules.contest_format != slate.contest_format:
        raise LineupOptimizationError("roster rules format does not match the slate")
    if rules.sport != slate.sport:
        raise LineupOptimizationError("roster rules sport does not match the slate")

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

    if settings.maximum_fragile_players is not None:
        model.add(
            sum(
                selected[index]
                for index, player in enumerate(projected_players)
                if player.platform_id in settings.fragile_player_ids
            )
            <= settings.maximum_fragile_players
        )

    if settings.maximum_bust_risk_players is not None:
        model.add(
            sum(
                selected[index]
                for index, player in enumerate(projected_players)
                if (
                    projection_matches.by_player_id[player.platform_id].bust_probability
                    or 0
                ) >= settings.bust_risk_threshold
            )
            <= settings.maximum_bust_risk_players
        )

    if settings.maximum_severe_bust_players is not None:
        model.add(
            sum(
                selected[index]
                for index, player in enumerate(projected_players)
                if (
                    projection_matches.by_player_id[player.platform_id].bust_probability
                    or 0
                ) >= settings.severe_bust_risk_threshold
            )
            <= settings.maximum_severe_bust_players
        )

    # A cheap or volatile TE may still fill the required TE slot, but should
    # not also invite a second TE into FLEX. Double-TE remains available when
    # every selected TE has a credible independent role and floor.
    tight_end_indexes = [
        index for index, player in enumerate(projected_players)
        if player.primary_position == Position.TE
    ]
    risky_flex_tight_ends = [
        index for index in tight_end_indexes
        if (
            projection_matches.by_player_id[
                projected_players[index].platform_id
            ].projected_points < settings.second_tight_end_minimum_projection
            or (
                projection_matches.by_player_id[
                    projected_players[index].platform_id
                ].floor or 0
            ) < settings.second_tight_end_minimum_floor
            or (
                projection_matches.by_player_id[
                    projected_players[index].platform_id
                ].bust_probability or 0
            ) > settings.second_tight_end_maximum_bust_probability
        )
    ]
    for risky_index in risky_flex_tight_ends:
        model.add(
            selected[risky_index]
            + sum(selected[index] for index in tight_end_indexes if index != risky_index)
            <= 1
        )

    if settings.minimum_quarterbacks:
        model.add(
            sum(
                selected[index]
                for index, player in enumerate(projected_players)
                if player.primary_position == Position.QB
            )
            >= settings.minimum_quarterbacks
        )

    if settings.minimum_projected_points:
        points_scale = 1_000
        model.add(
            sum(
                round(
                    projection_matches.by_player_id[player.platform_id].projected_points
                    * points_scale
                ) * selected[index]
                for index, player in enumerate(projected_players)
            )
            >= round(settings.minimum_projected_points * points_scale)
        )

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

    if settings.avoid_opposing_running_backs:
        running_backs = [
            (index, player) for index, player in enumerate(projected_players)
            if player.primary_position == Position.RB
        ]
        for left, (left_index, left_player) in enumerate(running_backs):
            for right_index, right_player in running_backs[left + 1:]:
                if left_player.team == right_player.opponent:
                    model.add(selected[left_index] + selected[right_index] <= 1)

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
        if rules.maximum_players_per_team is not None:
            model.add(sum(team_assignments) <= rules.maximum_players_per_team)
        if settings.require_bring_back_for_four_player_team:
            opponent_assignments = [
                selected[index]
                for index, player in enumerate(projected_players)
                if player.team != team
                and player.opponent == team
                and player.primary_position in {
                    Position.QB, Position.RB, Position.WR, Position.TE
                }
            ]
            if opponent_assignments:
                model.add(sum(team_assignments) <= 3 + sum(opponent_assignments))
            else:
                model.add(sum(team_assignments) <= 3)
        team_variables.append(used)
    model.add(sum(team_variables) >= rules.minimum_teams)

    if rules.minimum_games:
        game_variables = []
        for game in sorted({player.game for player in projected_players}):
            game_assignments = [
                variable
                for (_, player_index), variable in assignments.items()
                if projected_players[player_index].game == game
            ]
            used = model.new_bool_var(f"game_{len(game_variables)}")
            for variable in game_assignments:
                model.add(variable <= used)
            model.add(used <= sum(game_assignments))
            game_variables.append(used)
        model.add(sum(game_variables) >= rules.minimum_games)

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
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 0
    solver.parameters.max_time_in_seconds = CLASSIC_SOLVER_TIME_LIMIT_SECONDS
    solver.parameters.relative_gap_limit = CLASSIC_SOLVER_RELATIVE_GAP
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
