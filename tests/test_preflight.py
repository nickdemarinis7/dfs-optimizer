from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from dfs_optimizer.models import Platform
from dfs_optimizer.optimization import generate_classic_lineups
from dfs_optimizer.services import PlayerContext, preflight_lineups
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

    def test_recomputed_salary_blocks_tampered_total(self) -> None:
        broken_lineup = replace(self.lineups[0], salary=0)

        report = preflight_lineups(
            self.slate, self.projections, (broken_lineup,), expected_lineups=1,
        )

        self.assertTrue(report.blocking)
        self.assertTrue(any(item.code == "salary_total" for item in report.findings))

    def test_invalid_slot_assignment_blocks_export(self) -> None:
        entries = list(self.lineups[0].entries)
        running_back_index = next(
            index for index, entry in enumerate(entries)
            if entry.player.primary_position.value == "RB"
        )
        entries[running_back_index] = replace(
            entries[running_back_index], slot="QB"
        )
        broken_lineup = replace(self.lineups[0], entries=tuple(entries))

        report = preflight_lineups(
            self.slate, self.projections, (broken_lineup,), expected_lineups=1,
        )

        self.assertTrue(report.blocking)
        self.assertTrue(any(item.code == "slot_eligibility" for item in report.findings))

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

    def test_old_player_context_warns_without_blocking(self) -> None:
        now = datetime.now(timezone.utc)
        report = preflight_lineups(
            self.slate, self.projections, self.lineups,
            expected_lineups=1, projection_built_at=now,
            player_context_built_at=now - timedelta(hours=1), now=now,
        )

        self.assertFalse(report.blocking)
        self.assertTrue(any(
            item.code == "stale_player_context" for item in report.findings
        ))

    def test_repeated_backup_tight_end_exposure_warns(self) -> None:
        tight_end = next(
            entry.player for entry in self.lineups[0].entries
            if entry.player.primary_position.value == "TE"
        )
        now = datetime.now(timezone.utc)

        report = preflight_lineups(
            self.slate,
            self.projections,
            (self.lineups[0], self.lineups[0]),
            expected_lineups=2,
            player_context=(PlayerContext(
                tight_end.platform_id, 2, None, None, True,
            ),),
            player_context_built_at=now,
            now=now,
        )

        self.assertTrue(any(
            item.code == "subordinate_skill_exposure"
            for item in report.findings
        ))


if __name__ == "__main__":
    unittest.main()
