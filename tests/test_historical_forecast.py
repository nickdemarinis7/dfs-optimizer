from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from dfs_optimizer.models import ContestFormat, Platform, Player, Position, Slate
from dfs_optimizer.projections import forecast_from_nflverse
from dfs_optimizer.projections.historical import _normalize, _role_trend_factor


class HistoricalForecastTests(unittest.TestCase):
    def test_name_normalization_ignores_generational_suffixes(self) -> None:
        self.assertEqual(_normalize("James Cook III"), _normalize("James Cook"))
        self.assertEqual(_normalize("Anthony Richardson Sr."), _normalize("Anthony Richardson"))

    def test_weights_recent_games_and_excludes_target_week(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            players = root / "players.csv"
            teams = root / "teams.csv"
            games = root / "games.csv"
            players.write_text(
                "season,week,season_type,player_display_name,position,attempts,passing_yards,passing_tds,passing_interceptions\n"
                "2026,2,REG,Test Quarterback,QB,30,200,1,0\n"
                "2026,3,REG,Test Quarterback,QB,40,300,2,0\n"
                "2026,4,REG,Test Quarterback,QB,60,999,9,0\n",
                encoding="utf-8",
            )
            teams.write_text(
                "season,week,season_type,game_id,team,def_sacks,def_interceptions\n"
                "2026,2,REG,g2,AAA,2,1\n"
                "2026,3,REG,g3,AAA,4,0\n"
                "2026,4,REG,g4,AAA,20,10\n",
                encoding="utf-8",
            )
            games.write_text(
                "game_id,home_team,away_team,home_score,away_score\n"
                "g2,AAA,BBB,20,10\n"
                "g3,AAA,BBB,24,14\n"
                "g4,AAA,BBB,50,0\n",
                encoding="utf-8",
            )
            slate = Slate(
                Platform.DRAFTKINGS,
                ContestFormat.CLASSIC,
                (
                    Player("qb", "Test Quarterback", Position.QB, (Position.QB,), 5000, "AAA", "BBB", "AAA@BBB"),
                    Player("dst", "Test Defense", Position.DST, (Position.DST,), 3000, "AAA", "BBB", "AAA@BBB"),
                ),
                "test.csv",
            )

            offense, defense = forecast_from_nflverse(
                slate, (players,), (teams,), games, 2026, 4
            )

            self.assertAlmostEqual(sum(defense[0].stats.points_allowed_probabilities), 1)
            self.assertGreater(offense[0].stats.passing_yards, 200)
            self.assertLess(offense[0].stats.passing_yards, 300)

    def test_suppresses_stale_starter_projection_for_current_backup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            players = root / "players.csv"
            teams = root / "teams.csv"
            games = root / "games.csv"
            players.write_text(
                "season,week,season_type,player_display_name,position,carries,targets,rushing_yards\n"
                "2025,18,REG,Backup Runner,RB,18,4,90\n"
                "2026,1,REG,Backup Runner,RB,1,0,3\n"
                "2026,3,REG,Backup Runner,RB,1,0,2\n",
                encoding="utf-8",
            )
            teams.write_text(
                "season,week,season_type,game_id,team\n"
                "2026,1,REG,g1,AAA\n"
                "2026,2,REG,g2,AAA\n"
                "2026,3,REG,g3,AAA\n",
                encoding="utf-8",
            )
            games.write_text(
                "game_id,home_team,away_team,home_score,away_score\n",
                encoding="utf-8",
            )
            slate = Slate(
                Platform.DRAFTKINGS,
                ContestFormat.CLASSIC,
                (Player(
                    "rb", "Backup Runner", Position.RB, (Position.RB,), 3000,
                    "AAA", "BBB", "AAA@BBB", platform_average=1.0,
                ),),
                "test.csv",
            )

            offense, _ = forecast_from_nflverse(
                slate, (players,), (teams,), games, 2026, 4
            )

            self.assertEqual(offense, ())

    def test_role_trend_is_bounded_and_ignores_absence_only_samples(self) -> None:
        declining = [
            {"carries": "7", "targets": "3"},
            {"carries": "6", "targets": "2"},
            {"carries": "18", "targets": "6"},
        ]
        injury_absence = [{}, {}, {"carries": "0", "targets": "9"}]

        self.assertEqual(_role_trend_factor(Position.RB, declining), 0.75)
        self.assertEqual(_role_trend_factor(Position.WR, injury_absence), 1.0)


if __name__ == "__main__":
    unittest.main()
