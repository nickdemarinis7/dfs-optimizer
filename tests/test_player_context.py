from __future__ import annotations

import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from dfs_optimizer.models import ContestFormat, Platform, Player, Position, Projection, Slate
from dfs_optimizer.services.player_context import (
    PlayerContext,
    apply_final_status_overrides,
    final_status_csv_template,
    import_final_status_csv,
    import_player_context_csv,
    match_nflverse_player_context,
    match_player_context,
    merge_player_context_sources,
    player_context_csv_template,
    player_context_snapshot,
    summarize_prelock_context,
    verified_player_context_ids,
    unverified_selected_player_ids,
)
from dfs_optimizer.services.risk import (
    suggest_default_excluded_player_ids,
    suggest_max_once_player_ids,
)


class PlayerContextTests(unittest.TestCase):
    def test_imports_manual_cfb_availability_and_depth_chart(self) -> None:
        players = (
            Player(
                "qb1", "Starter One", Position.QB, (Position.QB,),
                9000, "AAA", "BBB", "AAA@BBB",
            ),
            Player(
                "qb2", "Backup Two", Position.QB, (Position.QB,),
                5000, "AAA", "BBB", "AAA@BBB",
            ),
        )
        slate = Slate(
            Platform.DRAFTKINGS, ContestFormat.CLASSIC, players, "test.csv"
        )
        contexts = import_player_context_csv(
            slate,
            b"name,team,status,depth_chart_position,active,practice_participation,verified_projection,expected_role,role_note\n"
            b"Starter One,AAA,QUESTIONABLE,1,true,LIMITED,18.5,expanded,expected full workload\n"
            b"Backup Two,AAA,,2,true,,,,\n",
        )
        summary = summarize_prelock_context(slate, contexts)

        self.assertEqual(len(contexts), 2)
        self.assertIn("qb1", summary.questionable_player_ids)
        self.assertIn("qb2", summary.backup_quarterback_ids)
        self.assertEqual(contexts[0].verified_projection, 18.5)
        self.assertEqual(contexts[0].expected_role, "expanded")
        self.assertEqual(contexts[0].role_note, "expected full workload")

    def test_manual_context_rejects_unmatched_player(self) -> None:
        with self.assertRaisesRegex(ValueError, "did not match"):
            import_player_context_csv(
                self.slate,
                b"name,team,status\nNot A Player,DAL,OUT\n",
            )

    def test_context_template_contains_every_slate_player(self) -> None:
        text = player_context_csv_template(self.slate).decode()

        self.assertIn("name,team,status,depth_chart_position,active", text)
        self.assertIn("Dak Prescott,DAL", text)
        self.assertIn("Depth Receiver,DAL", text)

    def test_final_status_overrides_stale_questionable_status(self) -> None:
        final = import_final_status_csv(
            self.slate,
            b"name,team,final_status\nDak Prescott,DAL,ACTIVE\n"
            b"Depth Receiver,DAL,INACTIVE\n",
        )
        existing = (
            PlayerContext("dak", 1, "QUESTIONABLE", "LIMITED", None),
            PlayerContext("wr", 3, None, None, True, expected_role="expanded"),
        )

        merged = {item.platform_id: item for item in apply_final_status_overrides(existing, final)}
        summary = summarize_prelock_context(self.slate, tuple(merged.values()))

        self.assertEqual(merged["dak"].injury_status, "ACTIVE")
        self.assertTrue(merged["dak"].active)
        self.assertNotIn("dak", summary.questionable_player_ids)
        self.assertFalse(merged["wr"].active)
        self.assertEqual(merged["wr"].expected_role, "expanded")
        self.assertIn("wr", summary.unavailable_player_ids)

    def test_final_status_template_and_context_snapshot_are_auditable(self) -> None:
        template = final_status_csv_template(self.slate).decode()
        snapshot = player_context_snapshot(
            (PlayerContext("1", 1, "ACTIVE", None, True),),
            source="official report",
            checked_at=datetime(2026, 10, 20, tzinfo=timezone.utc),
        ).decode()

        self.assertIn("name,team,final_status", template)
        self.assertIn("Dak Prescott,DAL", template)
        self.assertIn('"source": "official report"', snapshot)
        self.assertIn('"platform_id": "1"', snapshot)

    def test_final_status_rejects_unknown_values(self) -> None:
        with self.assertRaisesRegex(ValueError, "ACTIVE, INACTIVE, OUT"):
            import_final_status_csv(
                self.slate,
                b"name,team,final_status\nDak Prescott,DAL,PROBABLE\n",
            )

    def test_out_qb1_makes_active_qb2_replacement_not_backup(self) -> None:
        players = (
            Player(
                "qb1", "Out starter", Position.QB, (Position.QB,),
                10800, "BAL", "ATL", "BAL@ATL", status="OUT",
            ),
            Player(
                "qb2", "Replacement", Position.QB, (Position.QB,),
                8800, "BAL", "ATL", "BAL@ATL",
            ),
        )
        slate = Slate(
            Platform.DRAFTKINGS, ContestFormat.SINGLE_GAME, players, "test"
        )
        contexts = (
            PlayerContext("qb1", 1, "OUT", None, False),
            PlayerContext("qb2", 2, None, None, True),
        )

        summary = summarize_prelock_context(slate, contexts)

        self.assertIn("qb1", summary.unavailable_player_ids)
        self.assertNotIn("qb2", summary.backup_quarterback_ids)

    def test_active_qb1_keeps_qb2_flagged_as_backup(self) -> None:
        players = (
            Player(
                "qb1", "Starter", Position.QB, (Position.QB,),
                10800, "BAL", "ATL", "BAL@ATL",
            ),
            Player(
                "qb2", "Backup", Position.QB, (Position.QB,),
                5000, "BAL", "ATL", "BAL@ATL",
            ),
        )
        slate = Slate(
            Platform.DRAFTKINGS, ContestFormat.SINGLE_GAME, players, "test"
        )
        contexts = (
            PlayerContext("qb1", 1, None, None, True),
            PlayerContext("qb2", 2, None, None, True),
        )

        summary = summarize_prelock_context(slate, contexts)

        self.assertIn("qb2", summary.backup_quarterback_ids)

    def setUp(self) -> None:
        self.players = (
            Player("dak", "Dak Prescott", Position.QB, (Position.QB,), 15000, "DAL", "TB", "DAL@TB"),
            Player("joe", "Joe Milton III", Position.QB, (Position.QB,), 6000, "DAL", "TB", "DAL@TB"),
            Player("wr", "Depth Receiver", Position.WR, (Position.WR, Position.FLEX), 7000, "DAL", "TB", "DAL@TB"),
            Player("te", "Backup Tight End", Position.TE, (Position.TE, Position.FLEX), 5000, "DAL", "TB", "DAL@TB"),
        )
        self.slate = Slate(Platform.FANDUEL, ContestFormat.SINGLE_GAME, self.players, "test.csv")
        self.projections = (
            Projection("Dak Prescott", "DAL", 20, platform_id="dak"),
            Projection("Joe Milton III", "DAL", 8, platform_id="joe"),
            Projection("Depth Receiver", "DAL", 8, platform_id="wr", floor=2),
            Projection("Backup Tight End", "DAL", 7, platform_id="te", floor=2),
        )

    def test_matches_current_depth_and_injury_context(self) -> None:
        contexts = match_player_context(self.slate, {
            "1": {"full_name": "Dak Prescott", "team": "DAL", "depth_chart_position": 1, "active": True},
            "2": {"full_name": "Joe Milton", "team": "DAL", "depth_chart_position": "3", "active": True},
            "3": {"full_name": "Depth Receiver", "team": "DAL", "depth_chart_position": 4, "injury_status": "Questionable", "active": True},
        })

        by_id = {item.platform_id: item for item in contexts}
        self.assertEqual(by_id["joe"].depth_chart_position, 3)
        self.assertEqual(by_id["wr"].injury_status, "Questionable")

    def test_matches_latest_nflverse_depth_and_injury_records(self) -> None:
        with TemporaryDirectory() as directory:
            depth_path = Path(directory) / "depth.csv"
            injury_path = Path(directory) / "injuries.csv"
            depth_path.write_text(
                "dt,team,player_name,pos_rank\n"
                "2026-10-01,DAL,Dak Prescott,2\n"
                "2026-10-18,DAL,Dak Prescott,1\n"
                "2026-10-18,DAL,Joe Milton III,3\n",
                encoding="utf-8",
            )
            injury_path.write_text(
                "team,week,full_name,date_modified,report_status,practice_status\n"
                "DAL,6,Dak Prescott,2026-10-10,Questionable,Limited Participation\n"
                "DAL,7,Dak Prescott,2026-10-18,,Full Participation\n",
                encoding="utf-8",
            )

            contexts = match_nflverse_player_context(
                self.slate, depth_path, injury_path
            )

        by_id = {item.platform_id: item for item in contexts}
        self.assertEqual(by_id["dak"].depth_chart_position, 1)
        self.assertIsNone(by_id["dak"].injury_status)
        self.assertEqual(
            by_id["dak"].practice_participation, "Full Participation"
        )
        self.assertEqual(by_id["joe"].depth_chart_position, 3)

    def test_nflverse_merge_preserves_manual_role_report(self) -> None:
        primary = (
            PlayerContext(
                "dak", 2, "Questionable", None, True, 21.0,
                "expanded", "late workload report",
            ),
        )
        secondary = (
            PlayerContext(
                "dak", 1, None, "Full Participation", None,
                injury_reported=True,
            ),
        )

        merged = merge_player_context_sources(primary, secondary)

        self.assertEqual(merged[0].depth_chart_position, 1)
        self.assertIsNone(merged[0].injury_status)
        self.assertEqual(merged[0].practice_participation, "Full Participation")
        self.assertTrue(merged[0].active)
        self.assertEqual(merged[0].verified_projection, 21.0)
        self.assertEqual(merged[0].expected_role, "expanded")
        self.assertEqual(merged[0].role_note, "late workload report")

    def test_uses_sleeper_depth_chart_order_instead_of_position_label(self) -> None:
        contexts = match_player_context(self.slate, {
            "4": {
                "full_name": "Backup Tight End",
                "team": "DAL",
                "depth_chart_position": "TE",
                "depth_chart_order": 2,
                "active": True,
            },
        })

        self.assertEqual(contexts[0].depth_chart_position, 2)

    def test_context_excludes_backup_qb_and_limits_deep_skill_player(self) -> None:
        contexts = match_player_context(self.slate, {
            "1": {"full_name": "Dak Prescott", "team": "DAL", "depth_chart_position": 1, "active": True},
            "2": {"full_name": "Joe Milton III", "team": "DAL", "depth_chart_position": 3, "active": True},
            "3": {"full_name": "Depth Receiver", "team": "DAL", "depth_chart_position": 4, "active": True},
            "4": {"full_name": "Backup Tight End", "team": "DAL", "depth_chart_position": 2, "active": True},
        })

        excluded = suggest_default_excluded_player_ids(
            self.slate, self.projections, contexts
        )
        limited = suggest_max_once_player_ids(
            self.slate, self.projections, contexts
        )

        self.assertIn("joe", excluded)
        self.assertIn("wr", limited)
        self.assertIn("te", limited)
        self.assertNotIn("dak", excluded)

    def test_prelock_summary_identifies_role_and_start_time_risks(self) -> None:
        timed_players = tuple(
            Player(
                player.platform_id,
                player.name,
                player.primary_position,
                player.roster_positions,
                player.salary,
                player.team,
                player.opponent,
                "DAL@TB 10/09/2026 08:00PM ET",
                status=player.status,
            )
            for player in self.players
        )
        slate = Slate(
            Platform.FANDUEL,
            ContestFormat.SINGLE_GAME,
            timed_players,
            "test.csv",
        )
        contexts = match_player_context(slate, {
            "1": {
                "full_name": "Dak Prescott", "team": "DAL",
                "depth_chart_position": 1, "active": True,
                "injury_status": "Questionable",
            },
            "2": {
                "full_name": "Joe Milton III", "team": "DAL",
                "depth_chart_position": 3, "active": True,
            },
            "4": {
                "full_name": "Backup Tight End", "team": "DAL",
                "depth_chart_position": 2, "active": True,
            },
        })

        summary = summarize_prelock_context(
            slate,
            contexts,
            now=datetime(2026, 10, 9, 22, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(summary.questionable_player_ids, frozenset({"dak"}))
        self.assertEqual(summary.backup_quarterback_ids, frozenset({"joe"}))
        self.assertEqual(summary.subordinate_skill_player_ids, frozenset({"te"}))
        self.assertEqual(summary.unmatched_player_ids, frozenset({"wr"}))
        self.assertEqual(len(summary.games_starting_soon), 1)
        self.assertEqual(summary.timed_games, 1)

    def test_blank_context_row_does_not_count_as_verified(self) -> None:
        contexts = (
            PlayerContext("blank", None, None, None, None),
            PlayerContext("active", None, None, None, True),
            PlayerContext("depth", 1, None, None, None),
            PlayerContext("status", None, "QUESTIONABLE", None, None),
            PlayerContext("manual", None, None, None, None, 12.5),
        )

        verified = verified_player_context_ids(contexts)

        self.assertNotIn("blank", verified)
        self.assertEqual(
            verified, frozenset({"active", "depth", "status", "manual"})
        )

    def test_selected_players_require_context_or_individual_acknowledgement(self) -> None:
        contexts = (
            PlayerContext("verified", 1, None, None, True),
            PlayerContext("blank", None, None, None, None),
        )

        unresolved = unverified_selected_player_ids(
            {"verified", "blank", "checked", "missing"},
            contexts,
            {"checked"},
        )

        self.assertEqual(unresolved, frozenset({"blank", "missing"}))


if __name__ == "__main__":
    unittest.main()
