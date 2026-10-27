from __future__ import annotations

import unittest

from dfs_optimizer.data_sources.nfl_props import parse_nfl_prop_consensus
from dfs_optimizer.models import ContestFormat, Platform, Player, Position, Projection, Slate
from dfs_optimizer.services.props import (
    apply_nfl_prop_projection_signals,
    apply_nfl_prop_role_signals,
)


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

    def test_uses_complete_skill_prop_pair_for_bounded_dk_uplift(self) -> None:
        player = Player("1", "Example Receiver", Position.WR, (Position.WR,),
                        5000, "GB", "CHI", "GB@CHI")
        slate = Slate(Platform.DRAFTKINGS, ContestFormat.CLASSIC, (player,), "test")
        projection = Projection(
            player.name, player.team, 8, platform_id=player.platform_id,
            floor=3, ceiling=16, p10=2, p25=5, p75=11, p90=14,
        )
        props = parse_nfl_prop_consensus({"bookmakers": [{"markets": [
            {"key": "player_receptions", "outcomes": [
                {"name": "Over", "description": player.name, "point": 5},
            ]},
            {"key": "player_rush_reception_yds", "outcomes": [
                {"name": "Over", "description": player.name, "point": 60},
            ]},
        ]}]}, "event")

        adjusted, matched, audit = apply_nfl_prop_projection_signals(
            slate, (projection,), props
        )

        self.assertEqual(matched, 1)
        self.assertAlmostEqual(adjusted[0].projected_points, 9.5)
        self.assertEqual(len(audit), 1)
        self.assertAlmostEqual(audit[0].implied_points, 11)

    def test_does_not_move_projection_with_only_one_skill_market(self) -> None:
        player = Player("1", "Example Receiver", Position.WR, (Position.WR,),
                        5000, "GB", "CHI", "GB@CHI")
        slate = Slate(Platform.FANDUEL, ContestFormat.CLASSIC, (player,), "test")
        projection = Projection(player.name, player.team, 8, platform_id="1")
        props = parse_nfl_prop_consensus({"bookmakers": [{"markets": [{
            "key": "player_receptions", "outcomes": [
                {"name": "Over", "description": player.name, "point": 8},
            ],
        }]}]}, "event")

        adjusted, _, audit = apply_nfl_prop_projection_signals(
            slate, (projection,), props
        )

        self.assertEqual(adjusted[0].projected_points, 8)
        self.assertEqual(audit, ())


if __name__ == "__main__":
    unittest.main()
