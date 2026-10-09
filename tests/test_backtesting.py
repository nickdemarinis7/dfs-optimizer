from __future__ import annotations

import unittest
import io
import zipfile
from pathlib import Path

from dfs_optimizer.backtesting import (
    PlayerResult,
    evaluate_projections,
    import_fanduel_results,
    import_player_results_content,
)
from dfs_optimizer.models import Projection


ROOT = Path(__file__).resolve().parents[1]


class ContestResultTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.results = import_fanduel_results(ROOT / "samples" / "134649-280797705.csv")

    def test_parses_real_contest_export(self) -> None:
        self.assertEqual(len(self.results.entries), 27_777)
        self.assertEqual(len(self.results.scored_entries), 27_727)
        self.assertEqual(len(self.results.players), 40)
        self.assertAlmostEqual(max(entry.points for entry in self.results.scored_entries), 135.19)

    def test_computes_lineup_duplication_and_percentile(self) -> None:
        self.assertEqual(sum(self.results.duplicated_lineups.values()), 27_777)
        self.assertGreater(self.results.score_percentile(135.19), 99.9)


class ProjectionMetricTests(unittest.TestCase):
    def test_calculates_errors_and_correlation(self) -> None:
        projections = (
            Projection("A", "AAA", 10, floor=8, ceiling=14),
            Projection("B", "BBB", 20, floor=17, ceiling=19),
        )
        actuals = (
            PlayerResult("A", "WR", 10, 12),
            PlayerResult("B", "RB", 20, 16),
        )
        metrics = evaluate_projections(projections, actuals)

        self.assertEqual(metrics.matched_players, 2)
        self.assertEqual(metrics.mean_absolute_error, 3)
        self.assertAlmostEqual(metrics.root_mean_squared_error, (20 / 2) ** 0.5)
        self.assertEqual(metrics.mean_error, 1)
        self.assertEqual(metrics.interval_coverage, 0.5)
        self.assertEqual(metrics.ceiling_exceed_rate, 0)

    def test_extracts_unmultiplied_showdown_player_results(self) -> None:
        csv_text = (
            "Rank,EntryId,EntryName,Points,Lineup,,Player,Roster Position,%Drafted,FPTS\n"
            "1,one,user,20,CPT Test Player,,Test Player (1-2),CPT,10%,18\n"
            "1,one,user,20,CPT Test Player,,Test Player (1-2),FLEX,40%,12\n"
        )
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr("results.csv", csv_text)

        results = import_player_results_content(
            output.getvalue(), "results.zip", {"Test Player": "WR"}
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].name, "Test Player")
        self.assertEqual(results[0].position, "WR")
        self.assertEqual(results[0].fantasy_points, 12)


if __name__ == "__main__":
    unittest.main()
