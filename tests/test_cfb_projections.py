from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from dfs_optimizer.models import ContestFormat, Platform, Player, Position, Slate, Sport
from dfs_optimizer.services.cfb_projections import (
    build_cfb_projections_from_file,
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

    def test_infers_season_from_slate_metadata(self) -> None:
        self.assertEqual(infer_cfb_season(self.slate), 2026)


if __name__ == "__main__":
    unittest.main()
