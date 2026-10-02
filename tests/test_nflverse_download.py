from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from dfs_optimizer.data_sources import download_nflverse_season


class NflverseDownloadTests(unittest.TestCase):
    @patch("dfs_optimizer.data_sources.nflverse.requests.get")
    def test_downloads_all_inputs_with_verified_requests(self, get: Mock) -> None:
        response = Mock(content=b"header\nvalue\n")
        get.return_value = response

        with tempfile.TemporaryDirectory() as directory:
            paths = download_nflverse_season(2026, directory)

            self.assertEqual(paths["players"].read_bytes(), response.content)
            self.assertEqual(paths["teams"].read_bytes(), response.content)
            self.assertEqual(paths["games"].read_bytes(), response.content)
            self.assertEqual(paths["players"], Path(directory) / "players_2026.csv")

        self.assertEqual(get.call_count, 3)
        get.assert_any_call(
            "https://github.com/nflverse/nflverse-data/releases/download/"
            "stats_player/stats_player_week_2026.csv",
            timeout=60,
        )
        self.assertEqual(response.raise_for_status.call_count, 3)


if __name__ == "__main__":
    unittest.main()
