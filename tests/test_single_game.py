from __future__ import annotations

import unittest
from pathlib import Path

from dfs_optimizer.importers import import_salary_csv, match_projections
from dfs_optimizer.models import ContestFormat, Platform, Position
from dfs_optimizer.optimization import (
    SingleGameOptimizationSettings,
    generate_single_game_3max_portfolio,
    generate_single_game_lineups,
    optimize_single_game_lineup,
)
from dfs_optimizer.projections import build_platform_average_projections


ROOT = Path(__file__).resolve().parents[1]


class SingleGameTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.dk = import_salary_csv(ROOT / "samples" / "DKSalaries (1).csv")
        cls.fd = import_salary_csv(next((ROOT / "samples").glob("*134921-players-list.csv")))

    def test_detects_and_collapses_draftkings_showdown_rows(self) -> None:
        self.assertEqual(self.dk.platform, Platform.DRAFTKINGS)
        self.assertEqual(self.dk.contest_format, ContestFormat.SINGLE_GAME)
        self.assertEqual(len(self.dk.players), 56)
        self.assertEqual(len({player.platform_id for player in self.dk.players}), 56)
        self.assertTrue(any(player.primary_position == Position.K for player in self.dk.players))
        self.assertTrue(all(player.multiplier_platform_id for player in self.dk.players))

    def test_detects_fanduel_single_game(self) -> None:
        self.assertEqual(self.fd.platform, Platform.FANDUEL)
        self.assertEqual(self.fd.contest_format, ContestFormat.SINGLE_GAME)
        self.assertEqual(len(self.fd.players), 51)
        self.assertTrue(all(player.multiplier_salary for player in self.fd.players))

    def test_optimizes_both_single_game_formats(self) -> None:
        for slate, cap, multiplier_slot in ((self.dk, 50_000, "CPT"), (self.fd, 60_000, "MVP")):
            with self.subTest(platform=slate.platform):
                projections = build_platform_average_projections(slate)
                lineup = optimize_single_game_lineup(slate, match_projections(slate, projections))
                self.assertEqual(len(lineup.entries), 6)
                self.assertEqual(lineup.entries[0].slot, multiplier_slot)
                self.assertLessEqual(lineup.salary, cap)
                self.assertEqual(len({entry.player.name for entry in lineup.entries}), 6)
                self.assertEqual(len({entry.player.team for entry in lineup.entries}), 2)

    def test_generates_unique_lineups_with_multiplier_exposure(self) -> None:
        projections = build_platform_average_projections(self.dk)
        lineups = generate_single_game_lineups(
            self.dk,
            match_projections(self.dk, projections),
            count=4,
            minimum_unique_players=2,
            maximum_multiplier_exposure=0.5,
        )
        self.assertEqual(len(lineups), 4)
        multiplier_counts: dict[str, int] = {}
        for lineup in lineups:
            captain = lineup.entries[0].player.platform_id
            multiplier_counts[captain] = multiplier_counts.get(captain, 0) + 1
        self.assertLessEqual(max(multiplier_counts.values()), 2)

    def test_enforces_showdown_tournament_construction(self) -> None:
        projections = build_platform_average_projections(self.dk)
        settings = SingleGameOptimizationSettings(
            multiplier_positions=frozenset({
                Position.QB, Position.RB, Position.WR, Position.TE
            }),
            minimum_quarterbacks=1,
            minimum_quarterback_projection=5,
            minimum_player_projection=0.1,
            maximum_players_per_team=4,
            maximum_kickers_and_defenses=1,
            maximum_dst_opponents=1,
            require_multiplier_receiver_qb=True,
            ceiling_weight=0.3,
        )

        lineups = generate_single_game_lineups(
            self.dk,
            match_projections(self.dk, projections),
            count=3,
            minimum_unique_players=2,
            maximum_player_exposure=0.67,
            maximum_multiplier_exposure=0.67,
            settings=settings,
            lineup_ceiling_weights=(0.3, 0.3, 0.7),
        )

        self.assertEqual(len(lineups), 3)
        appearances: dict[str, int] = {}
        captain_appearances: dict[str, int] = {}
        for lineup in lineups:
            self.assertIn(lineup.entries[0].player.primary_position, settings.multiplier_positions)
            self.assertTrue(any(
                entry.player.primary_position == Position.QB
                and entry.projection.projected_points >= 5
                for entry in lineup.entries
            ))
            self.assertTrue(all(
                entry.projection.projected_points >= 0.1 for entry in lineup.entries
            ))
            team_counts = {
                team: sum(entry.player.team == team for entry in lineup.entries)
                for team in {entry.player.team for entry in lineup.entries}
            }
            self.assertLessEqual(max(team_counts.values()), 4)
            self.assertLessEqual(sum(
                entry.player.primary_position in {Position.K, Position.DST}
                for entry in lineup.entries
            ), 1)
            captain = lineup.entries[0].player
            if captain.primary_position in {Position.WR, Position.TE}:
                self.assertTrue(any(
                    entry.player.primary_position == Position.QB
                    and entry.player.team == captain.team
                    for entry in lineup.entries
                ))
            for entry in lineup.entries:
                if entry.player.primary_position != Position.DST:
                    continue
                opposing_offense = sum(
                    other.player.team == entry.player.opponent
                    and other.player.primary_position in {
                        Position.QB, Position.RB, Position.WR, Position.TE
                    }
                    for other in lineup.entries
                )
                self.assertLessEqual(opposing_offense, 1)
            for entry in lineup.entries:
                player_id = entry.player.platform_id
                appearances[player_id] = appearances.get(player_id, 0) + 1
            captain_id = lineup.entries[0].player.platform_id
            captain_appearances[captain_id] = captain_appearances.get(captain_id, 0) + 1
        self.assertLessEqual(max(appearances.values()), 2)
        self.assertLessEqual(max(captain_appearances.values()), 2)

    def test_joint_showdown_portfolio_makes_last_lineup_highest_ceiling(self) -> None:
        projections = build_platform_average_projections(self.dk)
        settings = SingleGameOptimizationSettings(
            multiplier_positions=frozenset({
                Position.QB, Position.RB, Position.WR, Position.TE
            }),
            minimum_quarterbacks=1,
            minimum_quarterback_projection=5,
            minimum_player_projection=0.1,
            maximum_players_per_team=4,
            maximum_kickers_and_defenses=1,
            maximum_dst_opponents=1,
            require_multiplier_receiver_qb=True,
        )

        lineups = generate_single_game_3max_portfolio(
            self.dk,
            match_projections(self.dk, projections),
            settings,
            candidate_count=24,
        )
        ceilings = [sum(
            (entry.projection.ceiling or entry.projection.projected_points)
            * entry.point_multiplier for entry in lineup.entries
        ) for lineup in lineups]

        self.assertEqual(len(lineups), 3)
        self.assertEqual(ceilings[-1], max(ceilings))
        medians = [lineup.projected_points for lineup in lineups]
        self.assertLessEqual(max(medians) - min(medians), 12)


if __name__ == "__main__":
    unittest.main()
