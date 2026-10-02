from __future__ import annotations

import unittest
from pathlib import Path

from dfs_optimizer.backtesting import PlayerResult, evaluate_projections, import_fanduel_results
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
            Projection("A", "AAA", 10),
            Projection("B", "BBB", 20),
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


if __name__ == "__main__":
    unittest.main()
