from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from dfs_optimizer.models import Platform
from dfs_optimizer.optimization import generate_classic_lineups
from dfs_optimizer.services import (
    build_run_archive,
    compare_runs,
    list_run_records,
    mark_run_final,
    save_run_archive,
    update_run_label,
)
from test_classic_optimizer import make_slate


class RunHistoryTests(unittest.TestCase):
    def test_lists_labels_marks_final_and_compares_runs(self) -> None:
        slate, matches = make_slate(Platform.DRAFTKINGS)
        projections = tuple(matches.by_player_id.values())
        lineups = generate_classic_lineups(slate, matches, 1)
        start = datetime(2026, 10, 7, 12, tzinfo=timezone.utc)

        with tempfile.TemporaryDirectory() as folder:
            for number, created in enumerate((start, start + timedelta(days=4)), 1):
                run_id = f"run-{number}"
                adjusted = tuple(
                    replace(item, projected_points=item.projected_points + number - 1)
                    for item in projections
                )
                content = build_run_archive(
                    slate,
                    adjusted,
                    lineups,
                    {},
                    run_id=run_id,
                    run_label=f"Run {number}",
                    created_at=created,
                )
                save_run_archive(content, slate, folder, created, run_id)

            records = list_run_records(folder)
            self.assertEqual([item.run_id for item in records], ["run-2", "run-1"])
            comparison = compare_runs(records[1], records[0])
            self.assertEqual(comparison.changed_projection_count, len(projections))
            self.assertEqual(comparison.lineup_overlap_percent, 100)

            update_run_label("run-1", "Wednesday baseline", folder)
            mark_run_final(records[0], folder)
            updated = list_run_records(folder)
            self.assertEqual(updated[1].label, "Wednesday baseline")
            self.assertTrue(updated[0].is_final)


if __name__ == "__main__":
    unittest.main()
