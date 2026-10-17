from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import unittest

from dfs_optimizer.importers import import_salary_csv
from dfs_optimizer.models import ContestFormat, Platform, Sport
from dfs_optimizer.projections import build_platform_average_projections
from dfs_optimizer.services.ownership import estimate_nfl_showdown_ownership


ROOT = Path(__file__).resolve().parents[1]


def make_single_game_slate(platform: Platform):
    path = (
        ROOT / "samples" / "DKSalaries (1).csv"
        if platform == Platform.DRAFTKINGS
        else next((ROOT / "samples").glob("*134921-players-list.csv"))
    )
    slate = import_salary_csv(path)
    return slate, build_platform_average_projections(slate)


class NFLOwnershipEstimateTests(unittest.TestCase):
    def test_scales_showdown_estimates_to_six_roster_slots(self) -> None:
        slate, projections = make_single_game_slate(Platform.DRAFTKINGS)

        estimated = estimate_nfl_showdown_ownership(slate, projections)

        self.assertAlmostEqual(
            sum(item.projected_ownership or 0 for item in estimated),
            600,
            places=1,
        )
        self.assertTrue(all(
            0 <= (item.projected_ownership or 0) <= 85 for item in estimated
        ))
        highest_projection = max(estimated, key=lambda item: item.projected_points)
        lowest_projection = min(estimated, key=lambda item: item.projected_points)
        self.assertGreater(
            highest_projection.projected_ownership,
            lowest_projection.projected_ownership,
        )

    def test_does_not_overwrite_uploaded_ownership(self) -> None:
        slate, projections = make_single_game_slate(Platform.FANDUEL)
        uploaded = tuple(
            replace(item, projected_ownership=12.5) for item in projections
        )

        self.assertEqual(
            estimate_nfl_showdown_ownership(slate, uploaded),
            uploaded,
        )

    def test_does_not_estimate_non_nfl_or_classic_slates(self) -> None:
        slate, projections = make_single_game_slate(Platform.DRAFTKINGS)
        classic = replace(slate, contest_format=ContestFormat.CLASSIC)
        cfb = replace(slate, sport=Sport.CFB)

        self.assertEqual(
            estimate_nfl_showdown_ownership(classic, projections), projections
        )
        self.assertEqual(
            estimate_nfl_showdown_ownership(cfb, projections), projections
        )


if __name__ == "__main__":
    unittest.main()
