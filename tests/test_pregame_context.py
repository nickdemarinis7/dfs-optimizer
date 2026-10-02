from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from dfs_optimizer.importers import PlayerStatProjection
from dfs_optimizer.models import ContestFormat, Platform, Player, Position, ProjectedOffensiveStats, Slate
from dfs_optimizer.projections import apply_pregame_context


class PregameContextTests(unittest.TestCase):
    def test_market_matchup_and_wind_are_bounded_and_applied(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            teams = root / "teams.csv"
            games = root / "games.csv"
            teams.write_text(
                "season,week,season_type,team,opponent_team,attempts,passing_yards,carries,rushing_yards\n"
                "2026,1,REG,AAA,BBB,30,300,20,80\n"
                "2026,1,REG,BBB,AAA,30,180,20,120\n",
                encoding="utf-8",
            )
            games.write_text(
                "season,week,home_team,away_team,total_line,spread_line,roof,wind\n"
                "2026,2,AAA,BBB,50,6,outdoors,25\n",
                encoding="utf-8",
            )
            player = Player("1", "Test QB", Position.QB, (Position.QB,), 5000, "AAA", "BBB", "BBB@AAA")
            slate = Slate(Platform.DRAFTKINGS, ContestFormat.CLASSIC, (player,), "test.csv")
            original = PlayerStatProjection("Test QB", "AAA", ProjectedOffensiveStats(passing_yards=300, passing_touchdowns=2))

            adjusted, _ = apply_pregame_context(slate, (original,), (), (teams,), games, 2026, 2)

            self.assertLess(adjusted[0].stats.passing_yards, 300)
            self.assertGreater(adjusted[0].stats.passing_yards, 200)


if __name__ == "__main__":
    unittest.main()
