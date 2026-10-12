from __future__ import annotations

from pathlib import Path
import unittest

from dfs_optimizer.importers import import_salary_csv
from dfs_optimizer.models import ContestFormat, Platform, Player, Position, Projection, Slate, Sport
from dfs_optimizer.services import suggest_max_once_player_ids
from dfs_optimizer.services.player_context import PlayerContext
from dfs_optimizer.services.risk import suggest_default_excluded_player_ids


ROOT = Path(__file__).resolve().parents[1]


class PortfolioRiskTests(unittest.TestCase):
    def test_nfl_high_bust_skill_player_is_suggested_max_once(self) -> None:
        player = Player(
            "fragile", "Fragile Tight End", Position.TE,
            (Position.TE, Position.FLEX), 3500, "AAA", "BBB", "AAA@BBB",
        )
        slate = Slate(
            Platform.DRAFTKINGS, ContestFormat.CLASSIC, (player,), "test", Sport.NFL
        )

        suggestions = suggest_max_once_player_ids(slate, (
            Projection(
                player.name, player.team, 7.5, platform_id=player.platform_id,
                ceiling=18, bust_probability=.5,
            ),
        ))

        self.assertIn(player.platform_id, suggestions)

    def test_nfl_high_bust_signal_does_not_limit_strong_tight_end(self) -> None:
        player = Player(
            "starter", "Starting Tight End", Position.TE,
            (Position.TE, Position.FLEX), 6500, "AAA", "BBB", "AAA@BBB",
        )
        slate = Slate(
            Platform.DRAFTKINGS, ContestFormat.CLASSIC, (player,), "test", Sport.NFL
        )

        suggestions = suggest_max_once_player_ids(slate, (
            Projection(
                player.name, player.team, 14, platform_id=player.platform_id,
                floor=5, ceiling=25, bust_probability=.5,
            ),
        ))

        self.assertNotIn(player.platform_id, suggestions)

    def test_cfb_fragile_skill_player_is_suggested_max_once(self) -> None:
        player = Player(
            "fragile", "Fragile Receiver", Position.WR,
            (Position.WR, Position.FLEX), 4000, "AAA", "BBB", "AAA@BBB",
        )
        slate = Slate(
            Platform.DRAFTKINGS, ContestFormat.CLASSIC, (player,), "test", Sport.CFB
        )
        suggestions = suggest_max_once_player_ids(slate, (
            Projection(
                player.name, player.team, 11, platform_id=player.platform_id,
                floor=2, ceiling=25, bust_probability=.5,
            ),
        ))
        self.assertIn(player.platform_id, suggestions)

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

    def test_does_not_exclude_qb2_when_depth_chart_qb1_is_out(self) -> None:
        players = (
            Player(
                "out-starter", "Out starter", Position.QB, (Position.QB,),
                11000, "BAL", "ATL", "BAL@ATL", status="OUT",
            ),
            Player(
                "replacement", "Replacement", Position.QB, (Position.QB,),
                8800, "BAL", "ATL", "BAL@ATL",
            ),
        )
        slate = Slate(Platform.DRAFTKINGS, ContestFormat.SINGLE_GAME, players, "test")
        projections = (
            Projection("Out starter", "BAL", 20, platform_id="out-starter"),
            Projection("Replacement", "BAL", 5, platform_id="replacement"),
        )
        contexts = (
            PlayerContext("out-starter", 1, "OUT", None, False),
            PlayerContext("replacement", 2, None, None, True),
        )

        suggestions = suggest_default_excluded_player_ids(
            slate, projections, contexts
        )

        self.assertIn("out-starter", suggestions)
        self.assertNotIn("replacement", suggestions)


if __name__ == "__main__":
    unittest.main()
