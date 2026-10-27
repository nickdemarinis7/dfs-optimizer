from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from dfs_optimizer.data_sources.nfl_news import (
    fetch_nfl_news_candidates,
    nfl_news_snapshot,
)
from dfs_optimizer.models import ContestFormat, Platform, Player, Position, Slate


class NFLNewsTests(unittest.TestCase):
    @patch("dfs_optimizer.data_sources.nfl_news.requests.get")
    def test_matches_attributed_role_headline_to_slate_player(self, get: Mock) -> None:
        response = Mock()
        response.raise_for_status.return_value = None
        response.content = b"""<?xml version='1.0'?><rss><channel><item>
          <title>Coach says Kenneth Walker will return to starting workload</title>
          <link>https://news.example/report</link>
          <pubDate>Tue, 27 Oct 2026 14:00:00 GMT</pubDate>
          <source>Example News</source>
        </item></channel></rss>"""
        get.return_value = response
        slate = Slate(
            Platform.DRAFTKINGS, ContestFormat.CLASSIC,
            (Player("1", "Kenneth Walker III", Position.RB, (Position.RB,), 7000, "SEA", "SF", "SEA@SF"),),
            "salaries.csv",
        )

        candidates = fetch_nfl_news_candidates(slate)

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].matched_players, ("Kenneth Walker III",))
        self.assertIn("coach", candidates[0].topics)
        self.assertIn("return", candidates[0].topics)
        self.assertIn(b"Example News", nfl_news_snapshot(candidates))


if __name__ == "__main__":
    unittest.main()
