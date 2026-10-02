from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from dfs_optimizer.importers import SalaryImportError, import_salary_csv
from dfs_optimizer.models import ContestFormat, Platform, Position


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


if __name__ == "__main__":
    unittest.main()
