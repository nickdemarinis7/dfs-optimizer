from __future__ import annotations

import unittest

from dfs_optimizer.models import (
    ContestFormat,
    Platform,
    Player,
    Position,
    Projection,
    Slate,
)
from dfs_optimizer.services.projections import apply_uploaded_projection_consensus


class ProjectionConsensusTests(unittest.TestCase):
    def setUp(self) -> None:
        self.player = Player(
            "p1", "Example Runner", Position.RB, (Position.RB,),
            6000, "GB", "CHI", "GB@CHI",
        )
        self.slate = Slate(
            Platform.DRAFTKINGS,
            ContestFormat.CLASSIC,
            (self.player,),
            "salary.csv",
        )
        self.projection = Projection(
            "Example Runner", "GB", 10, platform_id="p1",
            floor=4, ceiling=20, p10=2, p25=6, p75=14, p90=22,
            bust_probability=.35, sample_size=5, opportunity_stability=.8,
        )

    def test_blends_external_median_and_scales_internal_range(self) -> None:
        blended, matched = apply_uploaded_projection_consensus(
            self.slate,
            (self.projection,),
            "external.csv",
            b"name,team,projected_points\nExample Runner,GB,12\n",
        )

        self.assertEqual(matched, 1)
        self.assertAlmostEqual(blended[0].projected_points, 10.7)
        self.assertAlmostEqual(blended[0].floor, 4.28)
        self.assertAlmostEqual(blended[0].p90, 23.54)
        self.assertEqual(blended[0].sample_size, 5)
        self.assertEqual(blended[0].bust_probability, .35)

    def test_caps_extreme_external_value_before_blending(self) -> None:
        blended, _ = apply_uploaded_projection_consensus(
            self.slate,
            (self.projection,),
            "external.csv",
            b"name,team,projected_points\nExample Runner,GB,100\n",
        )

        self.assertAlmostEqual(blended[0].projected_points, 11.4)

    def test_rejects_external_majority_weight(self) -> None:
        with self.assertRaisesRegex(ValueError, "between 0 and 0.5"):
            apply_uploaded_projection_consensus(
                self.slate,
                (self.projection,),
                "external.csv",
                b"name,team,projected_points\nExample Runner,GB,12\n",
                external_weight=.75,
            )


if __name__ == "__main__":
    unittest.main()
