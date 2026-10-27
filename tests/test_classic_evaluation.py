from __future__ import annotations

import unittest

from dfs_optimizer.services.classic_evaluation import (
    build_classic_scorecard,
    scorecard_rows,
)


def record(run_id: str, *, top_percent: float | None, entries: int = 3) -> dict:
    return {
        "run_id": run_id,
        "recorded_at_utc": f"2026-10-{run_id[-1]}T12:00:00+00:00",
        "sport": "nfl",
        "contest_format": "classic",
        "platform": "draftkings",
        "submitted_entries": entries,
        "best_top_percent": top_percent,
        "average_top_percent": top_percent + 5 if top_percent is not None else None,
        "best_score": 180 if entries else None,
        "winning_score": 220,
        "lineup_roster_slots": 27,
        "lineup_zero_slots": 1,
        "projection_metrics": {
            "matched_players": 10,
            "mae": 4,
            "bias": 1,
            "ownership_samples": 8,
            "ownership_mae": 5,
            "ownership_bias": -2,
        },
        "player_calibration": [{
            "player": "Repeat Player",
            "projected_points": 15,
            "actual_points": 5,
        }, {
            "player": "Prop Player",
            "projected_points": 12,
            "actual_points": 14,
        }],
        "nfl_prop_adjustments": [{
            "player": "Prop Player",
            "original_projection": 10,
            "adjusted_projection": 12,
        }],
    }


class ClassicScorecardTests(unittest.TestCase):
    def test_aggregates_only_nfl_classic_and_verified_finish_records(self) -> None:
        first = record("run-1", top_percent=8)
        second = record("run-2", top_percent=2)
        unsubmitted = record("run-3", top_percent=None, entries=0)
        showdown = record("run-4", top_percent=.5)
        showdown["contest_format"] = "single_game"

        result = build_classic_scorecard((first, second, unsubmitted, showdown))

        self.assertEqual(result.slates, 3)
        self.assertEqual(result.scored_portfolios, 2)
        self.assertEqual(result.submitted_entries, 6)
        self.assertEqual(result.best_top_percent_median, 5)
        self.assertEqual(result.top_ten_rate, 1)
        self.assertEqual(result.average_winner_gap, 40)
        self.assertAlmostEqual(result.lineup_zero_rate, 1 / 27)
        self.assertEqual(result.recurring_misses[0]["Player"], "Repeat Player")
        self.assertEqual(result.prop_evaluation["samples"], 3)
        self.assertEqual(result.prop_evaluation["mae_change"], -2)

    def test_deduplicates_rewritten_record_by_run_id(self) -> None:
        older = record("run-1", top_percent=20)
        newer = record("run-1", top_percent=1)
        newer["recorded_at_utc"] = "2026-11-01T12:00:00+00:00"

        result = build_classic_scorecard((older, newer))

        self.assertEqual(result.slates, 1)
        self.assertEqual(result.best_top_percent_median, 1)
        self.assertEqual(len(scorecard_rows(result)), 1)

    def test_reports_missing_evidence_without_fabricating_metrics(self) -> None:
        result = build_classic_scorecard(())

        self.assertEqual(result.slates, 0)
        self.assertIsNone(result.weighted_projection_mae)
        self.assertIsNone(result.top_one_rate)
        self.assertTrue(result.data_gaps)


if __name__ == "__main__":
    unittest.main()
