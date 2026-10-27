from __future__ import annotations

import unittest

from dfs_optimizer.models import Platform
from dfs_optimizer.optimization import generate_classic_lineups
from dfs_optimizer.services.scenarios import simulate_lineups, validate_lineup_scripts
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
        self.assertTrue(all(item.script_type for item in first))
        self.assertTrue(all(item.rationale for item in first))

    def test_validates_multiplier_ceiling_from_final_results(self) -> None:
        slate, matches = make_slate(Platform.FANDUEL)
        lineups = generate_classic_lineups(
            slate, matches, 2, minimum_unique_players=2
        )
        analyses = simulate_lineups(lineups, simulations=100)
        names = {entry.player.name for lineup in lineups for entry in lineup.entries}
        actuals = tuple(
            type("Actual", (), {
                "name": name,
                "fantasy_points": 30 if name == lineups[0].entries[0].player.name else 5,
            })()
            for name in names
        )

        validation = validate_lineup_scripts(lineups, analyses, actuals)

        self.assertEqual(len(validation), 2)
        self.assertIn(validation[0].verdict, {"Supported", "Inconclusive", "Contradicted"})

    def test_rejects_too_few_simulations(self) -> None:
        slate, matches = make_slate(Platform.FANDUEL)
        lineup = generate_classic_lineups(slate, matches, 1)
        with self.assertRaisesRegex(ValueError, "at least 100"):
            simulate_lineups(lineup, simulations=99)


if __name__ == "__main__":
    unittest.main()
