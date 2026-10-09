from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from dfs_optimizer.exporters import lineups_csv_text
from dfs_optimizer.models import Platform
from dfs_optimizer.optimization import generate_classic_lineups
from dfs_optimizer.services.submissions import (
    compare_submitted_rosters,
    import_submitted_rosters,
    save_submission_snapshot,
    submission_snapshot_bytes,
)
from test_classic_optimizer import make_slate


class SubmissionSnapshotTests(unittest.TestCase):
    def test_imports_and_compares_final_rosters(self) -> None:
        slate, matches = make_slate(Platform.DRAFTKINGS)
        lineups = generate_classic_lineups(
            slate, matches, 2, minimum_unique_players=2
        )
        content = lineups_csv_text(lineups, slate.platform).encode()

        rosters = import_submitted_rosters(content, slate)
        comparison = compare_submitted_rosters(rosters, lineups)

        self.assertEqual(comparison.submitted_count, 2)
        self.assertEqual(comparison.exact_matches, 2)
        self.assertEqual(comparison.changed_count, 0)

    def test_persists_downloadable_snapshot(self) -> None:
        slate, matches = make_slate(Platform.FANDUEL)
        lineups = generate_classic_lineups(slate, matches, 1)
        rosters = import_submitted_rosters(
            lineups_csv_text(lineups, slate.platform).encode(), slate
        )
        comparison = compare_submitted_rosters(rosters, lineups)
        content = submission_snapshot_bytes("run-1", slate, rosters, comparison)

        with tempfile.TemporaryDirectory() as folder:
            destination = save_submission_snapshot(content, "run-1", folder)
            self.assertEqual(destination, Path(folder) / "run-1.json")
            self.assertEqual(destination.read_bytes(), content)


if __name__ == "__main__":
    unittest.main()
