from __future__ import annotations

import unittest

from dfs_optimizer.models import Platform, ProjectedKickerStats
from dfs_optimizer.rules import nfl_scoring_for


class KickerProjectionTests(unittest.TestCase):
    def test_scores_projected_kicks_by_distance(self) -> None:
        stats = ProjectedKickerStats(
            field_goals_0_to_39=1,
            field_goals_40_to_49=0.5,
            field_goals_50_plus=0.25,
            extra_points=2,
        )
        for platform in Platform:
            with self.subTest(platform=platform):
                self.assertEqual(nfl_scoring_for(platform).project_kicker(stats), 8.25)


if __name__ == "__main__":
    unittest.main()
