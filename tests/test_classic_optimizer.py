from __future__ import annotations

import unittest
from collections import Counter
from dataclasses import replace

from dfs_optimizer.importers import ProjectionMatchResult
from dfs_optimizer.models import (
    ContestFormat,
    Platform,
    Player,
    Position,
    Projection,
    Slate,
)
from dfs_optimizer.optimization import (
    ClassicOptimizationSettings,
    LineupOptimizationError,
    generate_classic_3max_portfolio,
    generate_classic_lineups,
    optimize_classic_lineup,
)
from dfs_optimizer.optimization.classic import _stack_combinations


def player(
    player_id: str, position: Position, salary: int, points: float, team: str
) -> tuple[Player, Projection]:
    item = Player(
        platform_id=player_id,
        name=f"Player {player_id}",
        primary_position=position,
        roster_positions=(position,),
        salary=salary,
        team=team,
        opponent="OPP",
        game=f"{team}@OPP",
    )
    projection = Projection(
        name=item.name, team=team, projected_points=points, platform_id=player_id
    )
    return item, projection


def make_slate(platform: Platform) -> tuple[Slate, ProjectionMatchResult]:
    cap_salary = 5_000 if platform == Platform.DRAFTKINGS else 6_000
    specifications = [
        ("qb1", Position.QB, cap_salary, 25, "AAA"),
        ("qb2", Position.QB, cap_salary, 15, "BBB"),
        ("rb1", Position.RB, cap_salary, 22, "AAA"),
        ("rb2", Position.RB, cap_salary, 21, "BBB"),
        ("rb3", Position.RB, cap_salary, 20, "CCC"),
        ("rb4", Position.RB, cap_salary, 5, "DDD"),
        ("wr1", Position.WR, cap_salary, 24, "AAA"),
        ("wr2", Position.WR, cap_salary, 23, "BBB"),
        ("wr3", Position.WR, cap_salary, 19, "CCC"),
        ("wr4", Position.WR, cap_salary, 10, "DDD"),
        ("wr5", Position.WR, cap_salary, 4, "EEE"),
        ("te1", Position.TE, cap_salary, 18, "AAA"),
        ("te2", Position.TE, cap_salary, 9, "BBB"),
        ("te3", Position.TE, cap_salary, 3, "CCC"),
        ("dst1", Position.DST, cap_salary, 12, "AAA"),
        ("dst2", Position.DST, cap_salary, 8, "BBB"),
    ]
    pairs = [player(*specification) for specification in specifications]
    players = tuple(item for item, _ in pairs)
    projections = {item.platform_id: projection for item, projection in pairs}
    slate = Slate(
        platform=platform,
        contest_format=ContestFormat.CLASSIC,
        players=players,
        source_name="synthetic.csv",
    )
    return slate, ProjectionMatchResult(projections, (), ())


class ClassicOptimizerTests(unittest.TestCase):
    def test_selects_three_lineups_as_a_joint_portfolio(self) -> None:
        slate, matches = make_slate(Platform.DRAFTKINGS)
        extra_specs = (
            [(f"rbx{i}", Position.RB, 8 - i / 10, f"R{i}") for i in range(5)]
            + [(f"wrx{i}", Position.WR, 8 - i / 10, f"W{i}") for i in range(7)]
            + [(f"tex{i}", Position.TE, 8 - i / 10, f"T{i}") for i in range(3)]
            + [(f"dstx{i}", Position.DST, 8 - i / 10, f"D{i}") for i in range(2)]
        )
        extra_pairs = [
            player(player_id, position, 5_000, points, team)
            for player_id, position, points, team in extra_specs
        ]
        slate = replace(
            slate,
            players=slate.players + tuple(item for item, _ in extra_pairs),
        )
        matches = ProjectionMatchResult(
            matches.by_player_id
            | {item.platform_id: projection for item, projection in extra_pairs},
            (),
            (),
        )

        lineups = generate_classic_3max_portfolio(
            slate,
            matches,
            ClassicOptimizationSettings(),
            candidate_count=8,
        )
        appearances = Counter(
            entry.player.platform_id for lineup in lineups for entry in lineup.entries
        )
        player_sets = [
            {entry.player.platform_id for entry in lineup.entries} for lineup in lineups
        ]

        self.assertEqual(len(lineups), 3)
        self.assertLessEqual(max(appearances.values()), 2)
        for left_index, left in enumerate(player_sets):
            for right in player_sets[left_index + 1:]:
                self.assertGreaterEqual(len(left - right), 3)

    def test_builds_optimal_draftkings_lineup(self) -> None:
        slate, matches = make_slate(Platform.DRAFTKINGS)
        lineup = optimize_classic_lineup(slate, matches)

        self.assertEqual(len(lineup.entries), 9)
        self.assertEqual(lineup.salary, 45_000)
        self.assertEqual(lineup.projected_points, 184)
        self.assertEqual(len({entry.player.platform_id for entry in lineup.entries}), 9)
        self.assertGreaterEqual(len({entry.player.team for entry in lineup.entries}), 2)

    def test_builds_optimal_fanduel_lineup(self) -> None:
        slate, matches = make_slate(Platform.FANDUEL)
        lineup = optimize_classic_lineup(slate, matches)

        self.assertEqual(len(lineup.entries), 9)
        self.assertEqual(lineup.salary, 54_000)
        self.assertLessEqual(lineup.salary, 60_000)

    def test_rejects_too_few_projected_players(self) -> None:
        slate, matches = make_slate(Platform.DRAFTKINGS)
        reduced = ProjectionMatchResult(
            dict(list(matches.by_player_id.items())[:8]), (), slate.players[8:]
        )
        with self.assertRaisesRegex(LineupOptimizationError, "at least 9"):
            optimize_classic_lineup(slate, reduced)

    def test_honors_locks_and_exclusions(self) -> None:
        slate, matches = make_slate(Platform.DRAFTKINGS)
        settings = ClassicOptimizationSettings(
            locked_player_ids=frozenset({"qb2"}),
            excluded_player_ids=frozenset({"wr1"}),
        )
        lineup = optimize_classic_lineup(slate, matches, settings=settings)
        ids = {entry.player.platform_id for entry in lineup.entries}

        self.assertIn("qb2", ids)
        self.assertNotIn("wr1", ids)

    def test_requires_qb_pass_catcher_stack(self) -> None:
        slate, matches = make_slate(Platform.DRAFTKINGS)
        settings = ClassicOptimizationSettings(qb_stack_size=2)
        lineup = optimize_classic_lineup(slate, matches, settings=settings)
        qb = next(entry.player for entry in lineup.entries if entry.player.primary_position == Position.QB)
        pass_catchers = [
            entry for entry in lineup.entries
            if entry.player.team == qb.team
            and entry.player.primary_position in {Position.WR, Position.TE}
        ]
        self.assertGreaterEqual(len(pass_catchers), 2)

    def test_generates_lineups_with_minimum_uniqueness(self) -> None:
        slate, matches = make_slate(Platform.DRAFTKINGS)
        lineups = generate_classic_lineups(
            slate, matches, count=3, minimum_unique_players=2
        )

        self.assertEqual(len(lineups), 3)
        ids = [{entry.player.platform_id for entry in lineup.entries} for lineup in lineups]
        for left_index, left in enumerate(ids):
            for right in ids[left_index + 1 :]:
                self.assertGreaterEqual(len(left - right), 2)

    def test_rejects_unavailable_lock(self) -> None:
        slate, matches = make_slate(Platform.DRAFTKINGS)
        with self.assertRaisesRegex(LineupOptimizationError, "locked players"):
            optimize_classic_lineup(
                slate,
                matches,
                settings=ClassicOptimizationSettings(
                    locked_player_ids=frozenset({"missing"})
                ),
            )

    def test_enforces_portfolio_exposure_cap(self) -> None:
        slate, matches = make_slate(Platform.DRAFTKINGS)
        balanced_matches = ProjectionMatchResult(
            {
                player_id: Projection(
                    name=projection.name,
                    team=projection.team,
                    projected_points=10,
                    platform_id=player_id,
                )
                for player_id, projection in matches.by_player_id.items()
            },
            (),
            (),
        )
        lineups = generate_classic_lineups(
            slate,
            balanced_matches,
            count=4,
            minimum_unique_players=1,
            maximum_player_exposure=0.75,
        )
        appearances: dict[str, int] = {}
        for lineup in lineups:
            for entry in lineup.entries:
                player_id = entry.player.platform_id
                appearances[player_id] = appearances.get(player_id, 0) + 1

        self.assertTrue(appearances)
        self.assertEqual(len(lineups), 4)
        self.assertLessEqual(max(appearances.values()), 3)

    def test_fractional_exposure_never_exceeds_requested_maximum(self) -> None:
        slate, matches = make_slate(Platform.DRAFTKINGS)

        lineups = generate_classic_lineups(
            slate,
            matches,
            count=3,
            minimum_unique_players=1,
            maximum_player_exposure=0.67,
        )
        appearances = Counter(
            entry.player.platform_id for lineup in lineups for entry in lineup.entries
        )

        self.assertGreaterEqual(len(lineups), 2)
        self.assertLessEqual(max(appearances.values()), 2)

    def test_lock_overrides_portfolio_exposure_cap(self) -> None:
        slate, matches = make_slate(Platform.DRAFTKINGS)
        extra_pairs = [
            player("rb5", Position.RB, 5_000, 8, "EEE"),
            player("rb6", Position.RB, 5_000, 7, "FFF"),
            player("wr6", Position.WR, 5_000, 8, "FFF"),
            player("wr7", Position.WR, 5_000, 7, "GGG"),
            player("te4", Position.TE, 5_000, 7, "GGG"),
            player("dst3", Position.DST, 5_000, 7, "CCC"),
        ]
        slate = replace(
            slate,
            players=slate.players + tuple(item for item, _ in extra_pairs),
        )
        matches = ProjectionMatchResult(
            matches.by_player_id
            | {item.platform_id: projection for item, projection in extra_pairs},
            (),
            (),
        )

        lineups = generate_classic_lineups(
            slate,
            matches,
            count=3,
            minimum_unique_players=1,
            maximum_player_exposure=0.67,
            settings=ClassicOptimizationSettings(
                locked_player_ids=frozenset({"qb1"})
            ),
        )
        appearances = Counter(
            entry.player.platform_id for lineup in lineups for entry in lineup.entries
        )

        self.assertEqual(len(lineups), 3)
        self.assertEqual(appearances["qb1"], 3)
        self.assertLessEqual(
            max(count for player_id, count in appearances.items() if player_id != "qb1"),
            2,
        )

    def test_enforces_separate_qb_exposure_cap(self) -> None:
        slate, matches = make_slate(Platform.DRAFTKINGS)

        lineups = generate_classic_lineups(
            slate,
            matches,
            count=3,
            minimum_unique_players=1,
            maximum_player_exposure=1,
            maximum_qb_exposure=0.67,
        )
        quarterbacks = Counter(
            entry.player.platform_id
            for lineup in lineups
            for entry in lineup.entries
            if entry.player.primary_position == Position.QB
        )

        self.assertEqual(len(lineups), 3)
        self.assertLessEqual(max(quarterbacks.values()), 2)

    def test_enforces_separate_dst_exposure_cap(self) -> None:
        slate, matches = make_slate(Platform.DRAFTKINGS)

        lineups = generate_classic_lineups(
            slate,
            matches,
            count=3,
            minimum_unique_players=1,
            maximum_player_exposure=1,
            maximum_dst_exposure=0.67,
        )
        defenses = Counter(
            entry.player.platform_id
            for lineup in lineups
            for entry in lineup.entries
            if entry.player.primary_position == Position.DST
        )

        self.assertEqual(len(lineups), 3)
        self.assertLessEqual(max(defenses.values()), 2)

    def test_stack_partner_must_clear_projection_minimum(self) -> None:
        slate, matches = make_slate(Platform.DRAFTKINGS)

        lineup = optimize_classic_lineup(
            slate,
            matches,
            settings=ClassicOptimizationSettings(
                qb_stack_size=1,
                minimum_stack_projection=20,
            ),
        )
        quarterback = next(
            entry.player for entry in lineup.entries
            if entry.player.primary_position == Position.QB
        )
        qualifying_teammates = [
            entry for entry in lineup.entries
            if entry.player.team == quarterback.team
            and entry.player.primary_position in {Position.WR, Position.TE}
            and entry.projection.projected_points >= 20
        ]

        self.assertTrue(qualifying_teammates)

    def test_rejects_stack_when_no_partner_clears_ceiling(self) -> None:
        slate, matches = make_slate(Platform.DRAFTKINGS)

        with self.assertRaises(LineupOptimizationError):
            optimize_classic_lineup(
                slate,
                matches,
                settings=ClassicOptimizationSettings(
                    qb_stack_size=1,
                    minimum_stack_ceiling=25,
                ),
            )

    def test_prevents_repeated_primary_stack_combination(self) -> None:
        slate, matches = make_slate(Platform.DRAFTKINGS)
        slate = replace(
            slate,
            players=tuple(
                replace(
                    player,
                    opponent="BBB" if player.team == "AAA" else "AAA",
                    game="AAA@BBB",
                )
                for player in slate.players
            ),
        )

        lineups = generate_classic_lineups(
            slate,
            matches,
            count=2,
            settings=ClassicOptimizationSettings(
                qb_stack_size=1,
                require_opponent_bring_back=True,
                unique_primary_stacks=True,
                avoid_dst_opponents=False,
            ),
        )

        self.assertEqual(len(lineups), 2)
        self.assertFalse(set(_stack_combinations(lineups[0])) & set(_stack_combinations(lineups[1])))

    def test_can_optimize_for_ceiling_instead_of_median(self) -> None:
        slate, matches = make_slate(Platform.DRAFTKINGS)
        ceiling_matches = replace(
            matches,
            by_player_id={
                player_id: replace(
                    projection,
                    ceiling=50 if player_id == "qb2" else projection.projected_points,
                )
                for player_id, projection in matches.by_player_id.items()
            },
        )

        lineup = optimize_classic_lineup(
            slate,
            ceiling_matches,
            settings=ClassicOptimizationSettings(ceiling_weight=1),
        )

        ids = {entry.player.platform_id for entry in lineup.entries}
        self.assertIn("qb2", ids)

    def test_can_assign_a_different_ceiling_objective_to_each_lineup(self) -> None:
        slate, matches = make_slate(Platform.DRAFTKINGS)
        ceiling_matches = replace(
            matches,
            by_player_id={
                player_id: replace(
                    projection,
                    ceiling=50 if player_id == "qb2" else projection.projected_points,
                )
                for player_id, projection in matches.by_player_id.items()
            },
        )

        lineups = generate_classic_lineups(
            slate,
            ceiling_matches,
            count=2,
            minimum_unique_players=1,
            lineup_ceiling_weights=(0, 1),
        )

        quarterbacks = [
            next(
                entry.player.platform_id
                for entry in lineup.entries
                if entry.player.primary_position == Position.QB
            )
            for lineup in lineups
        ]
        self.assertEqual(quarterbacks, ["qb1", "qb2"])

    def test_can_penalize_high_projected_ownership(self) -> None:
        slate, matches = make_slate(Platform.DRAFTKINGS)
        ownership_matches = replace(
            matches,
            by_player_id={
                player_id: replace(
                    projection,
                    projected_ownership=100 if player_id == "qb1" else 0,
                )
                for player_id, projection in matches.by_player_id.items()
            },
        )

        lineup = optimize_classic_lineup(
            slate,
            ownership_matches,
            settings=ClassicOptimizationSettings(ownership_penalty=0.2),
        )

        ids = {entry.player.platform_id for entry in lineup.entries}
        self.assertIn("qb2", ids)


if __name__ == "__main__":
    unittest.main()
