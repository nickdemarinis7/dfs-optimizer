from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from dfs_optimizer.models import ContestFormat, Platform, Player, Position, Projection, Slate
from dfs_optimizer.projections import add_historical_ranges


class HistoricalRangeTests(unittest.TestCase):
    def test_excludes_target_week_from_empirical_ceiling(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            players = root / "players.csv"
            teams = root / "teams.csv"
            games = root / "games.csv"
            players.write_text(
                "season,week,season_type,player_display_name,passing_yards,passing_tds,passing_interceptions\n"
                "2026,2,REG,Test QB,200,1,0\n"
                "2026,3,REG,Test QB,300,2,0\n"
                "2026,4,REG,Test QB,999,9,0\n",
                encoding="utf-8",
            )
            teams.write_text("season,week,season_type,game_id,team\n", encoding="utf-8")
            games.write_text("game_id,home_team,away_team,home_score,away_score\n", encoding="utf-8")
            slate = Slate(
                Platform.DRAFTKINGS,
                ContestFormat.CLASSIC,
                (Player("qb", "Test QB", Position.QB, (Position.QB,), 5000, "AAA", "BBB", "AAA@BBB"),),
                "test.csv",
            )
            projection = Projection("Test QB", "AAA", 15, platform_id="qb")

            result = add_historical_ranges(
                slate, (projection,), (players,), (teams,), games, 2026, 4
            )[0]

            self.assertIsNotNone(result.floor)
            self.assertIsNotNone(result.ceiling)
            self.assertLess(result.ceiling, 30)
            self.assertGreaterEqual(result.ceiling, result.projected_points)


if __name__ == "__main__":
    unittest.main()
