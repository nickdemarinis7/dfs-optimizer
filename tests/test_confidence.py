from __future__ import annotations

import unittest

from dfs_optimizer.models import ContestFormat, Platform, Player, Position, Projection, Slate, Sport
from dfs_optimizer.services.confidence import apply_projection_confidence
from dfs_optimizer.services.player_context import PlayerContext


class ProjectionConfidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.player = Player(
            "wr", "Test Receiver", Position.WR,
            (Position.WR, Position.FLEX, Position.SUPER_FLEX),
            6000, "AAA", "BBB", "AAA@BBB",
        )
        self.slate = Slate(
            Platform.DRAFTKINGS, ContestFormat.CLASSIC,
            (self.player,), "cfb-2026.csv", Sport.CFB,
        )

    def test_grades_strong_fresh_verified_evidence_high(self) -> None:
        projection = Projection(
            self.player.name, self.player.team, 20, platform_id="wr",
            floor=14, ceiling=28, bust_probability=.15,
            sample_size=6, opportunity_stability=.85, data_age_periods=0,
        )

        scored = apply_projection_confidence(
            self.slate,
            (projection,),
            (PlayerContext("wr", 1, None, None, True),),
            context_age_minutes=10,
        )[0]

        self.assertEqual(scored.confidence_tier, "High")
        self.assertGreaterEqual(scored.confidence_score, 75)
        self.assertIn("stable recent opportunity", scored.confidence_reasons)

    def test_grades_thin_volatile_unverified_evidence_low(self) -> None:
        projection = Projection(
            self.player.name, self.player.team, 12, platform_id="wr",
            floor=0, ceiling=38, bust_probability=.65,
            sample_size=1, opportunity_stability=.1, data_age_periods=3,
        )

        scored = apply_projection_confidence(self.slate, (projection,))[0]

        self.assertEqual(scored.confidence_tier, "Low")
        self.assertLess(scored.confidence_score, 40)
        self.assertIn("current CFB role unverified", scored.confidence_reasons)

    def test_leaves_projection_without_evidence_unrated(self) -> None:
        projection = Projection(
            self.player.name, self.player.team, 12, platform_id="wr"
        )

        scored = apply_projection_confidence(self.slate, (projection,))[0]

        self.assertIsNone(scored.confidence_score)
        self.assertEqual(scored.confidence_tier, "Unrated")

    def test_confidence_does_not_change_projected_points(self) -> None:
        projection = Projection(
            self.player.name, self.player.team, 17.5, platform_id="wr",
            floor=5, ceiling=30, sample_size=2,
        )

        scored = apply_projection_confidence(self.slate, (projection,))[0]

        self.assertEqual(scored.projected_points, 17.5)


if __name__ == "__main__":
    unittest.main()
