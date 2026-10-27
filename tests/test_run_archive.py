from __future__ import annotations

import io
import json
import unittest
import zipfile
from datetime import datetime, timezone
from pathlib import Path
import tempfile

from dfs_optimizer.importers import import_salary_csv
from dfs_optimizer.models import Platform
from dfs_optimizer.optimization import generate_classic_lineups
from dfs_optimizer.services import (
    CFB_FORECAST_MODEL_VERSION,
    apply_projection_confidence,
    build_cfb_projections_from_file,
    build_run_archive,
    replay_run_archive,
    save_run_archive,
)
from dfs_optimizer.importers import match_projections
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

    def test_archives_hidden_ab_control_portfolio(self) -> None:
        slate, matches = make_slate(Platform.DRAFTKINGS)
        projections = tuple(matches.by_player_id.values())
        lineups = generate_classic_lineups(slate, matches, 1)

        content = build_run_archive(
            slate, projections, lineups, {}, b"salary-header\n",
            shadow_projections=projections,
            shadow_lineups=lineups,
            experiment={"name": "weekly-context-ab-v1"},
        )

        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            self.assertIn("shadow/lineups.csv", archive.namelist())
            self.assertIn("shadow/projections.csv", archive.namelist())
            self.assertIn("shadow/lineups.csv", manifest["artifacts"])
            self.assertEqual(
                manifest["experiment"]["name"], "weekly-context-ab-v1"
            )

    def test_archives_hashed_projection_input_snapshots(self) -> None:
        slate, matches = make_slate(Platform.DRAFTKINGS)
        lineups = generate_classic_lineups(slate, matches, 1)
        content = build_run_archive(
            slate,
            tuple(matches.by_player_id.values()),
            lineups,
            {},
            input_snapshots={"model-input.csv": b"player,week\nA,1\n"},
        )

        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            self.assertEqual(
                archive.read("inputs/model-input.csv"), b"player,week\nA,1\n"
            )
            self.assertEqual(
                manifest["input_snapshots"]["model-input.csv"]["bytes"], 16
            )
            self.assertEqual(
                len(manifest["input_snapshots"]["model-input.csv"]["sha256"]), 64
            )
            self.assertEqual(
                set(manifest["artifacts"]),
                {"lineups.csv", "projections.csv"},
            )

    def test_replays_cfb_projections_and_lineup_from_archived_inputs(self) -> None:
        salary_header = (
            "Position,Name + ID,Name,ID,Roster Position,Salary,Game Info,"
            "TeamAbbrev,AvgPointsPerGame,Status\n"
        )
        specifications = (
            ("QB", "Alpha QB", "qb-a", "QB/S-FLEX", "AAA", 20),
            ("QB", "Beta QB", "qb-b", "QB/S-FLEX", "BBB", 18),
            ("RB", "Alpha RB One", "rb-a1", "RB/FLEX/S-FLEX", "AAA", 15),
            ("RB", "Alpha RB Two", "rb-a2", "RB/FLEX/S-FLEX", "AAA", 14),
            ("RB", "Beta RB One", "rb-b1", "RB/FLEX/S-FLEX", "BBB", 13),
            ("WR", "Alpha WR One", "wr-a1", "WR/FLEX/S-FLEX", "AAA", 14),
            ("WR", "Alpha WR Two", "wr-a2", "WR/FLEX/S-FLEX", "AAA", 13),
            ("WR", "Alpha WR Three", "wr-a3", "WR/FLEX/S-FLEX", "AAA", 12),
            ("WR", "Beta WR One", "wr-b1", "WR/FLEX/S-FLEX", "BBB", 11),
            ("WR", "Gamma WR", "wr-c1", "WR/FLEX/S-FLEX", "CCC", 10),
        )
        salary_content = salary_header + "".join(
            f"{position},{name} ({player_id}),{name},{player_id},{roles},5000,"
            f"{('CCC@DDD' if team == 'CCC' else 'AAA@BBB')} 10/17/2026 03:30PM ET,{team},{average},\n"
            for position, name, player_id, roles, team, average in specifications
        )
        history_header = (
            "game_id,season,week,team,opponent,completion_player,completion_yds,"
            "rush_player,rush_yds,reception_player,reception_yds,target_player,"
            "interception_thrown_player,interception_thrown_stat,touchdown_player\n"
        )
        history_rows = []
        for index, (position, name, _, _, team, _) in enumerate(specifications, 1):
            school, opponent = (
                ("Alpha", "Beta") if team == "AAA"
                else ("Beta", "Alpha") if team == "BBB"
                else ("Gamma", "Delta")
            )
            if position == "QB":
                values = (name, "200", "", "", "", "", "")
            elif position == "RB":
                values = ("", "", name, "60", "", "", "")
            else:
                values = ("", "", "", "", name, "50", name)
            history_rows.append(
                f"{index},2026,1,{school},{opponent}," + ",".join(values) + ",,,\n"
            )

        with tempfile.TemporaryDirectory() as directory:
            salary_path = Path(directory) / "DKSalaries-2026-10-17.csv"
            history_path = Path(directory) / "cfb-history.csv"
            salary_path.write_text(salary_content, encoding="utf-8")
            history_content = history_header + "".join(history_rows)
            history_path.write_text(history_content, encoding="utf-8")
            slate = import_salary_csv(salary_path)
            projections = build_cfb_projections_from_file(slate, history_path, 2)
            projections = apply_projection_confidence(slate, projections)
            lineups = generate_classic_lineups(
                slate, match_projections(slate, projections), 1
            )
            settings = {
                "projection_model_version": CFB_FORECAST_MODEL_VERSION,
                "cfb_target_week": 2,
                "lineups": 1,
                "minimum_unique_players": 1,
                "maximum_player_exposure": 1,
                "maximum_qb_exposure": 1,
                "maximum_dst_exposure": 1,
                "require_qb_stack": False,
                "require_opponent_bring_back": False,
                "ceiling_lineup_number": None,
            }
            content = build_run_archive(
                slate, projections, lineups, settings,
                salary_content.encode(),
                input_snapshots={
                    "cfb-2026-through-week-1.csv": history_content.encode()
                },
            )

        report = replay_run_archive(content)

        self.assertTrue(report.integrity_ok)
        self.assertTrue(report.reconstructable)
        self.assertTrue(report.model_version_match)
        self.assertTrue(report.projections_match)
        self.assertTrue(report.lineups_match)
        self.assertEqual(report.changed_confidence_count, 0)

    def test_detects_tampered_hashed_artifact(self) -> None:
        slate, matches = make_slate(Platform.DRAFTKINGS)
        lineups = generate_classic_lineups(slate, matches, 1)
        content = build_run_archive(
            slate, tuple(matches.by_player_id.values()), lineups, {}
        )
        source = zipfile.ZipFile(io.BytesIO(content))
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as changed:
            for name in source.namelist():
                value = source.read(name)
                if name == "projections.csv":
                    value += b"tampered"
                changed.writestr(name, value)
        source.close()

        report = replay_run_archive(output.getvalue())

        self.assertFalse(report.integrity_ok)
        self.assertTrue(any("projections.csv" in item for item in report.integrity_errors))
        self.assertFalse(report.reconstructable)


if __name__ == "__main__":
    unittest.main()
