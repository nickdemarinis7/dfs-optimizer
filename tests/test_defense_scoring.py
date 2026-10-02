from __future__ import annotations

import unittest
from pathlib import Path

from dfs_optimizer.importers import (
    import_defense_projections_csv,
    import_salary_csv,
    import_stat_projections_csv,
)
from dfs_optimizer.models import DefenseStatLine, Platform, ProjectedDefenseStats
from dfs_optimizer.projections import build_stat_based_projections
from dfs_optimizer.rules import nfl_scoring_for


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class DefenseScoringTests(unittest.TestCase):
    def test_scores_realized_defense_outcome(self) -> None:
        stats = DefenseStatLine(
            sacks=4,
            interceptions=1,
            fumble_recoveries=1,
            return_touchdowns=1,
            points_allowed=10,
        )
        for platform in Platform:
            with self.subTest(platform=platform):
                self.assertEqual(nfl_scoring_for(platform).score_defense(stats), 18)

    def test_scores_expected_points_allowed_distribution(self) -> None:
        stats = ProjectedDefenseStats(
            sacks=2,
            probability_allow_0=0.1,
            probability_allow_1_to_6=0.1,
            probability_allow_7_to_13=0.2,
            probability_allow_14_to_20=0.2,
            probability_allow_21_to_27=0.2,
            probability_allow_28_to_34=0.1,
            probability_allow_35_plus=0.1,
        )
        expected_tier_points = 1 + 0.7 + 0.8 + 0.2 + 0 - 0.1 - 0.4
        self.assertAlmostEqual(
            nfl_scoring_for(Platform.DRAFTKINGS).project_defense(stats),
            2 + expected_tier_points,
        )

    def test_adds_defenses_to_stat_based_slate_projections(self) -> None:
        slate = import_salary_csv(PROJECT_ROOT / "samples" / "DKSalaries.csv")
        offense = import_stat_projections_csv(
            PROJECT_ROOT / "examples" / "offensive-stat-projections.csv"
        )
        defenses = import_defense_projections_csv(
            PROJECT_ROOT / "examples" / "defense-stat-projections.csv"
        )
        projections = build_stat_based_projections(slate, offense, defenses)

        self.assertEqual(len(projections), 4)
        self.assertEqual({item.team for item in projections}, {"SEA", "BAL", "LV"})

    def test_requires_probability_distribution(self) -> None:
        with self.assertRaisesRegex(ValueError, "sum to 1"):
            ProjectedDefenseStats(probability_allow_0=0.5)


if __name__ == "__main__":
    unittest.main()

