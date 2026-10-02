from __future__ import annotations

import unittest
from dataclasses import replace

from dfs_optimizer.models import Platform
from dfs_optimizer.optimization import generate_classic_lineups
from dfs_optimizer.services import audit_lineups
from test_classic_optimizer import make_slate


class LineupAuditTests(unittest.TestCase):
    def test_blocks_unavailable_selected_player(self) -> None:
        slate, matches = make_slate(Platform.DRAFTKINGS)
        lineups = generate_classic_lineups(slate, matches, 1)
        selected_id = lineups[0].entries[0].player.platform_id
        slate = replace(
            slate,
            players=tuple(
                replace(player, status="OUT") if player.platform_id == selected_id else player
                for player in slate.players
            ),
        )

        findings = audit_lineups(slate, lineups)

        self.assertTrue(any(item.severity == "ERROR" for item in findings))
        self.assertTrue(any(item.code == "unavailable_player" for item in findings))


if __name__ == "__main__":
    unittest.main()
