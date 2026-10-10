from __future__ import annotations

import unittest

from dfs_optimizer.data_sources.cfb_odds import parse_cfb_consensus_lines


class CFBOddsTests(unittest.TestCase):
    def test_builds_median_consensus_from_bookmakers(self) -> None:
        payload = [{
            "home_team": "Alpha Tigers",
            "away_team": "Beta Bears",
            "bookmakers": [
                {"markets": [
                    {"key": "totals", "outcomes": [
                        {"name": "Over", "point": 54.5},
                        {"name": "Under", "point": 54.5},
                    ]},
                    {"key": "spreads", "outcomes": [
                        {"name": "Alpha Tigers", "point": -6.5},
                        {"name": "Beta Bears", "point": 6.5},
                    ]},
                ]},
                {"markets": [
                    {"key": "totals", "outcomes": [
                        {"name": "Over", "point": 55.5},
                    ]},
                    {"key": "spreads", "outcomes": [
                        {"name": "Alpha Tigers", "point": -7.5},
                        {"name": "Beta Bears", "point": 7.5},
                    ]},
                ]},
            ],
        }]
        lines = parse_cfb_consensus_lines(payload)
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0].game_total, 55)
        self.assertEqual(lines[0].home_spread, -7)
        self.assertEqual(lines[0].away_spread, 7)

    def test_skips_events_missing_a_feature_market(self) -> None:
        payload = [{
            "home_team": "Alpha Tigers",
            "away_team": "Beta Bears",
            "bookmakers": [{"markets": [{
                "key": "totals",
                "outcomes": [{"name": "Over", "point": 55}],
            }]}],
        }]
        self.assertEqual(parse_cfb_consensus_lines(payload), ())


if __name__ == "__main__":
    unittest.main()
