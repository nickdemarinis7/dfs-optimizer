from __future__ import annotations

from pathlib import Path
import unittest

from dfs_optimizer.importers import import_salary_csv
from dfs_optimizer.models import Projection
from dfs_optimizer.services import suggest_max_once_player_ids


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


if __name__ == "__main__":
    unittest.main()
