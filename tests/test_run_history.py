from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from dfs_optimizer.models import Platform
from dfs_optimizer.optimization import generate_classic_lineups
from dfs_optimizer.services import (
    PlayerContext,
    build_run_archive,
    compare_runs,
    list_run_records,
    load_run_context_inputs,
    mark_run_final,
    save_run_archive,
    update_run_label,
)
from dfs_optimizer.services.player_context import player_context_snapshot
from test_classic_optimizer import make_slate


class RunHistoryTests(unittest.TestCase):
    def test_restores_archived_player_context_inputs(self) -> None:
        slate, matches = make_slate(Platform.DRAFTKINGS)
        projections = tuple(matches.by_player_id.values())
        lineups = generate_classic_lineups(slate, matches, 1)
        checked_at = datetime(2026, 10, 20, 16, tzinfo=timezone.utc)
        context = (PlayerContext("qb", 1, "ACTIVE", None, True),)
        with tempfile.TemporaryDirectory() as folder:
            content = build_run_archive(
                slate, projections, lineups, {}, run_id="context-run",
                input_snapshots={
                    "player-context.json": player_context_snapshot(
                        context, source="final report", checked_at=checked_at
                    ),
                    "final-status.csv": b"name,team,final_status\n",
                },
            )
            save_run_archive(content, slate, folder, run_id="context-run")
            record = list_run_records(folder)[0]

            restored = load_run_context_inputs(record)

            self.assertEqual(restored.player_context, context)
            self.assertEqual(restored.source, "final report")
            self.assertEqual(restored.checked_at, checked_at)
            self.assertEqual(restored.final_status_content, b"name,team,final_status\n")

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
