from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from dfs_optimizer.models import ContestFormat, Platform, Player, Position, Projection, Slate, Sport
from dfs_optimizer.services.cfb_projections import (
    apply_cfb_game_lines,
    build_cfb_projections_from_file,
    estimate_cfb_ownership,
    infer_cfb_season,
)


class CFBProjectionTests(unittest.TestCase):
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

    def test_builds_recent_form_forecast_and_preserves_fallback(self) -> None:
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
            projections = build_cfb_projections_from_file(self.slate, source)

        by_id = {item.platform_id: item for item in projections}
        self.assertGreater(by_id["qb"].projected_points, 10)
        self.assertEqual(by_id["wr"].projected_points, 8)
        self.assertLessEqual(by_id["qb"].p25, by_id["qb"].projected_points)
        self.assertGreaterEqual(by_id["qb"].p75, by_id["qb"].projected_points)
        self.assertIsNotNone(by_id["qb"].projected_ownership)
        self.assertIsNotNone(by_id["wr"].projected_ownership)

    def test_infers_season_from_slate_metadata(self) -> None:
        self.assertEqual(infer_cfb_season(self.slate), 2026)

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


if __name__ == "__main__":
    unittest.main()
