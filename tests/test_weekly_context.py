from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest

from dfs_optimizer.models import ContestFormat, Platform, Player, Position, Slate
from dfs_optimizer.services.weekly_context import (
    apply_coach_signals_to_player_context,
    append_weekly_snapshot_history,
    build_weekly_context,
    import_coach_signals,
    load_practice_trajectories,
    weekly_context_snapshot,
)
from dfs_optimizer.services.player_context import PlayerContext


class WeeklyContextTests(unittest.TestCase):
    def setUp(self) -> None:
        self.slate = Slate(
            Platform.DRAFTKINGS,
            ContestFormat.CLASSIC,
            (
                Player("a", "Away QB", Position.QB, (Position.QB,), 6000, "SEA", "MIA", "SEA@MIA"),
                Player("b", "Home WR", Position.WR, (Position.WR,), 6000, "MIA", "SEA", "SEA@MIA"),
            ),
            "salaries.csv",
        )

    def test_builds_rest_travel_weather_and_defensive_injury_context(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "games.csv").write_text(
                "season,week,away_team,home_team,away_rest,home_rest,roof,temp,wind\n"
                "2026,8,SEA,MIA,4,14,outdoors,84,18\n"
            )
            (root / "injuries_2026.csv").write_text(
                "season,week,team,position,full_name,report_status,practice_status\n"
                "2026,8,SEA,WR,Wide Receiver,Questionable,Limited Participation in Practice\n"
                "2026,8,MIA,CB,Top Corner,Out,Did Not Participate In Practice\n"
            )

            contexts = build_weekly_context(self.slate, 2026, 8, root)
            away = next(item for item in contexts if item.team == "SEA")

            self.assertTrue(away.short_week)
            self.assertGreater(away.travel_miles, 2000)
            self.assertEqual(away.wind_mph, 18)
            self.assertEqual(dict(away.practice_counts)["LP"], 1)
            self.assertEqual(away.defensive_absences, ("Top Corner",))
            self.assertTrue(any("Wind watch" in note for note in away.notes))
            self.assertEqual(away.home_team, "MIA")

    def test_snapshot_history_deduplicates_unchanged_facts(self) -> None:
        snapshot_one = weekly_context_snapshot(
            (), season=2026, week=8,
            checked_at=datetime(2026, 10, 20, tzinfo=timezone.utc),
        )
        snapshot_two = weekly_context_snapshot(
            (), season=2026, week=8,
            checked_at=datetime(2026, 10, 20, 4, tzinfo=timezone.utc),
        )
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "history.jsonl"
            self.assertTrue(append_weekly_snapshot_history(path, snapshot_one))
            self.assertFalse(append_weekly_snapshot_history(path, snapshot_two))
            self.assertEqual(len(path.read_text().splitlines()), 1)

            next_day = weekly_context_snapshot(
                (), season=2026, week=8,
                checked_at=datetime(2026, 10, 21, tzinfo=timezone.utc),
            )
            self.assertTrue(append_weekly_snapshot_history(path, next_day))
            self.assertEqual(len(path.read_text().splitlines()), 2)

    def test_imports_attributed_coach_signal(self) -> None:
        signals = import_coach_signals(
            b"player,team,signal,confidence,speaker,published_at,source_url,note\n"
            b"Player One,SEA,expanded,high,Head Coach,2026-10-27,https://example.com,More routes\n"
        )
        self.assertEqual(signals[0].signal, "expanded")
        self.assertEqual(signals[0].speaker, "Head Coach")

        payload = json.loads(weekly_context_snapshot(
            (), season=2026, week=8, coach_signals=signals
        ))
        self.assertEqual(payload["coach_signals"][0]["player"], "Player One")

    def test_loads_player_practice_movement(self) -> None:
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "history.jsonl"
            base = {
                "schema_version": 1, "season": 2026, "week": 8,
                "teams": [], "coach_signals": [],
                "player_observations": [{
                    "platform_id": "a", "name": "Away QB", "team": "SEA",
                    "injury_status": "QUESTIONABLE", "active": True,
                    "depth_chart_position": 1, "expected_role": None, "role_note": None,
                }],
            }
            first = dict(base, checked_at_utc="2026-10-20T12:00:00+00:00")
            first["player_observations"] = [dict(base["player_observations"][0], practice_participation="Did Not Participate In Practice")]
            second = dict(base, checked_at_utc="2026-10-21T12:00:00+00:00")
            second["player_observations"] = [dict(base["player_observations"][0], practice_participation="Full Participation in Practice")]
            path.write_text(json.dumps(first) + "\n" + json.dumps(second) + "\n")

            trajectory = load_practice_trajectories(path)[0]

            self.assertEqual(trajectory.observations, ("Tue DNP", "Wed FP"))
            self.assertTrue(trajectory.improving)

    def test_confirmed_coach_signal_updates_optimizer_role_context(self) -> None:
        signals = import_coach_signals(
            b"player,team,signal,confidence,speaker,published_at,source_url,note\n"
            b"Away QB,SEA,limited,high,Head Coach,2026-10-27,https://example.com,Snap count\n"
        )
        contexts = apply_coach_signals_to_player_context(
            self.slate,
            (PlayerContext("a", 1, None, "FP", True),),
            signals,
        )

        self.assertEqual(contexts[0].expected_role, "limited")
        self.assertIn("Head Coach", contexts[0].role_note)
        self.assertIn("https://example.com", contexts[0].role_note)


if __name__ == "__main__":
    unittest.main()
