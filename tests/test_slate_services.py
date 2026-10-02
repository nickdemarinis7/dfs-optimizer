from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from dfs_optimizer.models import Platform
from dfs_optimizer.services import (
    discover_salary_files,
    infer_slate_period,
    load_uploaded_salary_file,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SAMPLES = PROJECT_ROOT / "samples"


class SlateServiceTests(unittest.TestCase):
    def test_discovers_salary_files_and_ignores_other_csvs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "salary.csv").write_bytes((SAMPLES / "DKSalaries.csv").read_bytes())
            (root / "history.csv").write_text("Entry ID,Contest Name\n1,Example\n", encoding="utf-8")

            discovered = discover_salary_files(root)

        self.assertEqual(len(discovered), 1)
        self.assertEqual(discovered[0][0].name, "salary.csv")
        self.assertEqual(discovered[0][1].platform, Platform.DRAFTKINGS)

    def test_loads_uploaded_salary_bytes(self) -> None:
        content = (SAMPLES / "DKSalaries.csv").read_bytes()

        slate = load_uploaded_salary_file("DKSalaries.csv", content)

        self.assertEqual(slate.platform, Platform.DRAFTKINGS)
        self.assertGreater(len(slate.players), 0)
        self.assertEqual(slate.source_name, "DKSalaries.csv")

    def test_uploaded_slate_identity_is_stable_across_reruns(self) -> None:
        content = (SAMPLES / "DKSalaries.csv").read_bytes()

        first = load_uploaded_salary_file("DKSalaries.csv", content)
        second = load_uploaded_salary_file("DKSalaries.csv", content)

        self.assertEqual(first, second)
        self.assertEqual(hash(first), hash(second))

    def test_infers_week_from_slate_matchups(self) -> None:
        slate = load_uploaded_salary_file(
            "DKSalaries.csv", (SAMPLES / "DKSalaries.csv").read_bytes()
        )
        with tempfile.TemporaryDirectory() as directory:
            schedule = Path(directory) / "games.csv"
            rows = [
                f"2026,REG,4,2026-10-04,{game.split('@')[0]},{game.split('@')[1]}"
                for game in slate.games
            ]
            schedule.write_text(
                "season,game_type,week,gameday,away_team,home_team\n"
                + "\n".join(rows)
                + "\n2026,REG,1,2026-09-13,ARI,LAR\n",
                encoding="utf-8",
            )

            result = infer_slate_period(slate, schedule)

        self.assertEqual(result, (2026, 4, len(slate.games), len(slate.games)))

    def test_does_not_guess_week_without_schedule(self) -> None:
        slate = load_uploaded_salary_file(
            "DKSalaries.csv", (SAMPLES / "DKSalaries.csv").read_bytes()
        )

        result = infer_slate_period(slate, "missing-games.csv")

        self.assertIsNone(result)

    def test_infers_single_game_week_from_slate_date(self) -> None:
        slate = load_uploaded_salary_file(
            "DKSalaries (1).csv", (SAMPLES / "DKSalaries (1).csv").read_bytes()
        )

        result = infer_slate_period(slate, PROJECT_ROOT / "data/cache/games.csv")

        self.assertEqual(result, (2026, 4, 1, 1))


if __name__ == "__main__":
    unittest.main()
