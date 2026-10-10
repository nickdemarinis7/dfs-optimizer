from __future__ import annotations

import io
import json
import unittest
import zipfile
from datetime import datetime, timezone
from pathlib import Path
import tempfile

from dfs_optimizer.models import Platform
from dfs_optimizer.optimization import generate_classic_lineups
from dfs_optimizer.services import build_run_archive, save_run_archive
from test_classic_optimizer import make_slate


class RunArchiveTests(unittest.TestCase):
    def test_contains_manifest_projections_and_lineups(self) -> None:
        slate, matches = make_slate(Platform.DRAFTKINGS)
        lineups = generate_classic_lineups(slate, matches, 1)

        content = build_run_archive(
            slate,
            tuple(matches.by_player_id.values()),
            lineups,
            {"preset": "test"},
            b"salary-header\n",
        )

        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            self.assertEqual(
                set(archive.namelist()),
                {
                    "manifest.json",
                    "lineups.csv",
                    "projections.csv",
                    "salary/synthetic.csv",
                },
            )
            manifest = json.loads(archive.read("manifest.json"))
            self.assertEqual(manifest["settings"], {"preset": "test"})
            self.assertEqual(manifest["lineup_count"], 1)
            self.assertEqual(manifest["sport"], "nfl")
            self.assertEqual(archive.read("salary/synthetic.csv"), b"salary-header\n")

    def test_persists_archive_with_stable_run_name(self) -> None:
        slate, _ = make_slate(Platform.DRAFTKINGS)
        with tempfile.TemporaryDirectory() as folder:
            destination = save_run_archive(
                b"archive",
                slate,
                folder,
                datetime(2026, 10, 4, 17, 30, tzinfo=timezone.utc),
            )

            self.assertEqual(
                destination.name,
                "20261004T173000Z-draftkings-classic.zip",
            )
            self.assertEqual(destination.read_bytes(), b"archive")


if __name__ == "__main__":
    unittest.main()
