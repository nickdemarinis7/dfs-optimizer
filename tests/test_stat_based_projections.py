from __future__ import annotations

import unittest
from pathlib import Path

from dfs_optimizer.importers import import_salary_csv, import_stat_projections_csv
from dfs_optimizer.models import Platform, ProjectedOffensiveStats
from dfs_optimizer.projections import build_stat_based_projections
from dfs_optimizer.rules import nfl_scoring_for


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class StatBasedProjectionTests(unittest.TestCase):
    def test_same_stats_score_differently_by_platform(self) -> None:
        stats = ProjectedOffensiveStats(
            receptions=8,
            receiving_yards=95,
            receiving_touchdowns=0.5,
            receiving_bonus_probability=0.4,
        )
        draftkings = nfl_scoring_for(Platform.DRAFTKINGS).project_offense(stats)
        fanduel = nfl_scoring_for(Platform.FANDUEL).project_offense(stats)

        self.assertAlmostEqual(draftkings, 21.7)
        self.assertAlmostEqual(fanduel, 17.7)

    def test_imports_stats_and_builds_slate_projections(self) -> None:
        stats = import_stat_projections_csv(
            PROJECT_ROOT / "examples" / "offensive-stat-projections.csv"
        )
        slate = import_salary_csv(PROJECT_ROOT / "samples" / "DKSalaries.csv")
        projections = build_stat_based_projections(slate, stats)

        self.assertEqual(len(stats), 2)
        self.assertEqual(len(projections), 2)
        self.assertEqual(
            {item.name for item in projections},
            {"Jaxon Smith-Njigba", "Derrick Henry"},
        )

    def test_expected_bonus_uses_probability_not_mean_threshold(self) -> None:
        rules = nfl_scoring_for(Platform.DRAFTKINGS)
        stats = ProjectedOffensiveStats(
            passing_yards=295,
            passing_bonus_probability=0.45,
        )

        self.assertAlmostEqual(rules.project_offense(stats), 13.15)


if __name__ == "__main__":
    unittest.main()

