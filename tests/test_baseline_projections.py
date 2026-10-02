from __future__ import annotations

import unittest

from dfs_optimizer.models import ContestFormat, Platform, Player, Position, Slate
from dfs_optimizer.projections import build_platform_average_projections


def make_player(
    player_id: str, average: float | None, status: str | None = None
) -> Player:
    return Player(
        platform_id=player_id,
        name=f"Player {player_id}",
        primary_position=Position.WR,
        roster_positions=(Position.WR, Position.FLEX),
        salary=5_000,
        team="AAA",
        opponent="BBB",
        game="AAA@BBB",
        platform_average=average,
        status=status,
    )


class BaselineProjectionTests(unittest.TestCase):
    def test_uses_available_player_averages(self) -> None:
        slate = Slate(
            platform=Platform.DRAFTKINGS,
            contest_format=ContestFormat.CLASSIC,
            players=(make_player("1", 12.5), make_player("2", 9.0, "Q")),
            source_name="test.csv",
        )
        projections = build_platform_average_projections(slate)

        self.assertEqual([item.projected_points for item in projections], [12.5, 9.0])

    def test_excludes_unavailable_and_missing_average_players(self) -> None:
        slate = Slate(
            platform=Platform.FANDUEL,
            contest_format=ContestFormat.CLASSIC,
            players=(
                make_player("1", 10.0, "IR"),
                make_player("2", 10.0, "OUT"),
                make_player("3", 10.0, "O"),
                make_player("4", None),
                make_player("5", 8.0),
            ),
            source_name="test.csv",
        )
        projections = build_platform_average_projections(slate)

        self.assertEqual([item.platform_id for item in projections], ["5"])


if __name__ == "__main__":
    unittest.main()

