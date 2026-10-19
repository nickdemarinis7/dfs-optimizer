from __future__ import annotations

import unittest

from dfs_optimizer.data_sources.nfl_props import parse_nfl_prop_consensus
from dfs_optimizer.models import ContestFormat, Platform, Player, Position, Projection, Slate
from dfs_optimizer.services.props import apply_nfl_prop_role_signals


class NFLPropTests(unittest.TestCase):
    def test_parses_median_over_lines_by_player_and_market(self) -> None:
        payload = {"bookmakers": [
            {"markets": [{"key": "player_receptions", "outcomes": [
                {"name": "Over", "description": "Example Receiver", "point": 4.5},
                {"name": "Under", "description": "Example Receiver", "point": 4.5},
            ]}]},
            {"markets": [{"key": "player_receptions", "outcomes": [
                {"name": "Over", "description": "Example Receiver", "point": 5.5},
            ]}]},
        ]}

        result = parse_nfl_prop_consensus(payload, "event")

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].markets, (("player_receptions", 5.0),))

    def test_marks_only_games_with_broad_prop_coverage_as_checked(self) -> None:
        players = tuple(
            Player(str(index), f"Player {index}", Position.WR, (Position.WR,),
                   5000, "GB", "CHI", "GB@CHI")
            for index in range(6)
        )
        slate = Slate(Platform.DRAFTKINGS, ContestFormat.CLASSIC, players, "test")
        projections = tuple(
            Projection(player.name, player.team, 8, platform_id=player.platform_id)
            for player in players
        )
        payload = {"bookmakers": [{"markets": [
            {"key": "player_receptions", "outcomes": [
                {"name": "Over", "description": f"Player {index}", "point": 3.5}
                for index in range(5)
            ]}
        ]}]}
        props = parse_nfl_prop_consensus(payload, "event")

        adjusted, matched = apply_nfl_prop_role_signals(slate, projections, props)

        self.assertEqual(matched, 5)
        self.assertTrue(all(item.prop_coverage_checked for item in adjusted))
        self.assertEqual(adjusted[-1].prop_market_count, 0)


if __name__ == "__main__":
    unittest.main()
