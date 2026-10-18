from __future__ import annotations

import json
import math
from pathlib import Path
import tempfile
import unittest

from dfs_optimizer.models import ContestFormat, Platform, Player, Position, Projection, Slate, Sport
from dfs_optimizer.services.cfb_projections import build_cfb_projections_from_file
from dfs_optimizer.services.risk import suggest_player_exposure_limits


FIXTURE = Path(__file__).parent / "fixtures" / "cfb_2026_10_17_regression.json"


def _position(value: str) -> Position:
    return Position(value)


def _player(item: dict) -> Player:
    position = _position(item["position"])
    return Player(
        item["platform_id"], item["name"], position,
        (position, Position.FLEX, Position.SUPER_FLEX), item["salary"],
        item["team"], "OPP", f"{item['team']}@OPP 10/17/2026 03:30PM ET",
        platform_average=item["old_projection"],
    )


class October17CFBRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def test_incident_fixture_has_traceable_sources_and_real_zeroes(self) -> None:
        self.assertEqual(self.fixture["slate_date"], "2026-10-17")
        self.assertEqual(len(self.fixture["source_sha256"]), 4)
        self.assertTrue(all(
            len(value) == 64 for value in self.fixture["source_sha256"].values()
        ))
        self.assertTrue(all(
            item["actual_points"] == 0
            and item["selected_lineups"] > 0
            for item in self.fixture["zero_point_failures"]
        ))

    def test_stale_skill_players_do_not_receive_a_projection_on_either_site(self) -> None:
        headers = (
            "game_id,season,week,team,opponent,completion_player,completion_yds,"
            "rush_player,rush_yds,reception_player,reception_yds,target_player,"
            "interception_thrown_player,interception_thrown_stat,touchdown_player\n"
        )
        stale = [
            item for item in self.fixture["zero_point_failures"]
            if item["evidence"] == "no_current_season_events"
        ]
        for item in stale:
            with self.subTest(platform=item["platform"], player=item["name"]):
                player = _player(item)
                slate = Slate(
                    Platform(item["platform"]), ContestFormat.CLASSIC, (player,),
                    f"CFB-{item['platform']}-2026-10-17.csv", Sport.CFB,
                )
                with tempfile.TemporaryDirectory() as directory:
                    source = Path(directory) / "history.csv"
                    source.write_text(
                        headers + "1,2026,6,Other,Elsewhere,Someone Else,100,,,,,,,,\n",
                        encoding="utf-8",
                    )
                    projections = build_cfb_projections_from_file(slate, source, 7)
                self.assertNotIn(
                    item["platform_id"],
                    {projection.platform_id for projection in projections},
                )

    def test_qb_who_lost_latest_game_role_does_not_receive_a_projection(self) -> None:
        item = next(
            value for value in self.fixture["zero_point_failures"]
            if value["name"] == "Faizon Brandon"
        )
        faizon = _player(item)
        teammate = Player(
            "tenn-starter", "Tennessee Starter", Position.QB,
            (Position.QB, Position.SUPER_FLEX), 9000, "TENN", "OPP",
            "TENN@OPP 10/17/2026 03:30PM ET", platform_average=20,
        )
        slate = Slate(
            Platform.DRAFTKINGS, ContestFormat.CLASSIC, (faizon, teammate),
            "DKSalaries-2026-10-17.csv", Sport.CFB,
        )
        content = (
            "game_id,season,week,team,opponent,completion_player,completion_yds,"
            "rush_player,rush_yds,reception_player,reception_yds,target_player,"
            "interception_thrown_player,interception_thrown_stat,touchdown_player\n"
            "1,2026,5,Tennessee,Alabama,Faizon Brandon,150,,,,,,,,\n"
            "2,2026,6,Tennessee,Georgia,Tennessee Starter,220,,,,,,,,\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "history.csv"
            source.write_text(content, encoding="utf-8")
            projections = build_cfb_projections_from_file(slate, source, 7)

        projected_ids = {projection.platform_id for projection in projections}
        self.assertNotIn(item["platform_id"], projected_ids)
        self.assertIn("tenn-starter", projected_ids)

    def test_captured_jamal_roberts_exposure_is_now_capped_below_two_of_three(self) -> None:
        for item in self.fixture["exposure_failures"]:
            with self.subTest(platform=item["platform"]):
                player = _player(item)
                slate = Slate(
                    Platform(item["platform"]), ContestFormat.CLASSIC, (player,),
                    f"CFB-{item['platform']}-2026-10-17.csv", Sport.CFB,
                )
                projection = Projection(
                    item["name"], item["team"], item["old_projection"],
                    platform_id=item["platform_id"],
                    floor=item["old_projection"] * .4,
                    bust_probability=item["old_bust_probability"],
                )
                limits = suggest_player_exposure_limits(slate, (projection,))
                limit = limits[item["platform_id"]]
                allowed = max(1, math.floor(item["portfolio_size"] * limit))

                self.assertEqual(limit, item["expected_maximum_exposure"])
                self.assertLess(allowed, item["selected_lineups"])


if __name__ == "__main__":
    unittest.main()
