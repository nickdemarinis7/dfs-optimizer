from __future__ import annotations

import unittest

from dfs_optimizer.models import ContestFormat, Platform, Player, Position, Projection, Slate
from dfs_optimizer.services.player_context import match_player_context
from dfs_optimizer.services.risk import (
    suggest_default_excluded_player_ids,
    suggest_max_once_player_ids,
)


class PlayerContextTests(unittest.TestCase):
    def setUp(self) -> None:
        self.players = (
            Player("dak", "Dak Prescott", Position.QB, (Position.QB,), 15000, "DAL", "TB", "DAL@TB"),
            Player("joe", "Joe Milton III", Position.QB, (Position.QB,), 6000, "DAL", "TB", "DAL@TB"),
            Player("wr", "Depth Receiver", Position.WR, (Position.WR, Position.FLEX), 7000, "DAL", "TB", "DAL@TB"),
        )
        self.slate = Slate(Platform.FANDUEL, ContestFormat.SINGLE_GAME, self.players, "test.csv")
        self.projections = (
            Projection("Dak Prescott", "DAL", 20, platform_id="dak"),
            Projection("Joe Milton III", "DAL", 8, platform_id="joe"),
            Projection("Depth Receiver", "DAL", 8, platform_id="wr", floor=2),
        )

    def test_matches_current_depth_and_injury_context(self) -> None:
        contexts = match_player_context(self.slate, {
            "1": {"full_name": "Dak Prescott", "team": "DAL", "depth_chart_position": 1, "active": True},
            "2": {"full_name": "Joe Milton", "team": "DAL", "depth_chart_position": "3", "active": True},
            "3": {"full_name": "Depth Receiver", "team": "DAL", "depth_chart_position": 4, "injury_status": "Questionable", "active": True},
        })

        by_id = {item.platform_id: item for item in contexts}
        self.assertEqual(by_id["joe"].depth_chart_position, 3)
        self.assertEqual(by_id["wr"].injury_status, "Questionable")

    def test_context_excludes_backup_qb_and_limits_deep_skill_player(self) -> None:
        contexts = match_player_context(self.slate, {
            "1": {"full_name": "Dak Prescott", "team": "DAL", "depth_chart_position": 1, "active": True},
            "2": {"full_name": "Joe Milton III", "team": "DAL", "depth_chart_position": 3, "active": True},
            "3": {"full_name": "Depth Receiver", "team": "DAL", "depth_chart_position": 4, "active": True},
        })

        excluded = suggest_default_excluded_player_ids(
            self.slate, self.projections, contexts
        )
        limited = suggest_max_once_player_ids(
            self.slate, self.projections, contexts
        )

        self.assertIn("joe", excluded)
        self.assertIn("wr", limited)
        self.assertNotIn("dak", excluded)


if __name__ == "__main__":
    unittest.main()
