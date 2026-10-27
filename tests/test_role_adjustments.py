from __future__ import annotations

import unittest

from dfs_optimizer.models import ContestFormat, Platform, Player, Position, Projection, Slate
from dfs_optimizer.services.player_context import PlayerContext
from dfs_optimizer.services.role_adjustments import apply_current_role_adjustments


class CurrentRoleAdjustmentTests(unittest.TestCase):
    def test_promotes_replacement_qb_when_qb1_is_out(self) -> None:
        players = (
            Player(
                "qb1", "Injured starter", Position.QB, (Position.QB,),
                10800, "BAL", "ATL", "BAL@ATL", status="OUT",
            ),
            Player(
                "qb2", "Replacement", Position.QB, (Position.QB,),
                8800, "BAL", "ATL", "BAL@ATL",
            ),
            Player(
                "qb3", "Third string", Position.QB, (Position.QB,),
                5000, "BAL", "ATL", "BAL@ATL",
            ),
        )
        slate = Slate(Platform.DRAFTKINGS, ContestFormat.SINGLE_GAME, players, "test")
        projections = (
            Projection(
                "Injured starter", "BAL", 20, platform_id="qb1",
                floor=10, ceiling=30, p10=7, p25=12, p75=25, p90=32,
                bust_probability=.15,
            ),
            Projection(
                "Replacement", "BAL", 4, platform_id="qb2",
                floor=1, ceiling=12, p10=.5, p25=2, p75=7, p90=13,
                bust_probability=.40,
            ),
            Projection("Third string", "BAL", 2, platform_id="qb3"),
        )
        contexts = (
            PlayerContext("qb1", 1, "OUT", None, False),
            PlayerContext("qb2", 2, None, None, True),
            PlayerContext("qb3", 3, None, None, True),
        )

        adjusted, audit = apply_current_role_adjustments(
            slate, projections, contexts
        )

        by_id = {item.platform_id: item for item in adjusted}
        self.assertEqual(by_id["qb2"].projected_points, 14)
        self.assertEqual(by_id["qb2"].floor, 7)
        self.assertEqual(by_id["qb2"].ceiling, 21)
        self.assertEqual(by_id["qb3"].projected_points, 2)
        self.assertEqual(len(audit), 1)
        self.assertIn("replacement QB", audit[0].reason)

    def test_reduces_backup_tight_end_behind_active_te1(self) -> None:
        players = (
            Player("te1", "Starter", Position.TE, (Position.TE,), 6000, "LV", "NE", "LV@NE"),
            Player("te2", "Former fill in", Position.TE, (Position.TE,), 3000, "LV", "NE", "LV@NE"),
        )
        slate = Slate(Platform.DRAFTKINGS, ContestFormat.CLASSIC, players, "test")
        projections = (
            Projection("Starter", "LV", 12, platform_id="te1", floor=6, ceiling=20),
            Projection(
                "Former fill in", "LV", 8, platform_id="te2",
                floor=3, ceiling=14, p10=1, p25=3, p75=10, p90=14,
                bust_probability=.30, opportunity_stability=.25,
            ),
        )
        contexts = (
            PlayerContext("te1", 1, None, None, True),
            PlayerContext("te2", 2, None, None, True),
        )

        adjusted, audit = apply_current_role_adjustments(
            slate, projections, contexts
        )

        by_id = {item.platform_id: item for item in adjusted}
        self.assertEqual(by_id["te1"].projected_points, 12)
        self.assertAlmostEqual(by_id["te2"].projected_points, 6)
        self.assertAlmostEqual(by_id["te2"].ceiling, 10.5)
        self.assertGreater(by_id["te2"].bust_probability, .30)
        self.assertEqual(audit[0].depth_order, 2)
        self.assertIn("opportunity decline", audit[0].reason)

    def test_does_not_reduce_te2_median_when_recent_role_is_stable(self) -> None:
        players = (
            Player("te1", "Starter", Position.TE, (Position.TE,), 6000, "DET", "ARI", "DET@ARI"),
            Player("te2", "Package tight end", Position.TE, (Position.TE,), 4000, "DET", "ARI", "DET@ARI"),
        )
        slate = Slate(Platform.DRAFTKINGS, ContestFormat.SINGLE_GAME, players, "test")
        projections = (
            Projection("Starter", "DET", 13, platform_id="te1"),
            Projection(
                "Package tight end", "DET", 8, platform_id="te2",
                floor=3, ceiling=16, opportunity_stability=.85,
            ),
        )
        contexts = (
            PlayerContext("te1", 1, None, None, True),
            PlayerContext("te2", 2, None, None, True),
        )

        adjusted, audit = apply_current_role_adjustments(slate, projections, contexts)

        self.assertEqual(adjusted, projections)
        self.assertEqual(audit, ())

    def test_does_not_penalize_backup_when_starter_is_out(self) -> None:
        players = (
            Player("te1", "Starter", Position.TE, (Position.TE,), 6000, "LV", "NE", "LV@NE"),
            Player("te2", "Replacement", Position.TE, (Position.TE,), 3000, "LV", "NE", "LV@NE"),
        )
        slate = Slate(Platform.DRAFTKINGS, ContestFormat.CLASSIC, players, "test")
        projections = tuple(
            Projection(player.name, player.team, 10, platform_id=player.platform_id)
            for player in players
        )
        contexts = (
            PlayerContext("te1", 1, "OUT", None, False),
            PlayerContext("te2", 2, None, None, True),
        )

        adjusted, audit = apply_current_role_adjustments(
            slate, projections, contexts
        )

        self.assertEqual(adjusted, projections)
        self.assertEqual(audit, ())

    def test_does_not_penalize_wr3_from_depth_order_alone(self) -> None:
        players = (
            Player("wr1", "Outside One", Position.WR, (Position.WR,), 9000, "SEA", "DEN", "SEA@DEN"),
            Player("wr3", "Slot Starter", Position.WR, (Position.WR,), 5000, "SEA", "DEN", "SEA@DEN"),
        )
        slate = Slate(Platform.DRAFTKINGS, ContestFormat.SINGLE_GAME, players, "test")
        projections = (
            Projection("Outside One", "SEA", 15, platform_id="wr1"),
            Projection("Slot Starter", "SEA", 8, platform_id="wr3", floor=3, ceiling=15),
        )
        contexts = (
            PlayerContext("wr1", 1, None, None, True),
            PlayerContext("wr3", 3, None, None, True),
        )

        adjusted, audit = apply_current_role_adjustments(slate, projections, contexts)

        self.assertEqual(adjusted, projections)
        self.assertEqual(audit, ())

    def test_penalizes_wr4_behind_active_receivers(self) -> None:
        players = (
            Player("wr1", "Starter", Position.WR, (Position.WR,), 9000, "SEA", "DEN", "SEA@DEN"),
            Player("wr4", "Reserve", Position.WR, (Position.WR,), 2000, "SEA", "DEN", "SEA@DEN"),
        )
        slate = Slate(Platform.DRAFTKINGS, ContestFormat.SINGLE_GAME, players, "test")
        projections = (
            Projection("Starter", "SEA", 15, platform_id="wr1"),
            Projection(
                "Reserve", "SEA", 4, platform_id="wr4", floor=0, ceiling=10,
                opportunity_stability=.20,
            ),
        )
        contexts = (
            PlayerContext("wr1", 1, None, None, True),
            PlayerContext("wr4", 4, None, None, True),
        )

        adjusted, audit = apply_current_role_adjustments(slate, projections, contexts)

        self.assertEqual(adjusted[1].projected_points, 3)
        self.assertEqual(audit[0].depth_order, 4)

    def test_confirmed_role_report_overrides_nominal_depth_chart(self) -> None:
        players = (
            Player("rb1", "Nominal starter", Position.RB, (Position.RB,), 7000, "GB", "CHI", "GB@CHI"),
            Player("rb3", "Expected lead", Position.RB, (Position.RB,), 3500, "GB", "CHI", "GB@CHI"),
        )
        slate = Slate(Platform.DRAFTKINGS, ContestFormat.CLASSIC, players, "test")
        projections = (
            Projection("Nominal starter", "GB", 12, platform_id="rb1"),
            Projection(
                "Expected lead", "GB", 8, platform_id="rb3", floor=2,
                ceiling=16, p10=1, p25=3, p75=11, p90=17,
                bust_probability=.40, opportunity_stability=.20,
            ),
        )
        contexts = (
            PlayerContext(
                "rb1", 1, None, None, True,
                expected_role="committee", role_note="will rotate",
            ),
            PlayerContext(
                "rb3", 3, None, None, True,
                expected_role="expanded", role_note="expected lead work",
            ),
        )

        adjusted, audit = apply_current_role_adjustments(slate, projections, contexts)

        by_id = {item.platform_id: item for item in adjusted}
        self.assertAlmostEqual(by_id["rb1"].projected_points, 10.2)
        self.assertAlmostEqual(by_id["rb3"].projected_points, 10.0)
        self.assertEqual(len(audit), 2)
        self.assertTrue(all("pre-lock" in item.reason for item in audit))

    def test_rb3_is_reduced_when_healthy_rb1_returns(self) -> None:
        players = (
            Player(
                "rb1", "Returning starter", Position.RB, (Position.RB,),
                8000, "GB", "CHI", "GB@CHI",
            ),
            Player(
                "rb3", "Temporary contributor", Position.RB, (Position.RB,),
                5000, "GB", "CHI", "GB@CHI",
            ),
        )
        slate = Slate(
            Platform.FANDUEL, ContestFormat.CLASSIC, players, "test"
        )
        projections = (
            Projection("Returning starter", "GB", 17, platform_id="rb1"),
            Projection(
                "Temporary contributor", "GB", 10, platform_id="rb3",
                floor=3, ceiling=20, p10=1, p25=4, p75=14, p90=22,
                bust_probability=.40, opportunity_stability=.90,
            ),
        )
        contexts = (
            PlayerContext("rb1", 1, None, None, True),
            PlayerContext("rb3", 3, None, None, True),
        )

        adjusted, audit = apply_current_role_adjustments(
            slate, projections, contexts
        )

        by_id = {item.platform_id: item for item in adjusted}
        self.assertAlmostEqual(by_id["rb3"].projected_points, 6)
        self.assertAlmostEqual(by_id["rb3"].floor, 1.8)
        self.assertGreater(by_id["rb3"].bust_probability, .40)
        self.assertIn("active RB1", audit[0].reason)

    def test_guardrails_severely_depressed_healthy_starter_projection(self) -> None:
        player = Player(
            "qb1", "Healthy starter", Position.QB, (Position.QB,),
            10400, "WAS", "DAL", "WAS@DAL", platform_average=22.0,
        )
        slate = Slate(
            Platform.DRAFTKINGS, ContestFormat.SINGLE_GAME, (player,), "test"
        )
        projection = Projection(
            "Healthy starter", "WAS", 7.0, platform_id="qb1",
            floor=3.0, ceiling=14.0, p10=2.0, p25=4.0, p75=10.0, p90=15.0,
        )
        contexts = (PlayerContext("qb1", 1, None, None, True),)

        adjusted, audit = apply_current_role_adjustments(
            slate, (projection,), contexts
        )

        self.assertAlmostEqual(adjusted[0].projected_points, 13.2)
        self.assertAlmostEqual(adjusted[0].ceiling, 26.4)
        self.assertEqual(len(audit), 1)
        self.assertIn("starter guardrail", audit[0].reason)

    def test_guardrail_does_not_raise_backup_or_questionable_player(self) -> None:
        players = (
            Player(
                "wr2", "Backup", Position.WR, (Position.WR,),
                3000, "WAS", "DAL", "WAS@DAL", platform_average=10.0,
            ),
            Player(
                "rb1", "Questionable starter", Position.RB, (Position.RB,),
                7000, "DAL", "WAS", "WAS@DAL", platform_average=16.0,
                status="Q",
            ),
        )
        slate = Slate(
            Platform.DRAFTKINGS, ContestFormat.SINGLE_GAME, players, "test"
        )
        projections = (
            Projection("Backup", "WAS", 3.0, platform_id="wr2"),
            Projection("Questionable starter", "DAL", 4.0, platform_id="rb1"),
        )
        contexts = (
            PlayerContext("wr2", 2, None, None, True),
            PlayerContext("rb1", 1, "QUESTIONABLE", None, True),
        )

        adjusted, audit = apply_current_role_adjustments(
            slate, projections, contexts
        )

        self.assertEqual(adjusted, projections)
        self.assertEqual(audit, ())

    def test_guardrail_respects_confirmed_limited_role(self) -> None:
        player = Player(
            "te1", "Limited starter", Position.TE, (Position.TE,),
            5000, "LV", "NE", "LV@NE", platform_average=10.0,
        )
        slate = Slate(Platform.FANDUEL, ContestFormat.CLASSIC, (player,), "test")
        projection = Projection("Limited starter", "LV", 4.0, platform_id="te1")
        contexts = (
            PlayerContext(
                "te1", 1, None, None, True,
                expected_role="limited", role_note="expected snap count",
            ),
        )

        adjusted, audit = apply_current_role_adjustments(
            slate, (projection,), contexts
        )

        self.assertAlmostEqual(adjusted[0].projected_points, 2.4)
        self.assertEqual(len(audit), 1)
        self.assertIn("limited role", audit[0].reason)

    def test_promotes_next_running_back_when_higher_usage_back_is_out(self) -> None:
        players = (
            Player(
                "rb1", "Unavailable lead", Position.RB, (Position.RB,),
                7000, "WAS", "SF", "WAS@SF", platform_average=9.0,
                status="IR",
            ),
            Player(
                "rb2", "Committee replacement", Position.RB, (Position.RB,),
                6600, "WAS", "SF", "WAS@SF", platform_average=8.3,
            ),
            Player(
                "rb3", "Passing-down back", Position.RB, (Position.RB,),
                3600, "WAS", "SF", "WAS@SF", platform_average=3.7,
            ),
        )
        slate = Slate(
            Platform.DRAFTKINGS, ContestFormat.SINGLE_GAME, players, "test"
        )
        projections = (
            Projection(
                "Committee replacement", "WAS", 2.16, platform_id="rb2",
                floor=1.2, ceiling=4.2, p10=1.0, p25=1.2, p75=3.1, p90=4.2,
            ),
            Projection("Passing-down back", "WAS", 3.2, platform_id="rb3"),
        )
        contexts = (
            PlayerContext("rb2", 2, None, "Limited Participation", True),
            PlayerContext("rb3", 3, None, "Limited Participation", True),
        )

        adjusted, audit = apply_current_role_adjustments(
            slate, projections, contexts
        )

        by_id = {item.platform_id: item for item in adjusted}
        self.assertAlmostEqual(by_id["rb2"].projected_points, 2.16 * 1.35)
        self.assertAlmostEqual(by_id["rb2"].ceiling, 4.2 * 1.35)
        self.assertEqual(by_id["rb3"].projected_points, 3.2)
        self.assertEqual(len(audit), 1)
        self.assertIn("unavailable player", audit[0].reason)

    def test_promotes_receiver_when_higher_usage_receiver_is_out(self) -> None:
        players = (
            Player(
                "wr1", "Unavailable receiver", Position.WR, (Position.WR,),
                9000, "SF", "WAS", "WAS@SF", platform_average=15.0,
                status="OUT",
            ),
            Player(
                "wr2", "Promoted receiver", Position.WR, (Position.WR,),
                5400, "SF", "WAS", "WAS@SF", platform_average=8.0,
            ),
        )
        slate = Slate(
            Platform.DRAFTKINGS, ContestFormat.SINGLE_GAME, players, "test"
        )
        projection = Projection(
            "Promoted receiver", "SF", 4.0, platform_id="wr2",
            floor=1.0, ceiling=9.0,
        )
        contexts = (PlayerContext("wr2", 2, None, None, True),)

        adjusted, audit = apply_current_role_adjustments(
            slate, (projection,), contexts
        )

        self.assertAlmostEqual(adjusted[0].projected_points, 5.4)
        self.assertAlmostEqual(adjusted[0].ceiling, 12.15)
        self.assertEqual(len(audit), 1)
        self.assertIn("WR", audit[0].reason)

    def test_promoted_receiver_gets_role_aware_upside_range(self) -> None:
        players = (
            Player(
                "wr1", "Unavailable receiver", Position.WR, (Position.WR,),
                9000, "PHI", "DAL", "DAL@PHI", status="OUT",
                platform_average=15.0,
            ),
            Player(
                "wr2", "Promoted receiver", Position.WR, (Position.WR,),
                5000, "PHI", "DAL", "DAL@PHI", platform_average=9.2,
            ),
        )
        slate = Slate(
            Platform.DRAFTKINGS, ContestFormat.SINGLE_GAME, players, "test"
        )
        projection = Projection(
            "Promoted receiver", "PHI", 9.2, platform_id="wr2",
            floor=4.0, ceiling=9.5, p10=2.5, p25=4.0,
            p75=9.2, p90=9.5,
        )
        contexts = (PlayerContext("wr2", 2, None, None, True),)

        adjusted, _ = apply_current_role_adjustments(
            slate, (projection,), contexts
        )

        self.assertAlmostEqual(adjusted[0].projected_points, 10.12)
        self.assertGreaterEqual(
            adjusted[0].ceiling, adjusted[0].projected_points * 1.8
        )
        self.assertEqual(adjusted[0].p90, adjusted[0].ceiling)

    def test_promotes_first_reserve_even_when_his_platform_average_is_higher(self) -> None:
        players = (
            Player(
                "out", "Unavailable receiver", Position.WR, (Position.WR,),
                7600, "NE", "CHI", "NE@CHI", platform_average=9.7,
                status="IR",
            ),
            Player(
                "wr2", "Established WR2", Position.WR, (Position.WR,),
                6800, "NE", "CHI", "NE@CHI", platform_average=10.1,
            ),
            Player(
                "wr3", "Reserve WR3", Position.WR, (Position.WR,),
                3200, "NE", "CHI", "NE@CHI", platform_average=5.1,
            ),
        )
        slate = Slate(
            Platform.DRAFTKINGS, ContestFormat.SINGLE_GAME, players, "test"
        )
        projections = (
            Projection("Established WR2", "NE", 10, platform_id="wr2"),
            Projection("Reserve WR3", "NE", 5, platform_id="wr3"),
        )
        contexts = (
            PlayerContext("wr2", 2, None, None, True),
            PlayerContext("wr3", 3, None, None, True),
        )

        adjusted, audit = apply_current_role_adjustments(
            slate, projections, contexts
        )

        by_id = {item.platform_id: item for item in adjusted}
        self.assertAlmostEqual(by_id["wr2"].projected_points, 11.11)
        self.assertEqual(by_id["wr3"].projected_points, 5)
        self.assertEqual([item.player for item in audit], ["Established WR2"])

    def test_does_not_guardrail_low_volume_fullback_listed_first(self) -> None:
        player = Player(
            "fb1", "Starting fullback", Position.RB, (Position.RB,),
            1400, "SF", "WAS", "WAS@SF", platform_average=3.9,
        )
        slate = Slate(
            Platform.DRAFTKINGS, ContestFormat.SINGLE_GAME, (player,), "test"
        )
        projection = Projection(
            "Starting fullback", "SF", .94, platform_id="fb1",
            floor=.2, ceiling=3.4,
        )
        contexts = (PlayerContext("fb1", 1, None, None, True),)

        adjusted, audit = apply_current_role_adjustments(
            slate, (projection,), contexts
        )

        self.assertEqual(adjusted, (projection,))
        self.assertEqual(audit, ())


if __name__ == "__main__":
    unittest.main()
