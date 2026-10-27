from __future__ import annotations

import unittest
from dataclasses import replace

from dfs_optimizer.backtesting import PlayerResult
from dfs_optimizer.models import Platform
from dfs_optimizer.optimization import generate_classic_lineups
from dfs_optimizer.services.experiments import evaluate_weekly_context_experiment
from test_classic_optimizer import make_slate


class WeeklyContextExperimentTests(unittest.TestCase):
    def test_compares_projection_error_and_realized_lineup_scores(self) -> None:
        _, matches = make_slate(Platform.DRAFTKINGS)
        projections = tuple(matches.by_player_id.values())
        lineups = generate_classic_lineups(make_slate(Platform.DRAFTKINGS)[0], matches, 1)
        actuals = tuple(
            PlayerResult(item.name, "", 0, item.projected_points)
            for item in projections
        )
        control = tuple(
            replace(item, projected_points=item.projected_points + 2)
            for item in projections
        )

        result = evaluate_weekly_context_experiment(
            projections, lineups, control, lineups, actuals
        )

        self.assertEqual(result.treatment_metrics.mean_absolute_error, 0)
        self.assertEqual(result.control_metrics.mean_absolute_error, 2)
        self.assertEqual(result.mae_change, -2)
        self.assertEqual(result.average_lineup_score_change, 0)
        self.assertEqual(result.best_lineup_score_change, 0)


if __name__ == "__main__":
    unittest.main()
