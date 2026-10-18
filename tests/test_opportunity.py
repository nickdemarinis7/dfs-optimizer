from __future__ import annotations

import unittest

from dfs_optimizer.models import ContestFormat, Platform, Player, Position, Projection, Slate
from dfs_optimizer.services.opportunity import apply_opportunity_risk
from dfs_optimizer.services.player_context import PlayerContext


class OpportunityRiskTests(unittest.TestCase):
    def test_fragile_backup_role_widens_downside_without_changing_median(self) -> None:
        starter = Player(
            "te1", "Starter", Position.TE, (Position.TE, Position.FLEX),
            6000, "LV", "NE", "LV@NE",
        )
        player = Player(
            "te2", "Former Starter", Position.TE, (Position.TE, Position.FLEX),
            3000, "LV", "NE", "LV@NE",
        )
        slate = Slate(
            Platform.DRAFTKINGS, ContestFormat.CLASSIC, (starter, player), "test"
        )
        projection = Projection(
            player.name, player.team, 7, platform_id=player.platform_id,
            floor=2, ceiling=15, p10=1, p25=3, p75=10, p90=16,
            bust_probability=.35, opportunity_stability=.20,
        )

        adjusted, assessments = apply_opportunity_risk(
            slate, (projection,),
            (
                PlayerContext("te1", 1, None, None, True),
                PlayerContext("te2", 2, None, None, True),
            ),
        )

        self.assertEqual(adjusted[0].projected_points, 7)
        self.assertLess(adjusted[0].floor, projection.floor)
        self.assertLess(adjusted[0].ceiling, projection.ceiling)
        self.assertGreaterEqual(adjusted[0].bust_probability, .65)
        self.assertEqual(assessments[0].tier, "Fragile")
        self.assertIn("TE2", " ".join(assessments[0].reasons))

    def test_current_starter_with_held_opportunity_remains_strong(self) -> None:
        player = Player(
            "wr1", "Starter", Position.WR, (Position.WR, Position.FLEX),
            7000, "BUF", "NE", "BUF@NE",
        )
        slate = Slate(Platform.FANDUEL, ContestFormat.CLASSIC, (player,), "test")
        projection = Projection(
            player.name, player.team, 15, platform_id=player.platform_id,
            floor=8, ceiling=24, p10=5, p25=9, p75=19, p90=25,
            bust_probability=.15, opportunity_stability=.95,
        )

        adjusted, assessments = apply_opportunity_risk(
            slate, (projection,),
            (PlayerContext("wr1", 1, None, None, True),),
        )

        self.assertEqual(adjusted, (projection,))
        self.assertEqual(assessments[0].tier, "Strong")

    def test_replacement_qb_is_not_penalized_when_qb1_is_out(self) -> None:
        starter = Player(
            "qb1", "Injured QB", Position.QB, (Position.QB,),
            10000, "BUF", "NE", "BUF@NE", status="OUT",
        )
        replacement = Player(
            "qb2", "Replacement QB", Position.QB, (Position.QB,),
            7000, "BUF", "NE", "BUF@NE",
        )
        slate = Slate(
            Platform.DRAFTKINGS, ContestFormat.SINGLE_GAME,
            (starter, replacement), "test",
        )
        projection = Projection(
            replacement.name, replacement.team, 14,
            platform_id=replacement.platform_id, floor=6, ceiling=22,
            bust_probability=.25, opportunity_stability=.8,
        )

        _, assessments = apply_opportunity_risk(
            slate, (projection,),
            (
                PlayerContext("qb1", 1, "OUT", None, False),
                PlayerContext("qb2", 2, None, None, True),
            ),
        )

        self.assertNotIn(assessments[0].tier, {"Watch", "Fragile"})
        self.assertNotIn("QB2", " ".join(assessments[0].reasons))


if __name__ == "__main__":
    unittest.main()
