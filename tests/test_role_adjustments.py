from __future__ import annotations

import unittest

from dfs_optimizer.models import ContestFormat, Platform, Player, Position, Projection, Slate
from dfs_optimizer.services.player_context import PlayerContext
from dfs_optimizer.services.role_adjustments import apply_current_role_adjustments


class CurrentRoleAdjustmentTests(unittest.TestCase):
    def test_reduces_backup_tight_end_behind_active_te1(self) -> None:
        players = (
            Player("te1", "Starter", Position.TE, (Position.TE,), 6000, "LV", "NE", "LV@NE"),
            Player("te2", "Former fill in", Position.TE, (Position.TE,), 3000, "LV", "NE", "LV@NE"),
        )
        slate = Slate(Platform.DRAFTKINGS, ContestFormat.CLASSIC, players, "test")
        projections = (
            Projection("Starter", "LV", 12, platform_id="te1", floor=6, ceiling=20),
            Projection(
                "Former fill in", "LV", 8, platform_id="te2",
                floor=3, ceiling=14, p10=1, p25=3, p75=10, p90=14,
                bust_probability=.30,
            ),
        )
        contexts = (
            PlayerContext("te1", 1, None, None, True),
            PlayerContext("te2", 2, None, None, True),
        )

        adjusted, audit = apply_current_role_adjustments(
            slate, projections, contexts
        )

        by_id = {item.platform_id: item for item in adjusted}
        self.assertEqual(by_id["te1"].projected_points, 12)
        self.assertAlmostEqual(by_id["te2"].projected_points, 5.2)
        self.assertAlmostEqual(by_id["te2"].ceiling, 9.1)
        self.assertGreater(by_id["te2"].bust_probability, .30)
        self.assertEqual(audit[0].depth_order, 2)

    def test_does_not_penalize_backup_when_starter_is_out(self) -> None:
        players = (
            Player("te1", "Starter", Position.TE, (Position.TE,), 6000, "LV", "NE", "LV@NE"),
            Player("te2", "Replacement", Position.TE, (Position.TE,), 3000, "LV", "NE", "LV@NE"),
        )
        slate = Slate(Platform.DRAFTKINGS, ContestFormat.CLASSIC, players, "test")
        projections = tuple(
            Projection(player.name, player.team, 10, platform_id=player.platform_id)
            for player in players
        )
        contexts = (
            PlayerContext("te1", 1, "OUT", None, False),
            PlayerContext("te2", 2, None, None, True),
        )

        adjusted, audit = apply_current_role_adjustments(
            slate, projections, contexts
        )

        self.assertEqual(adjusted, projections)
        self.assertEqual(audit, ())


if __name__ == "__main__":
    unittest.main()
