from __future__ import annotations

import tempfile
import unittest
import zipfile
import io
from os import utime
from pathlib import Path
from time import time

from dfs_optimizer.services import (
    historical_data_coverage,
    historical_data_paths,
    nfl_historical_input_snapshot,
)


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
            self.assertEqual(
                paths.snap_files,
                (
                    Path(directory) / "snap_counts_2025.csv",
                    Path(directory) / "snap_counts_2026.csv",
                ),
            )
            self.assertEqual(paths.games_file, Path(directory) / "games.csv")
            self.assertEqual(len(paths.missing), 7)
            self.assertIsNone(paths.age_hours)

    def test_reports_age_from_oldest_historical_input(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = historical_data_paths(2026, directory)
            all_paths = (
                *paths.player_files, *paths.team_files, *paths.snap_files,
                paths.games_file,
            )
            for path in all_paths:
                path.write_text("test", encoding="utf-8")
            old_time = time() - 18 * 3600
            utime(paths.player_files[0], (old_time, old_time))

            self.assertGreaterEqual(paths.age_hours, 17.9)

    def test_reports_latest_current_season_stats_and_snap_weeks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = historical_data_paths(2026, directory)
            paths.player_files[1].write_text(
                "season,week,season_type\n2025,18,REG\n2026,4,REG\n2026,5,POST\n",
                encoding="utf-8",
            )
            paths.snap_files[1].write_text(
                "season,week,game_type\n2026,2,REG\n2026,3,REG\n",
                encoding="utf-8",
            )

            coverage = historical_data_coverage(paths, 2026)

            self.assertEqual(coverage.stats_week, 4)
            self.assertEqual(coverage.snap_week, 3)

    def test_snapshots_exact_historical_inputs_for_future_rebuilds(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = historical_data_paths(2026, directory)
            all_paths = (
                *paths.player_files, *paths.team_files, *paths.snap_files,
                paths.games_file,
            )
            for index, path in enumerate(all_paths):
                path.write_text(f"source-{index}\n", encoding="utf-8")

            content = nfl_historical_input_snapshot(2026, directory)

            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                self.assertEqual(
                    set(archive.namelist()), {path.name for path in all_paths}
                )
                self.assertEqual(
                    archive.read(paths.player_files[0].name), b"source-0\n"
                )

    def test_snapshot_requires_every_model_input(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(FileNotFoundError):
                nfl_historical_input_snapshot(2026, directory)


if __name__ == "__main__":
    unittest.main()
