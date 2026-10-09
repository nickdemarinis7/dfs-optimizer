from __future__ import annotations

import unittest

from dfs_optimizer.models import Platform
from dfs_optimizer.optimization import generate_classic_lineups
from dfs_optimizer.services.scenarios import simulate_lineups
from test_classic_optimizer import make_slate


class ScenarioSimulationTests(unittest.TestCase):
    def test_is_deterministic_and_assigns_portfolio_lead_rates(self) -> None:
        slate, matches = make_slate(Platform.DRAFTKINGS)
        lineups = generate_classic_lineups(
            slate, matches, 2, minimum_unique_players=2
        )

        first = simulate_lineups(lineups, simulations=500, seed=42)
        second = simulate_lineups(lineups, simulations=500, seed=42)

        self.assertEqual(first, second)
        self.assertAlmostEqual(sum(item.top_rate for item in first), 1)
        self.assertTrue(all(item.p90 >= item.p75 for item in first))
        self.assertTrue(all(item.label for item in first))

    def test_rejects_too_few_simulations(self) -> None:
        slate, matches = make_slate(Platform.FANDUEL)
        lineup = generate_classic_lineups(slate, matches, 1)
        with self.assertRaisesRegex(ValueError, "at least 100"):
            simulate_lineups(lineup, simulations=99)


if __name__ == "__main__":
    unittest.main()
