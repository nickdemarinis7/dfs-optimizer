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
            self.assertLessEqual(result.p10, result.p25)
            self.assertLessEqual(result.p25, result.projected_points)
            self.assertGreaterEqual(result.p75, result.projected_points)
            self.assertGreaterEqual(result.p90, result.p75)
            self.assertIsNotNone(result.bust_probability)

    def test_role_reduction_pulls_down_temporary_starter_ceiling(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            players = root / "players.csv"
            teams = root / "teams.csv"
            games = root / "games.csv"
            players.write_text(
                "season,week,season_type,player_display_name,receptions,receiving_yards,receiving_tds\n"
                "2026,1,REG,Backup Tight End,6,60,0\n"
                "2026,2,REG,Backup Tight End,5,50,1\n"
                "2026,3,REG,Backup Tight End,1,2,0\n",
                encoding="utf-8",
            )
            teams.write_text("season,week,season_type,game_id,team\n", encoding="utf-8")
            games.write_text("game_id,home_team,away_team,home_score,away_score\n", encoding="utf-8")
            player = Player(
                "te", "Backup Tight End", Position.TE,
                (Position.TE, Position.FLEX), 3000, "AAA", "BBB", "AAA@BBB",
            )
            slate = Slate(
                Platform.DRAFTKINGS, ContestFormat.CLASSIC, (player,), "test.csv"
            )

            result = add_historical_ranges(
                slate,
                (Projection(player.name, player.team, 2.5, platform_id="te"),),
                (players,), (teams,), games, 2026, 4,
            )[0]

            self.assertLess(result.ceiling, 8)

    def test_kicker_ranges_use_realized_kicking_points(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            players = root / "players.csv"
            teams = root / "teams.csv"
            games = root / "games.csv"
            players.write_text(
                "season,week,season_type,player_display_name,fg_att,pat_att,"
                "fg_made_0_19,fg_made_20_29,fg_made_30_39,fg_made_40_49,"
                "fg_made_50_59,fg_made_60_,pat_made\n"
                "2026,1,REG,Test Kicker,1,2,0,0,1,0,0,0,2\n"
                "2026,2,REG,Test Kicker,2,3,0,0,1,1,0,0,3\n"
                "2026,3,REG,Test Kicker,3,2,0,0,1,1,1,0,2\n",
                encoding="utf-8",
            )
            teams.write_text(
                "season,week,season_type,game_id,team\n", encoding="utf-8"
            )
            games.write_text(
                "game_id,home_team,away_team,home_score,away_score\n",
                encoding="utf-8",
            )
            player = Player(
                "k", "Test Kicker", Position.K, (Position.K,),
                5000, "AAA", "BBB", "AAA@BBB",
            )
            slate = Slate(
                Platform.DRAFTKINGS, ContestFormat.SINGLE_GAME,
                (player,), "test.csv",
            )

            result = add_historical_ranges(
                slate,
                (Projection(player.name, player.team, 8, platform_id="k"),),
                (players,), (teams,), games, 2026, 4,
            )[0]

            self.assertEqual(result.sample_size, 3)
            self.assertGreater(result.ceiling, result.projected_points)
            self.assertLess(result.bust_probability, 1)

    def test_preserves_recent_opportunity_decline_as_projection_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            players = root / "players.csv"
            teams = root / "teams.csv"
            games = root / "games.csv"
            snaps = root / "snaps.csv"
            players.write_text(
                "season,week,season_type,player_display_name,position,targets,receptions,receiving_yards\n"
                "2026,1,REG,Declining TE,TE,8,5,50\n"
                "2026,2,REG,Declining TE,TE,7,4,40\n"
                "2026,3,REG,Declining TE,TE,1,1,4\n"
                "2026,4,REG,Declining TE,TE,1,0,0\n",
                encoding="utf-8",
            )
            teams.write_text("season,week,season_type,game_id,team\n", encoding="utf-8")
            games.write_text("game_id,home_team,away_team,home_score,away_score\n", encoding="utf-8")
            snaps.write_text(
                "season,week,game_type,player,team,offense_pct\n"
                "2026,1,REG,Declining TE,AAA,.80\n"
                "2026,2,REG,Declining TE,AAA,.75\n"
                "2026,3,REG,Declining TE,AAA,.20\n"
                "2026,4,REG,Declining TE,AAA,.15\n",
                encoding="utf-8",
            )
            player = Player(
                "te", "Declining TE", Position.TE, (Position.TE, Position.FLEX),
                3500, "AAA", "BBB", "AAA@BBB",
            )
            slate = Slate(
                Platform.DRAFTKINGS, ContestFormat.CLASSIC, (player,), "test.csv"
            )

            result = add_historical_ranges(
                slate, (Projection(player.name, player.team, 4, platform_id="te"),),
                (players,), (teams,), games, 2026, 5, snap_files=(snaps,),
            )[0]

            self.assertEqual(result.sample_size, 4)
            self.assertLess(result.opportunity_stability, .30)
            self.assertEqual(result.data_age_periods, 0)

    def test_marks_first_game_back_after_multi_game_absence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            players = root / "players.csv"
            teams = root / "teams.csv"
            games = root / "games.csv"
            snaps = root / "snaps.csv"
            players.write_text(
                "season,week,season_type,player_display_name,position,targets,receptions,receiving_yards\n"
                "2026,1,REG,Returning WR,WR,8,5,70\n"
                "2026,6,REG,Returning WR,WR,10,3,27\n",
                encoding="utf-8",
            )
            teams.write_text(
                "season,week,season_type,game_id,team\n"
                + "".join(
                    f"2026,{week},REG,g{week},NE\n" for week in range(1, 7)
                ),
                encoding="utf-8",
            )
            games.write_text(
                "game_id,home_team,away_team,home_score,away_score\n",
                encoding="utf-8",
            )
            snaps.write_text(
                "season,week,game_type,player,team,offense_pct\n"
                "2026,1,REG,Returning WR,NE,.80\n"
                "2026,6,REG,Returning WR,NE,.76\n",
                encoding="utf-8",
            )
            player = Player(
                "wr", "Returning WR", Position.WR,
                (Position.WR, Position.FLEX), 7000, "NE", "CHI", "NE@CHI",
            )
            slate = Slate(
                Platform.DRAFTKINGS, ContestFormat.SINGLE_GAME,
                (player,), "test.csv",
            )

            result = add_historical_ranges(
                slate,
                (Projection(player.name, player.team, 14, platform_id="wr"),),
                (players,), (teams,), games, 2026, 7, snap_files=(snaps,),
            )[0]

            self.assertEqual(result.recent_return_games, 1)


if __name__ == "__main__":
    unittest.main()
