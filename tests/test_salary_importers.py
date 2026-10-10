from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from dfs_optimizer.importers import SalaryImportError, import_salary_csv
from dfs_optimizer.models import ContestFormat, Platform, Position, Sport


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SAMPLES = PROJECT_ROOT / "samples"


class DraftKingsImporterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.slate = import_salary_csv(SAMPLES / "DKSalaries.csv")

    def test_imports_classic_slate(self) -> None:
        self.assertEqual(self.slate.platform, Platform.DRAFTKINGS)
        self.assertEqual(self.slate.contest_format, ContestFormat.CLASSIC)
        self.assertEqual(len(self.slate.players), 629)
        self.assertEqual(len(self.slate.teams), 24)
        self.assertEqual(len(self.slate.games), 12)

    def test_normalizes_player_and_opponent(self) -> None:
        player = next(p for p in self.slate.players if p.name == "Jaxon Smith-Njigba")
        self.assertEqual(player.team, "SEA")
        self.assertEqual(player.opponent, "LAC")
        self.assertEqual(player.salary, 9100)
        self.assertEqual(player.primary_position, Position.WR)
        self.assertEqual(player.roster_positions, (Position.WR, Position.FLEX))


class FanDuelImporterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.path = SAMPLES / "FanDuel-NFL-2026 EDT-10 EDT-04 EDT-134747-players-list.csv"
        cls.slate = import_salary_csv(cls.path)

    def test_imports_classic_slate(self) -> None:
        self.assertEqual(self.slate.platform, Platform.FANDUEL)
        self.assertEqual(self.slate.contest_format, ContestFormat.CLASSIC)
        self.assertEqual(len(self.slate.players), 613)
        self.assertEqual(len(self.slate.teams), 24)
        self.assertEqual(len(self.slate.games), 12)

    def test_normalizes_defense_position(self) -> None:
        defense = next(p for p in self.slate.players if p.primary_position == Position.DST)
        self.assertIn(Position.DST, defense.roster_positions)


class ImportFailureTests(unittest.TestCase):
    def test_rejects_unknown_schema(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "unknown.csv"
            path.write_text("foo,bar\n1,2\n", encoding="utf-8")
            with self.assertRaisesRegex(SalaryImportError, "unrecognized"):
                import_salary_csv(path)


class CollegeFootballImporterTests(unittest.TestCase):
    def test_detects_draftkings_college_super_flex(self) -> None:
        content = (
            "Position,Name + ID,Name,ID,Roster Position,Salary,Game Info,"
            "TeamAbbrev,AvgPointsPerGame,Status\n"
            "QB,Test QB (1),Test QB,1,QB/S-FLEX,8000,AAA@BBB 10/10/2026 12:00PM ET,AAA,24.5,\n"
            "WR,Test WR (2),Test WR,2,WR/FLEX/S-FLEX,7000,AAA@BBB 10/10/2026 12:00PM ET,BBB,18.0,\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "DKSalaries.csv"
            path.write_text(content, encoding="utf-8")
            slate = import_salary_csv(path)

        self.assertEqual(slate.sport, Sport.CFB)
        self.assertEqual(slate.platform, Platform.DRAFTKINGS)
        self.assertIn(Position.SUPER_FLEX, slate.players[0].roster_positions)

    def test_detects_fanduel_college_and_preserves_tight_end_position(self) -> None:
        content = (
            "Id,Position,First Name,Nickname,Last Name,FPPG,Played,Salary,Game,"
            "Team,Opponent,Injury Indicator,Injury Details,Tier,,,Roster Position\n"
            "1,TE,Test,Test Tight End,Tight End,14.2,4,7000,AAA@BBB,AAA,BBB,,,,,,WR/Super FLEX\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fanduel.csv"
            path.write_text(content, encoding="utf-8")
            slate = import_salary_csv(path)

        self.assertEqual(slate.sport, Sport.CFB)
        self.assertEqual(slate.platform, Platform.FANDUEL)
        self.assertEqual(slate.players[0].primary_position, Position.TE)
        self.assertEqual(
            slate.players[0].roster_positions,
            (Position.WR, Position.SUPER_FLEX),
        )


if __name__ == "__main__":
    unittest.main()
