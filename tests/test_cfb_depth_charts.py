from __future__ import annotations

import unittest
from types import SimpleNamespace

from dfs_optimizer.data_sources.cfb_depth_charts import (
    CFBDepthChartEntry,
    parse_cfb_depth_chart,
)
from dfs_optimizer.models import (
    ContestFormat,
    Platform,
    Player,
    Position,
    Slate,
    Sport,
)
from dfs_optimizer.services.player_context import match_cfb_depth_chart_context


class CFBDepthChartTests(unittest.TestCase):
    def test_parses_ordered_skill_position_rows(self) -> None:
        content = """
        <table>
          <tr><td>QB</td><td>14</td><td><a href='/ncaa-football-depth-charts/player/ty-dieffenbach/1'>Dieffenbach, Ty RS JR/TR</a></td><td>10</td><td><a href='/ncaa-football-depth-charts/player/madden-iamaleava/2'>Iamaleava, Madden RS FR</a></td></tr>
          <tr><td>RB</td><td>3</td><td><a href='/ncaa-football-depth-charts/player/wayne-knight/3'>Knight, Wayne RS SR/TR</a></td><td>6</td><td><a href='/ncaa-football-depth-charts/player/anthony-woods/4'>Woods, Anthony</a></td></tr>
          <tr><td>WR-X</td><td>5</td><td><a href='/ncaa-football-depth-charts/player/jaden-bray/6'>Bray, Jaden</a></td></tr>
          <tr><td>RES</td><td>17</td><td><a href='/ncaa-football-depth-charts/player/prince-strachan/7'>Strachan, Prince</a></td></tr>
          <tr><td>LT</td><td>1</td><td><a href='/ncaa-football-depth-charts/player/lineman/5'>Lineman</a></td></tr>
        </table>
        """

        entries = parse_cfb_depth_chart(content, "UCLA")

        self.assertEqual(
            [(item.position, item.name, item.depth) for item in entries],
            [
                ("QB", "ty dieffenbach", 1),
                ("QB", "madden iamaleava", 2),
                ("RB", "wayne knight", 1),
                ("RB", "anthony woods", 2),
                ("WR", "jaden bray", 1),
                ("RES", "prince strachan", 1),
            ],
        )

    def test_matches_reserve_as_a_limited_out_of_rotation_player(self) -> None:
        slate = Slate(
            Platform.DRAFTKINGS,
            ContestFormat.CLASSIC,
            (Player(
                "reserve", "Prince Strachan", Position.WR,
                (Position.WR, Position.FLEX), 3700, "WVU", "TCU",
                "WVU@TCU 10/24/2026 12:00PM ET",
            ),),
            "DKSalaries.csv",
            Sport.CFB,
        )

        contexts = match_cfb_depth_chart_context(
            slate,
            (CFBDepthChartEntry("WVU", "prince strachan", "RES", 1, True),),
        )

        self.assertEqual(contexts[0].depth_chart_position, 99)
        self.assertEqual(contexts[0].expected_role, "limited")
        self.assertIn("Ourlads reserves", contexts[0].role_note)

    def test_tolerates_cached_entries_from_before_reserve_field(self) -> None:
        slate = Slate(
            Platform.DRAFTKINGS,
            ContestFormat.CLASSIC,
            (Player(
                "starter", "Wayne Knight", Position.RB,
                (Position.RB, Position.FLEX), 8000, "UCLA", "MSU",
                "MSU@UCLA 10/24/2026 03:30PM ET",
            ),),
            "DKSalaries.csv",
            Sport.CFB,
        )
        old_cached_entry = SimpleNamespace(
            team="UCLA", name="wayne knight", position="RB", depth=1
        )

        contexts = match_cfb_depth_chart_context(slate, (old_cached_entry,))

        self.assertEqual(contexts[0].depth_chart_position, 1)
        self.assertIsNone(contexts[0].expected_role)

    def test_matches_platform_wr_to_ourlads_te_depth(self) -> None:
        slate = Slate(
            Platform.DRAFTKINGS,
            ContestFormat.CLASSIC,
            (Player(
                "kari", "Kari Ashley", Position.WR,
                (Position.WR, Position.FLEX), 5000, "TCU", "CINCY",
                "CINCY@TCU 10/24/2026 12:00PM ET",
            ),),
            "DKSalaries.csv",
            Sport.CFB,
        )

        contexts = match_cfb_depth_chart_context(
            slate,
            (CFBDepthChartEntry("TCU", "kari ashley", "TE", 2),),
        )

        self.assertEqual(contexts[0].depth_chart_position, 2)

    def test_matches_depth_order_to_salary_players(self) -> None:
        slate = Slate(
            Platform.DRAFTKINGS,
            ContestFormat.CLASSIC,
            (
                Player(
                    "starter", "Wayne Knight", Position.RB,
                    (Position.RB, Position.FLEX), 8000, "UCLA", "MSU",
                    "MSU@UCLA 10/24/2026 03:30PM ET",
                ),
                Player(
                    "backup", "Anthony Woods", Position.RB,
                    (Position.RB, Position.FLEX), 5000, "UCLA", "MSU",
                    "MSU@UCLA 10/24/2026 03:30PM ET",
                ),
            ),
            "DKSalaries.csv",
            Sport.CFB,
        )
        entries = (
            CFBDepthChartEntry("UCLA", "wayne knight", "RB", 1),
            CFBDepthChartEntry("UCLA", "anthony woods", "RB", 2),
        )

        contexts = match_cfb_depth_chart_context(slate, entries)

        self.assertEqual(
            {item.platform_id: item.depth_chart_position for item in contexts},
            {"starter": 1, "backup": 2},
        )


if __name__ == "__main__":
    unittest.main()
