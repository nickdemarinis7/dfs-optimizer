from __future__ import annotations

import io
import json
import unittest
import zipfile

from dfs_optimizer.models import Platform
from dfs_optimizer.optimization import generate_classic_lineups
from dfs_optimizer.services import build_run_archive
from test_classic_optimizer import make_slate


class RunArchiveTests(unittest.TestCase):
    def test_contains_manifest_projections_and_lineups(self) -> None:
        slate, matches = make_slate(Platform.DRAFTKINGS)
        lineups = generate_classic_lineups(slate, matches, 1)

        content = build_run_archive(
            slate, tuple(matches.by_player_id.values()), lineups, {"preset": "test"}
        )

        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            self.assertEqual(
                set(archive.namelist()),
                {"manifest.json", "lineups.csv", "projections.csv"},
            )
            manifest = json.loads(archive.read("manifest.json"))
            self.assertEqual(manifest["settings"], {"preset": "test"})
            self.assertEqual(manifest["lineup_count"], 1)


if __name__ == "__main__":
    unittest.main()
