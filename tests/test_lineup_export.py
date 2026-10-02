from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from dfs_optimizer.exporters import export_lineups_csv, merge_lineups_into_template
from dfs_optimizer.importers import ProjectionMatchResult
from dfs_optimizer.models import Platform
from dfs_optimizer.optimization import generate_classic_lineups
from test_classic_optimizer import make_slate


class LineupExportTests(unittest.TestCase):
    def test_exports_draftkings_name_and_id_cells(self) -> None:
        slate, matches = make_slate(Platform.DRAFTKINGS)
        lineups = generate_classic_lineups(slate, matches, 2)
        with tempfile.TemporaryDirectory() as directory:
            path = export_lineups_csv(lineups, slate.platform, Path(directory) / "dk.csv")
            with path.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.reader(handle))

        self.assertEqual(rows[0], ["QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX", "DST"])
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(" (" in value and value.endswith(")") for value in rows[1]))

    def test_exports_fanduel_ids(self) -> None:
        slate, matches = make_slate(Platform.FANDUEL)
        lineups = generate_classic_lineups(slate, matches, 1)
        with tempfile.TemporaryDirectory() as directory:
            path = export_lineups_csv(lineups, slate.platform, Path(directory) / "fd.csv")
            with path.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.reader(handle))

        self.assertTrue(all(value in matches.by_player_id for value in rows[1]))

    def test_fills_rosters_without_replacing_entry_metadata(self) -> None:
        slate, matches = make_slate(Platform.DRAFTKINGS)
        lineups = generate_classic_lineups(slate, matches, 2)
        template = (
            "Entry ID,Contest Name,QB,RB,RB,WR,WR,WR,TE,FLEX,DST\n"
            "entry-1,Millionaire,,,,,,,,,\n"
            "entry-2,Millionaire,,,,,,,,,\n"
        ).encode()

        completed = list(csv.reader(merge_lineups_into_template(
            lineups, slate.platform, template
        ).decode().splitlines()))

        self.assertEqual(completed[1][:2], ["entry-1", "Millionaire"])
        self.assertTrue(all(" (" in value for value in completed[1][2:]))


if __name__ == "__main__":
    unittest.main()
