from __future__ import annotations

import io
import tempfile
import unittest
import zipfile
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from dfs_optimizer.app_state import restore_run_session
from dfs_optimizer.models import Platform
from dfs_optimizer.optimization import generate_classic_lineups
from dfs_optimizer.services import (
    PlayerContext,
    build_run_archive,
    compare_runs,
    import_run_archive,
    list_run_records,
    load_run_context_inputs,
    mark_run_final,
    restore_run,
    save_run_archive,
    update_run_label,
)
from dfs_optimizer.services.player_context import player_context_snapshot
from dfs_optimizer.services.run_history import run_input_coverage
from dfs_optimizer.services.run_history import restore_shadow_run
from test_classic_optimizer import make_slate


def draftkings_salary_content(slate) -> bytes:
    header = (
        "Position,Name + ID,Name,ID,Roster Position,Salary,Game Info,"
        "TeamAbbrev,AvgPointsPerGame,Status\n"
    )
    rows = []
    for player in slate.players:
        position = player.primary_position.value
        rows.append(
            f"{position},{player.name} ({player.platform_id}),{player.name},"
            f"{player.platform_id},{position},5000,{player.team}@OPP 10/25/2026 01:00PM ET,"
            f"{player.team},0,\n"
        )
    return (header + "".join(rows)).encode()


class RunHistoryTests(unittest.TestCase):
    def test_imports_downloaded_archive_and_makes_it_restorable(self) -> None:
        slate, matches = make_slate(Platform.DRAFTKINGS)
        projections = tuple(matches.by_player_id.values())
        lineups = generate_classic_lineups(slate, matches, 1)
        content = build_run_archive(
            slate,
            projections,
            lineups,
            {"lineups": 1},
            draftkings_salary_content(slate),
            run_id="portable-run",
            run_label="Sunday final",
        )

        with tempfile.TemporaryDirectory() as folder:
            imported = import_run_archive(content, folder)
            restored_slate, restored_projections, restored_lineups, _, settings = (
                restore_run(imported)
            )

            self.assertEqual(imported.run_id, "portable-run")
            self.assertEqual(imported.label, "Sunday final")
            self.assertEqual(restored_slate.platform, slate.platform)
            self.assertEqual(len(restored_projections), len(projections))
            self.assertEqual(len(restored_lineups), 1)
            self.assertEqual(settings["lineups"], 1)

            state = {"submission_snapshot": b"old", "current_config_key": "old"}
            restore_run_session(state, imported)
            self.assertEqual(state["current_run_id"], "portable-run")
            self.assertEqual(len(state["lineups"]), 1)
            self.assertEqual(state["base_projections"], state["projections"])
            self.assertIsNone(state["submission_snapshot"])
            self.assertIsNone(state["current_config_key"])

    def test_rejects_tampered_import_without_saving_it(self) -> None:
        slate, matches = make_slate(Platform.DRAFTKINGS)
        projections = tuple(matches.by_player_id.values())
        lineups = generate_classic_lineups(slate, matches, 1)
        content = build_run_archive(
            slate, projections, lineups, {}, draftkings_salary_content(slate),
            run_id="tampered-run"
        )
        source = zipfile.ZipFile(io.BytesIO(content))
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as changed:
            for name in source.namelist():
                value = source.read(name)
                if name == "lineups.csv":
                    value += b"changed"
                changed.writestr(name, value)
        source.close()

        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError, "integrity check failed"):
                import_run_archive(output.getvalue(), folder)

            self.assertEqual(list_run_records(folder), ())

    def test_restores_hidden_ab_control_portfolio(self) -> None:
        slate, matches = make_slate(Platform.DRAFTKINGS)
        projections = tuple(matches.by_player_id.values())
        lineups = generate_classic_lineups(slate, matches, 1)
        content = build_run_archive(
            slate, projections, lineups, {}, draftkings_salary_content(slate),
            run_id="ab-run",
            shadow_projections=projections,
            shadow_lineups=lineups,
            experiment={"name": "weekly-context-ab-v1"},
        )

        with tempfile.TemporaryDirectory() as folder:
            record = import_run_archive(content, folder)
            restored_projections, restored_lineups = restore_shadow_run(record)

        self.assertEqual(len(restored_projections), len(projections))
        self.assertEqual(len(restored_lineups), 1)

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
                    input_snapshots={
                        "weekly-context.json": (
                            '{"player_observations":[{"platform_id":"qb",'
                            '"name":"Quarterback","practice_participation":"%s"}],'
                            '"teams":[{"team":"DAL","wind_mph":%d}]}'
                            % ("DNP" if number == 1 else "FP", 10 + number * 5)
                        ).encode(),
                    },
                )
                save_run_archive(content, slate, folder, created, run_id)

            records = list_run_records(folder)
            self.assertEqual([item.run_id for item in records], ["run-2", "run-1"])
            comparison = compare_runs(records[1], records[0])
            self.assertEqual(comparison.changed_projection_count, len(projections))
            self.assertEqual(comparison.lineup_overlap_percent, 100)
            self.assertTrue(any(
                item["Signal"] == "Practice"
                for item in comparison.context_changes
            ))
            self.assertTrue(run_input_coverage(records[0])["Weekly context"])

            update_run_label("run-1", "Wednesday baseline", folder)
            mark_run_final(records[0], folder)
            updated = list_run_records(folder)
            self.assertEqual(updated[1].label, "Wednesday baseline")
            self.assertTrue(updated[0].is_final)


if __name__ == "__main__":
    unittest.main()
