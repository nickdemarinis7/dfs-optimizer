from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from dfs_optimizer.models import Platform
from dfs_optimizer.optimization import generate_classic_lineups
from dfs_optimizer.services import preflight_lineups
from test_classic_optimizer import make_slate


class PreflightTests(unittest.TestCase):
    def setUp(self) -> None:
        self.slate, self.matches = make_slate(Platform.DRAFTKINGS)
        self.lineups = generate_classic_lineups(self.slate, self.matches, 1)
        self.projections = tuple(self.matches.by_player_id.values())

    def test_valid_lineup_passes_structural_checks(self) -> None:
        now = datetime.now(timezone.utc)
        report = preflight_lineups(
            self.slate, self.projections, self.lineups,
            expected_lineups=1, projection_built_at=now, now=now,
        )

        self.assertFalse(report.blocking)
        self.assertGreaterEqual(len(report.passed), 3)

    def test_wrong_lineup_count_blocks_export(self) -> None:
        report = preflight_lineups(
            self.slate, self.projections, self.lineups, expected_lineups=3,
        )

        self.assertTrue(report.blocking)
        self.assertTrue(any(item.code == "lineup_count" for item in report.findings))

    def test_nonpositive_selected_projection_blocks_export(self) -> None:
        first = self.lineups[0].entries[0]
        broken_projection = replace(first.projection, projected_points=0)
        broken_entry = replace(first, projection=broken_projection)
        broken_lineup = replace(
            self.lineups[0], entries=(broken_entry, *self.lineups[0].entries[1:]),
        )

        report = preflight_lineups(
            self.slate, self.projections, (broken_lineup,), expected_lineups=1,
        )

        self.assertTrue(report.blocking)
        self.assertTrue(any(item.code == "nonpositive_projection" for item in report.findings))

    def test_old_projection_snapshot_warns_without_blocking(self) -> None:
        now = datetime.now(timezone.utc)
        report = preflight_lineups(
            self.slate, self.projections, self.lineups,
            expected_lineups=1,
            projection_built_at=now - timedelta(hours=8),
            now=now,
        )

        self.assertFalse(report.blocking)
        self.assertTrue(any(item.code == "stale_projections" for item in report.findings))

    def test_old_salary_file_warns_without_blocking(self) -> None:
        now = datetime.now(timezone.utc)
        report = preflight_lineups(
            self.slate, self.projections, self.lineups,
            expected_lineups=1, projection_built_at=now,
            salary_loaded_at=now - timedelta(hours=24), now=now,
        )

        self.assertFalse(report.blocking)
        self.assertTrue(any(item.code == "stale_salary_file" for item in report.findings))


if __name__ == "__main__":
    unittest.main()
