from __future__ import annotations

import unittest

from dfs_optimizer.models import OffensiveStatLine, Platform
from dfs_optimizer.rules import nfl_scoring_for


class NFLScoringRuleTests(unittest.TestCase):
    def test_draftkings_is_full_ppr_and_fanduel_is_half_ppr(self) -> None:
        stats = OffensiveStatLine(
            receptions=8,
            receiving_yards=110,
            receiving_touchdowns=1,
        )

        draftkings = nfl_scoring_for(Platform.DRAFTKINGS).score_offense(stats)
        fanduel = nfl_scoring_for(Platform.FANDUEL).score_offense(stats)

        self.assertEqual(draftkings, 28)
        self.assertEqual(fanduel, 24)
        self.assertEqual(draftkings - fanduel, 4)

    def test_both_platforms_apply_passing_yardage_bonus(self) -> None:
        stats = OffensiveStatLine(
            passing_yards=325,
            passing_touchdowns=2,
            interceptions_thrown=1,
        )

        for platform in Platform:
            with self.subTest(platform=platform):
                self.assertEqual(nfl_scoring_for(platform).score_offense(stats), 23)

    def test_bonus_requires_reaching_threshold(self) -> None:
        rules = nfl_scoring_for(Platform.DRAFTKINGS)
        below = rules.score_offense(OffensiveStatLine(receiving_yards=99.9))
        reached = rules.score_offense(OffensiveStatLine(receiving_yards=100))

        self.assertAlmostEqual(below, 9.99)
        self.assertEqual(reached, 13)

    def test_platform_fumble_penalties_differ(self) -> None:
        stats = OffensiveStatLine(fumbles_lost=1)

        self.assertEqual(
            nfl_scoring_for(Platform.DRAFTKINGS).score_offense(stats), -1
        )
        self.assertEqual(nfl_scoring_for(Platform.FANDUEL).score_offense(stats), -2)

    def test_rejects_negative_count(self) -> None:
        with self.assertRaisesRegex(ValueError, "receptions"):
            OffensiveStatLine(receptions=-1)


if __name__ == "__main__":
    unittest.main()

