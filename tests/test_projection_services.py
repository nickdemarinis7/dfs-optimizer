from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from dfs_optimizer.services import historical_data_paths


class HistoricalProjectionServiceTests(unittest.TestCase):
    def test_resolves_current_and_previous_season_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = historical_data_paths(2026, directory)

            self.assertEqual(
                paths.player_files,
                (
                    Path(directory) / "players_2025.csv",
                    Path(directory) / "players_2026.csv",
                ),
            )
            self.assertEqual(
                paths.team_files,
                (
                    Path(directory) / "teams_2025.csv",
                    Path(directory) / "teams_2026.csv",
                ),
            )
            self.assertEqual(paths.games_file, Path(directory) / "games.csv")
            self.assertEqual(len(paths.missing), 5)


if __name__ == "__main__":
    unittest.main()
