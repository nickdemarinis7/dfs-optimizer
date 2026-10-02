from __future__ import annotations

import unittest

from dfs_optimizer.models import Player, Position, Projection
from dfs_optimizer.optimization import LineupEntry, OptimizedLineup
from dfs_optimizer.services import analyze_portfolio


def entry(player_id: str, position: Position, status: str | None = None) -> LineupEntry:
    player = Player(
        player_id,
        f"Player {player_id}",
        position,
        (position,),
        5_000,
        "AAA",
        "BBB",
        "AAA@BBB",
        status=status,
    )
    projection = Projection(player.name, player.team, 10, platform_id=player_id)
    return LineupEntry(position.value, player, projection)


class PortfolioDiagnosticsTests(unittest.TestCase):
    def test_flags_concentration_projection_drop_and_status(self) -> None:
        shared = entry("shared", Position.WR, "Q")
        quarterback = entry("qb", Position.QB)
        lineups = (
            OptimizedLineup((quarterback, shared, entry("a", Position.RB)), 15_000, 30, 50_000),
            OptimizedLineup((quarterback, shared, entry("b", Position.RB)), 15_000, 20, 50_000),
        )

        result = analyze_portfolio(lineups, projected_player_count=2, salary_player_count=10)

        self.assertEqual(result.unique_quarterbacks, 1)
        self.assertEqual(result.maximum_exposure_count, 2)
        self.assertEqual(result.average_shared_players, 2)
        self.assertEqual(result.projection_spread, 10)
        self.assertEqual(result.full_exposure_players, ("Player qb", "Player shared"))
        self.assertTrue(any("same quarterback" in warning for warning in result.warnings))
        self.assertTrue(any("20%" in warning for warning in result.warnings))
        self.assertTrue(any("Player shared (Q)" in warning for warning in result.warnings))


if __name__ == "__main__":
    unittest.main()
