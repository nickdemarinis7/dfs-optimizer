from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from dfs_optimizer.models import ContestFormat, Platform, Player, Position, Projection, Slate, Sport
from dfs_optimizer.services.cfb_projections import (
    apply_cfb_game_lines,
    build_cfb_projections_from_file,
    cfb_consensus_lines_csv,
    cfb_projection_input_snapshot,
    estimate_cfb_ownership,
    infer_cfb_season,
    infer_cfb_week,
    restore_verified_cfb_starters,
    historically_verified_cfb_player_ids,
)
from dfs_optimizer.data_sources import CFBConsensusLine


class CFBProjectionTests(unittest.TestCase):
    def test_recent_repeated_usage_clears_routine_availability_gate(self) -> None:
        projections = (
            Projection(
                "Established Player", "AAA", 15, platform_id="established",
                sample_size=5, data_age_periods=0,
            ),
            Projection(
                "One Game Player", "AAA", 10, platform_id="new",
                sample_size=1, data_age_periods=0,
            ),
            Projection(
                "Stale Player", "AAA", 9, platform_id="stale",
                sample_size=5, data_age_periods=2,
            ),
        )

        verified = historically_verified_cfb_player_ids(projections)

        self.assertEqual(verified, frozenset({"established"}))

    def setUp(self) -> None:
        self.slate = Slate(
            Platform.DRAFTKINGS,
            ContestFormat.CLASSIC,
            (
                Player(
                    "qb", "Example Quarterback Jr.", Position.QB,
                    (Position.QB, Position.SUPER_FLEX), 8000,
                    "AAA", "BBB", "AAA@BBB 10/10/2026 12:00PM ET",
                    platform_average=10,
                ),
                Player(
                    "wr", "Unmatched Receiver", Position.WR,
                    (Position.WR, Position.FLEX, Position.SUPER_FLEX), 5000,
                    "AAA", "BBB", "AAA@BBB 10/10/2026 12:00PM ET",
                    platform_average=8,
                ),
            ),
            "DKSalaries-2026.csv",
            Sport.CFB,
        )

    def test_builds_recent_form_forecast_and_rejects_stale_fallback(self) -> None:
        headers = (
            "game_id,season,week,team,opponent,completion_player,completion_yds,"
            "rush_player,rush_yds,reception_player,reception_yds,target_player,"
            "interception_thrown_player,interception_thrown_stat,touchdown_player\n"
        )
        rows = (
            "1,2026,1,Alpha,Beta,Example Quarterback,100,,,,,,,,Some Receiver\n"
            "2,2026,2,Alpha,Gamma,Example Quarterback,100,,,,,,,,Some Receiver\n"
            "2,2026,2,Alpha,Gamma,Example Quarterback,100,,,,,,,,Some Receiver\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "stats.csv"
            source.write_text(headers + rows, encoding="utf-8")
            projections = build_cfb_projections_from_file(self.slate, source, 3)

        by_id = {item.platform_id: item for item in projections}
        self.assertGreater(by_id["qb"].projected_points, 10)
        self.assertNotIn("wr", by_id)
        self.assertLessEqual(by_id["qb"].p25, by_id["qb"].projected_points)
        self.assertGreaterEqual(by_id["qb"].p75, by_id["qb"].projected_points)
        self.assertIsNotNone(by_id["qb"].projected_ownership)

    def test_excludes_qb_who_missed_latest_team_game_for_another_qb(self) -> None:
        backup = replace(
            self.slate.players[0], platform_id="backup", name="Backup Quarterback"
        )
        slate = replace(self.slate, players=self.slate.players + (backup,))
        headers = (
            "game_id,season,week,team,opponent,completion_player,completion_yds,"
            "rush_player,rush_yds,reception_player,reception_yds,target_player,"
            "interception_thrown_player,interception_thrown_stat,touchdown_player\n"
        )
        rows = (
            "1,2026,1,Alpha,Beta,Backup Quarterback,150,,,,,,,,\n"
            "2,2026,2,Alpha,Gamma,Example Quarterback,200,,,,,,,,\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "stats.csv"
            source.write_text(headers + rows, encoding="utf-8")
            projections = build_cfb_projections_from_file(slate, source, 3)

        ids = {item.platform_id for item in projections}
        self.assertIn("qb", ids)
        self.assertNotIn("backup", ids)

    def test_qb_injury_absence_is_not_scored_as_zero_when_no_teammate_replaced_him(self) -> None:
        headers = (
            "game_id,season,week,team,opponent,completion_player,completion_yds,"
            "rush_player,rush_yds,reception_player,reception_yds,target_player,"
            "interception_thrown_player,interception_thrown_stat,touchdown_player\n"
        )
        rows = (
            "1,2026,1,Alpha,Beta,Example Quarterback,300,,,,,,,,\n"
            # Establish that Alpha played in Week 2 without recording another
            # slate quarterback, as happens during an injury absence.
            "2,2026,2,Alpha,Gamma,,,,,Some Receiver,20,Some Receiver,,,\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "stats.csv"
            source.write_text(headers + rows, encoding="utf-8")
            projections = build_cfb_projections_from_file(self.slate, source, 3)

        quarterback = next(
            item for item in projections if item.platform_id == "qb"
        )
        self.assertGreater(quarterback.projected_points, 10)
        self.assertGreater(quarterback.ceiling, quarterback.projected_points)

    def test_restores_only_explicitly_verified_new_starter(self) -> None:
        from dfs_optimizer.services.player_context import PlayerContext

        context = PlayerContext("wr", 1, None, None, True, 12.5)
        restored = restore_verified_cfb_starters(
            self.slate,
            (Projection(
                "Example Quarterback Jr.", "AAA", 20, platform_id="qb"
            ),),
            (context,),
        )
        by_id = {item.platform_id: item for item in restored}

        self.assertEqual(by_id["wr"].projected_points, 12.5)
        self.assertEqual(by_id["wr"].bust_probability, .45)

    def test_does_not_restore_unverified_or_inactive_player(self) -> None:
        from dfs_optimizer.services.player_context import PlayerContext

        contexts = (
            PlayerContext("wr", 1, None, None, True, None),
            PlayerContext("wr", 1, "OUT", None, False, 12.5),
        )
        for context in contexts:
            restored = restore_verified_cfb_starters(
                self.slate, (), (context,)
            )
            self.assertFalse(restored)

    def test_infers_season_from_slate_metadata(self) -> None:
        self.assertEqual(infer_cfb_season(self.slate), 2026)

    def test_infers_week_from_slate_kickoff(self) -> None:
        # cfbfastR labels the October 10, 2026 slate as Week 6.
        self.assertEqual(infer_cfb_week(self.slate), 6)

    def test_infers_week_from_fanduel_salary_filename(self) -> None:
        fanduel_slate = Slate(
            Platform.FANDUEL,
            ContestFormat.CLASSIC,
            tuple(replace(player, game="AAA@BBB") for player in self.slate.players),
            "FanDuel-CFB-2026 EDT-10 EDT-17 EDT-135105-players-list.csv",
            Sport.CFB,
        )

        self.assertEqual(infer_cfb_week(fanduel_slate), 7)

    def test_excludes_target_week_and_later_results(self) -> None:
        headers = (
            "game_id,season,week,team,opponent,completion_player,completion_yds,"
            "rush_player,rush_yds,reception_player,reception_yds,target_player,"
            "interception_thrown_player,interception_thrown_stat,touchdown_player\n"
        )
        rows = (
            "1,2026,6,Alpha,Beta,Example Quarterback,100,,,,,,,,\n"
            "2,2026,7,Alpha,Gamma,Example Quarterback,500,,,,,,,,\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "stats.csv"
            source.write_text(headers + rows, encoding="utf-8")
            projections = build_cfb_projections_from_file(self.slate, source, 7)
        quarterback = next(item for item in projections if item.platform_id == "qb")
        self.assertLess(quarterback.projected_points, 30)

    def test_fanduel_excludes_third_overtime_and_later(self) -> None:
        fanduel_slate = replace(self.slate, platform=Platform.FANDUEL)
        headers = (
            "game_id,season,week,period,team,opponent,completion_player,completion_yds,"
            "rush_player,rush_yds,reception_player,reception_yds,target_player,"
            "interception_thrown_player,interception_thrown_stat,touchdown_player\n"
        )
        regulation = "1,2026,1,4,Alpha,Beta,Example Quarterback,100,,,,,,,,\n"
        third_overtime = "1,2026,1,7,Alpha,Beta,Example Quarterback,200,,,,,,,,\n"
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "stats.csv"
            source.write_text(headers + regulation + third_overtime, encoding="utf-8")
            with_late_overtime = build_cfb_projections_from_file(
                fanduel_slate, source, 2
            )
            draftkings_with_late_overtime = build_cfb_projections_from_file(
                self.slate, source, 2
            )
            source.write_text(headers + regulation, encoding="utf-8")
            regulation_only = build_cfb_projections_from_file(
                fanduel_slate, source, 2
            )
            draftkings_regulation_only = build_cfb_projections_from_file(
                self.slate, source, 2
            )

        first = next(item for item in with_late_overtime if item.platform_id == "qb")
        second = next(item for item in regulation_only if item.platform_id == "qb")
        self.assertEqual(first.projected_points, second.projected_points)
        dk_full = next(
            item for item in draftkings_with_late_overtime
            if item.platform_id == "qb"
        )
        dk_regulation = next(
            item for item in draftkings_regulation_only
            if item.platform_id == "qb"
        )
        self.assertGreater(dk_full.projected_points, dk_regulation.projected_points)

    def test_ownership_proxy_is_bounded_for_small_slates(self) -> None:
        estimates = estimate_cfb_ownership(self.slate, (
            Projection("Example Quarterback Jr.", "AAA", 24, platform_id="qb", p90=35),
            Projection("Unmatched Receiver", "AAA", 8, platform_id="wr", p90=12),
        ))
        by_id = {item.platform_id: item for item in estimates}
        self.assertTrue(all(
            0 <= item.projected_ownership <= 55 for item in estimates
        ))
        self.assertEqual(by_id["qb"].projected_ownership, 55)

    def test_classic_ownership_scales_to_actual_cfb_roster_size(self) -> None:
        estimates = estimate_cfb_ownership(self.slate, (
            Projection("Example Quarterback Jr.", "AAA", 24, platform_id="qb", p90=35),
            Projection("Unmatched Receiver", "AAA", 8, platform_id="wr", p90=12),
        ))
        # The cap makes a tiny synthetic slate unable to absorb all 800 points,
        # but the assertion documents that DK CFB has eight—not nine—slots.
        self.assertLessEqual(
            sum(item.projected_ownership or 0 for item in estimates),
            8 * 55,
        )

    def test_low_recent_skill_opportunity_is_treated_as_fragile(self) -> None:
        player = Player(
            "rb", "Low Usage Runner", Position.RB,
            (Position.RB, Position.FLEX, Position.SUPER_FLEX), 4000,
            "AAA", "BBB", "AAA@BBB 10/10/2026 12:00PM ET",
            platform_average=10,
        )
        slate = Slate(
            Platform.DRAFTKINGS, ContestFormat.CLASSIC,
            self.slate.players + (player,), "DKSalaries-2026.csv", Sport.CFB,
        )
        headers = (
            "game_id,season,week,team,opponent,completion_player,completion_yds,"
            "rush_player,rush_yds,reception_player,reception_yds,target_player,"
            "interception_thrown_player,interception_thrown_stat,touchdown_player\n"
        )
        rows = (
            "1,2026,1,Alpha,Beta,,,Low Usage Runner,8,,,,,,\n"
            "2,2026,2,Alpha,Gamma,,,Low Usage Runner,6,,,,,,\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "stats.csv"
            source.write_text(headers + rows, encoding="utf-8")
            projections = build_cfb_projections_from_file(slate, source, 3)
        projection = next(item for item in projections if item.platform_id == "rb")
        self.assertGreaterEqual(projection.bust_probability or 0, .55)
        self.assertLessEqual(projection.p25 or 99, projection.projected_points * .35)

    def test_game_lines_apply_capped_implied_total_adjustments(self) -> None:
        slate = Slate(
            Platform.DRAFTKINGS,
            ContestFormat.CLASSIC,
            self.slate.players + (
                Player(
                    "qb2", "Other Quarterback", Position.QB,
                    (Position.QB, Position.SUPER_FLEX), 7000,
                    "BBB", "AAA", "AAA@BBB 10/10/2026 12:00PM ET",
                    platform_average=10,
                ),
            ),
            "DKSalaries-2026.csv",
            Sport.CFB,
        )
        adjusted, environments = apply_cfb_game_lines(
            slate,
            (
                Projection("Example Quarterback Jr.", "AAA", 20, platform_id="qb", p90=30),
                Projection("Other Quarterback", "BBB", 20, platform_id="qb2", p90=30),
            ),
            "team,opponent,game_total,spread\nAAA,BBB,60,-10\nBBB,AAA,60,10\n",
        )
        by_id = {item.platform_id: item for item in adjusted}
        self.assertGreater(by_id["qb"].projected_points, 20)
        self.assertLess(by_id["qb2"].projected_points, 20)
        self.assertAlmostEqual(environments["AAA"].implied_team_total, 35)
        self.assertLessEqual(environments["AAA"].projection_multiplier, 1.06)

    def test_game_lines_require_salary_file_team_abbreviations(self) -> None:
        with self.assertRaisesRegex(ValueError, "no game-lines teams matched"):
            apply_cfb_game_lines(
                self.slate,
                (Projection("Example Quarterback Jr.", "AAA", 20, platform_id="qb"),),
                "team,game_total,spread\nNOT-A-TEAM,50,-3\n",
            )

    def test_matches_consensus_team_names_to_slate_abbreviations(self) -> None:
        slate = Slate(
            Platform.DRAFTKINGS,
            ContestFormat.CLASSIC,
            self.slate.players + (
                Player(
                    "qb2", "Other Quarterback", Position.QB,
                    (Position.QB, Position.SUPER_FLEX), 7000,
                    "BBB", "AAA", "AAA@BBB 10/10/2026 12:00PM ET",
                    platform_average=10,
                ),
            ),
            "DKSalaries-2026.csv",
            Sport.CFB,
        )
        content, matched = cfb_consensus_lines_csv(
            slate,
            (CFBConsensusLine("Alpha Tigers", "Beta Bears", 55, -7, 7),),
            {"AAA": "Alpha", "BBB": "Beta"},
        )
        self.assertEqual(matched, 1)
        self.assertIn("AAA,BBB,55,-7", content)
        self.assertIn("BBB,AAA,55,7", content)

    def test_consensus_prefers_most_specific_nested_team_name(self) -> None:
        slate = Slate(
            Platform.DRAFTKINGS,
            ContestFormat.CLASSIC,
            (
                Player(
                    "ucla-qb", "UCLA Quarterback", Position.QB,
                    (Position.QB, Position.SUPER_FLEX), 8000,
                    "UCLA", "MSU", "MSU@UCLA 10/24/2026 03:30PM ET",
                    platform_average=20,
                ),
                Player(
                    "msu-qb", "Michigan State Quarterback", Position.QB,
                    (Position.QB, Position.SUPER_FLEX), 7000,
                    "MSU", "UCLA", "MSU@UCLA 10/24/2026 03:30PM ET",
                    platform_average=15,
                ),
            ),
            "DKSalaries-2026.csv",
            Sport.CFB,
        )

        content, matched = cfb_consensus_lines_csv(
            slate,
            (CFBConsensusLine(
                "UCLA Bruins", "Michigan State Spartans", 43.5, -16.5, 16.5
            ),),
            {"MICH": "Michigan", "MSU": "Michigan State", "UCLA": "UCLA"},
        )

        self.assertEqual(matched, 1)
        self.assertIn("UCLA,MSU,43.5,-16.5", content)
        self.assertIn("MSU,UCLA,43.5,16.5", content)

    def test_consensus_ignores_future_cross_slate_matchups(self) -> None:
        slate = Slate(
            Platform.DRAFTKINGS,
            ContestFormat.CLASSIC,
            self.slate.players + (
                Player(
                    "qb2", "Other Quarterback", Position.QB,
                    (Position.QB, Position.SUPER_FLEX), 7000,
                    "BBB", "AAA", "AAA@BBB 10/10/2026 12:00PM ET",
                    platform_average=10,
                ),
                Player(
                    "qb3", "Third Quarterback", Position.QB,
                    (Position.QB, Position.SUPER_FLEX), 6500,
                    "CCC", "DDD", "CCC@DDD 10/10/2026 3:30PM ET",
                    platform_average=10,
                ),
            ),
            "DKSalaries-2026.csv",
            Sport.CFB,
        )
        content, matched = cfb_consensus_lines_csv(
            slate,
            (
                CFBConsensusLine("Alpha Tigers", "Beta Bears", 55, -7, 7),
                CFBConsensusLine("Alpha Tigers", "Charlie Cats", 60, -3, 3),
            ),
            {"AAA": "Alpha", "BBB": "Beta", "CCC": "Charlie"},
        )
        self.assertEqual(matched, 1)
        self.assertNotIn("CCC", content)

    def test_projection_input_snapshot_excludes_irrelevant_and_future_rows(self) -> None:
        headers = (
            "game_id,season,week,team,opponent,completion_player,completion_yds,"
            "rush_player,rush_yds,reception_player,reception_yds,target_player,"
            "interception_thrown_player,interception_thrown_stat,touchdown_player\n"
        )
        rows = (
            "1,2026,1,Alpha,Beta,Example Quarterback,100,,,,,,,,\n"
            "4,2026,2,Alpha,Gamma,Alpha Teammate,75,,,,,,,,\n"
            "2,2026,1,Other,Beta,Irrelevant Player,100,,,,,,,,\n"
            "3,2026,3,Alpha,Beta,Example Quarterback,300,,,,,,,,\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "stats.csv"
            source.write_text(headers + rows, encoding="utf-8")
            snapshot = cfb_projection_input_snapshot(
                self.slate, source, target_week=3
            ).decode()

        self.assertIn("Example Quarterback,100", snapshot)
        self.assertIn("Alpha Teammate,75", snapshot)
        self.assertNotIn("Irrelevant Player", snapshot)
        self.assertNotIn("Example Quarterback,300", snapshot)


if __name__ == "__main__":
    unittest.main()
