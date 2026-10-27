from __future__ import annotations

from datetime import datetime, timezone
import unittest

from dfs_optimizer.models import ContestFormat, Platform, Player, Position, Projection, Slate
from dfs_optimizer.services.weekly_adjustments import apply_weekly_projection_context
from dfs_optimizer.services.weekly_context import TeamWeeklyContext


class WeeklyAdjustmentTests(unittest.TestCase):
    def test_live_high_wind_boundedly_scales_pass_game_distribution(self) -> None:
        slate = Slate(
            Platform.DRAFTKINGS, ContestFormat.CLASSIC,
            (Player("qb", "Quarterback", Position.QB, (Position.QB,), 7000, "SEA", "SF", "SEA@SF"),),
            "salary.csv",
        )
        projection = Projection(
            "Quarterback", "SEA", 20, "qb", floor=10, ceiling=35,
            p10=8, p25=14, p75=27, p90=32, bust_probability=.25,
        )
        weekly = TeamWeeklyContext(
            "SEA", "SF", "SEA@SF", 7, False, False, 700, "outdoors",
            45, 22, (), (), (), home_team="SF",
            kickoff_utc=datetime(2026, 10, 27, tzinfo=timezone.utc),
            precipitation_probability=20, weather_summary="Windy",
            weather_source="National Weather Service",
        )

        projections, adjustments = apply_weekly_projection_context(
            slate, (projection,), (weekly,)
        )

        self.assertAlmostEqual(projections[0].projected_points, 19)
        self.assertAlmostEqual(projections[0].p90, 30.4)
        self.assertAlmostEqual(projections[0].bust_probability, .30)
        self.assertEqual(adjustments[0].factor, .95)
        self.assertIn("live kickoff wind 22 mph", projections[0].confidence_reasons)

    def test_cached_weather_does_not_apply_second_adjustment(self) -> None:
        slate = Slate(
            Platform.DRAFTKINGS, ContestFormat.CLASSIC,
            (Player("wr", "Receiver", Position.WR, (Position.WR,), 6000, "SEA", "SF", "SEA@SF"),),
            "salary.csv",
        )
        projection = Projection("Receiver", "SEA", 15, "wr")
        weekly = TeamWeeklyContext(
            "SEA", "SF", "SEA@SF", 7, False, False, 700, "outdoors",
            45, 25, (), (), (),
        )

        projections, adjustments = apply_weekly_projection_context(
            slate, (projection,), (weekly,)
        )

        self.assertEqual(projections[0].projected_points, 15)
        self.assertEqual(adjustments, ())


if __name__ == "__main__":
    unittest.main()
