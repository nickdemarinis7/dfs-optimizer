from __future__ import annotations

import tempfile
import unittest

from dfs_optimizer.backtesting import PlayerResult, evaluate_projection_rows, evaluate_projections
from dfs_optimizer.models import Platform
from dfs_optimizer.services.calibration import (
    calibration_record,
    list_calibration_records,
    save_calibration_record,
)
from test_classic_optimizer import make_slate


class CalibrationLedgerTests(unittest.TestCase):
    def test_saves_and_lists_cross_slate_record(self) -> None:
        slate, matches = make_slate(Platform.DRAFTKINGS)
        projections = tuple(matches.by_player_id.values())[:2]
        actuals = tuple(
            PlayerResult(item.name, "WR", 10, item.projected_points + 2)
            for item in projections
        )
        metrics = evaluate_projections(projections, actuals)
        rows = evaluate_projection_rows(projections, actuals)
        record = calibration_record(
            "run-1", slate, metrics, rows, 100, 200, ()
        )

        with tempfile.TemporaryDirectory() as folder:
            save_calibration_record(record, folder)
            saved = list_calibration_records(folder)

        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["run_id"], "run-1")
        self.assertEqual(saved[0]["projection_metrics"]["mae"], 2)
        self.assertEqual(saved[0]["position_metrics"]["WR"]["players"], 2)


if __name__ == "__main__":
    unittest.main()
