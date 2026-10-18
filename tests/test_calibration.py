from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from types import SimpleNamespace

from dfs_optimizer.backtesting import PlayerResult, evaluate_projection_rows, evaluate_projections
from dfs_optimizer.models import Platform
from dfs_optimizer.services.calibration import (
    aggregate_calibration_segments,
    aggregate_winner_strategy_bands,
    calibration_record,
    list_calibration_records,
    save_calibration_record,
)
from test_classic_optimizer import make_slate


class CalibrationLedgerTests(unittest.TestCase):
    def test_aggregates_winner_strategy_bands_by_unique_lineup_count(self) -> None:
        combined = aggregate_winner_strategy_bands((
            {"winner_strategy_bands": {"Top 1%": {
                "unique_lineups": 2, "average_salary_left": 100,
                "qb_stack_rate": .5,
            }}},
            {"winner_strategy_bands": {"Top 1%": {
                "unique_lineups": 1, "average_salary_left": 400,
                "qb_stack_rate": 1,
            }}},
        ))

        self.assertEqual(combined["Top 1%"]["slates"], 2)
        self.assertEqual(combined["Top 1%"]["unique_lineups"], 3)
        self.assertEqual(combined["Top 1%"]["average_salary_left"], 200)
        self.assertAlmostEqual(combined["Top 1%"]["qb_stack_rate"], 2 / 3)

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
        self.assertEqual(saved[0]["sport"], "nfl")
        self.assertEqual(saved[0]["projection_metrics"]["mae"], 2)
        self.assertEqual(saved[0]["projection_metrics"]["ownership_samples"], 0)
        self.assertEqual(saved[0]["position_metrics"]["WR"]["players"], 2)

    def test_records_salary_confidence_ownership_and_roi_segments(self) -> None:
        slate, matches = make_slate(Platform.DRAFTKINGS)
        source = tuple(matches.by_player_id.values())[:3]
        salary_by_id = {
            source[0].platform_id: 3000,
            source[1].platform_id: 5000,
            source[2].platform_id: 7000,
        }
        slate = replace(slate, players=tuple(
            replace(player, salary=salary_by_id.get(player.platform_id, player.salary))
            for player in slate.players
        ))
        projections = tuple(
            type(item)(
                item.name, item.team, item.projected_points,
                platform_id=item.platform_id,
                floor=item.projected_points * .7,
                ceiling=item.projected_points * 1.3,
                projected_ownership=10 + index,
                bust_probability=.15 if index == 0 else .6,
            )
            for index, item in enumerate(source)
        )
        actuals = tuple(
            PlayerResult(item.name, "WR", 12, item.projected_points - 2)
            for item in projections
        )
        metrics = evaluate_projections(projections, actuals)
        rows = evaluate_projection_rows(projections, actuals)
        record = calibration_record(
            "run-segments", slate, metrics, rows, 100, 200,
            (SimpleNamespace(rank=10, score=150),),
            entry_fee=5,
            total_winnings=12,
        )

        self.assertEqual(set(record["salary_metrics"]), {"Value", "Mid-range", "Premium"})
        self.assertEqual(record["confidence_metrics"]["High"]["players"], 1)
        self.assertEqual(record["confidence_metrics"]["Low"]["players"], 2)
        self.assertEqual(record["entry_cost"], 5)
        self.assertEqual(record["roi"], 1.4)

    def test_aggregates_segment_totals_across_slates(self) -> None:
        records = (
            {"position_metrics": {"WR": {
                "players": 2, "absolute_error_total": 6, "error_total": 2,
                "zero_players": 1, "ownership_samples": 2,
                "ownership_absolute_error_total": 4,
                "ownership_error_total": -2,
            }}},
            {"position_metrics": {"WR": {
                "players": 1, "absolute_error_total": 6, "error_total": -6,
                "zero_players": 0, "ownership_samples": 1,
                "ownership_absolute_error_total": 2,
                "ownership_error_total": 2,
            }}},
        )

        combined = aggregate_calibration_segments(records, "position_metrics")

        self.assertEqual(combined["WR"]["mae"], 4)
        self.assertAlmostEqual(combined["WR"]["bias"], -4 / 3)
        self.assertAlmostEqual(combined["WR"]["zero_rate"], 1 / 3)
        self.assertEqual(combined["WR"]["ownership_mae"], 2)

    def test_aggregates_legacy_segment_averages(self) -> None:
        combined = aggregate_calibration_segments(({
            "position_metrics": {
                "WR": {"players": 2, "mae": 3, "bias": -1}
            }
        },), "position_metrics")

        self.assertEqual(combined["WR"]["mae"], 3)
        self.assertEqual(combined["WR"]["bias"], -1)


if __name__ == "__main__":
    unittest.main()
