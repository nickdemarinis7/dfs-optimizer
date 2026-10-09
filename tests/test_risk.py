from __future__ import annotations

from pathlib import Path
import unittest

from dfs_optimizer.importers import import_salary_csv
from dfs_optimizer.models import ContestFormat, Platform, Player, Position, Projection, Slate
from dfs_optimizer.services import suggest_max_once_player_ids
from dfs_optimizer.services.risk import suggest_default_excluded_player_ids


ROOT = Path(__file__).resolve().parents[1]


class PortfolioRiskTests(unittest.TestCase):
    def test_only_suggests_usable_players_with_low_historical_floors(self) -> None:
        slate = import_salary_csv(ROOT / "samples" / "DKSalaries.csv")
        low_projection, low_floor, stable = slate.players[:3]
        projections = (
            Projection(
                low_projection.name,
                low_projection.team,
                1.5,
                platform_id=low_projection.platform_id,
            ),
            Projection(
                low_floor.name,
                low_floor.team,
                8,
                platform_id=low_floor.platform_id,
                floor=0.5,
                ceiling=20,
            ),
            Projection(
                stable.name,
                stable.team,
                12,
                platform_id=stable.platform_id,
                floor=5,
                ceiling=20,
            ),
        )

        suggestions = suggest_max_once_player_ids(slate, projections)

        self.assertNotIn(low_projection.platform_id, suggestions)
        self.assertIn(low_floor.platform_id, suggestions)
        self.assertNotIn(stable.platform_id, suggestions)

    def test_suggests_unavailable_players_and_clear_backup_quarterbacks(self) -> None:
        players = (
            Player("starter", "Starter", Position.QB, (Position.QB,), 11000, "DAL", "TB", "DAL@TB"),
            Player("backup", "Backup", Position.QB, (Position.QB,), 1000, "DAL", "TB", "DAL@TB"),
            Player("other", "Other starter", Position.QB, (Position.QB,), 10000, "TB", "DAL", "DAL@TB"),
            Player("out", "Inactive", Position.WR, (Position.WR, Position.FLEX), 5000, "DAL", "TB", "DAL@TB", status="OUT"),
        )
        slate = Slate(Platform.FANDUEL, ContestFormat.SINGLE_GAME, players, "test")
        projections = (
            Projection("Starter", "DAL", 20, platform_id="starter"),
            Projection("Backup", "DAL", 5, platform_id="backup"),
            Projection("Other starter", "TB", 18, platform_id="other"),
            Projection("Inactive", "DAL", 10, platform_id="out"),
        )

        suggestions = suggest_default_excluded_player_ids(slate, projections)

        self.assertIn("backup", suggestions)
        self.assertIn("out", suggestions)
        self.assertNotIn("starter", suggestions)
        self.assertNotIn("other", suggestions)

    def test_keeps_viable_second_quarterback_and_replacement_for_out_starter(self) -> None:
        players = (
            Player("out-starter", "Out starter", Position.QB, (Position.QB,), 11000, "DAL", "TB", "DAL@TB", status="O"),
            Player("replacement", "Replacement", Position.QB, (Position.QB,), 7000, "DAL", "TB", "DAL@TB"),
            Player("package", "Package QB", Position.QB, (Position.QB,), 6000, "TB", "DAL", "DAL@TB"),
            Player("starter", "Starter", Position.QB, (Position.QB,), 9000, "TB", "DAL", "DAL@TB"),
        )
        slate = Slate(Platform.DRAFTKINGS, ContestFormat.SINGLE_GAME, players, "test")
        projections = (
            Projection("Out starter", "DAL", 20, platform_id="out-starter"),
            Projection("Replacement", "DAL", 15, platform_id="replacement"),
            Projection("Package QB", "TB", 12, platform_id="package"),
            Projection("Starter", "TB", 16, platform_id="starter"),
        )

        suggestions = suggest_default_excluded_player_ids(slate, projections)

        self.assertIn("out-starter", suggestions)
        self.assertNotIn("replacement", suggestions)
        self.assertNotIn("package", suggestions)


if __name__ == "__main__":
    unittest.main()
