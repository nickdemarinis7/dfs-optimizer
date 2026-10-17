from __future__ import annotations

import csv
import io
import unittest
from types import SimpleNamespace

from dfs_optimizer.models import ContestFormat, Platform
from dfs_optimizer.optimization import generate_classic_lineups
from dfs_optimizer.services import (
    CapturedSubmission,
    SavedPortfolio,
    classify_submitted_entry_provenance,
    extract_submitted_entries,
    review_contest_results,
)
from test_classic_optimizer import make_slate


class ResultsReviewTests(unittest.TestCase):
    def test_matches_generated_classic_lineup(self) -> None:
        slate, matches = make_slate(Platform.DRAFTKINGS)
        lineups = generate_classic_lineups(slate, matches, 1)
        lineup_text = "  ".join(
            f"{entry.slot.rstrip('123')} {entry.player.name}"
            for entry in lineups[0].entries
        )
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(("Rank", "EntryId", "EntryName", "Points", "Lineup"))
        writer.writerow((2, "entry-1", "nick_demarinis", 150.5, lineup_text))
        writer.writerow((1, "entry-2", "winner", 220, "QB Other Player"))

        review = review_contest_results(
            output.getvalue().encode(),
            "results.csv",
            lineups,
            slate.platform,
            slate.contest_format,
            "nick_demarinis",
        )

        self.assertEqual(review.field_size, 2)
        self.assertEqual(review.winning_score, 220)
        self.assertEqual(review.lineups[0].score, 150.5)
        self.assertEqual(review.lineups[0].rank, 2)
        self.assertFalse(review.unmatched_lineups)

    def test_rejects_non_results_csv(self) -> None:
        slate, matches = make_slate(Platform.FANDUEL)
        lineups = generate_classic_lineups(slate, matches, 1)
        with self.assertRaisesRegex(ValueError, "missing columns"):
            review_contest_results(
                b"name,score\nA,10\n",
                "wrong.csv",
                lineups,
                slate.platform,
                slate.contest_format,
            )

    def test_draftkings_cfb_classic_recognizes_super_flex(self) -> None:
        names = (
            "Quarterback One", "Runner One", "Runner Two", "Receiver One",
            "Receiver Two", "Receiver Three", "Flex Player", "Super Quarterback",
        )
        lineup = SimpleNamespace(entries=tuple(
            SimpleNamespace(player=SimpleNamespace(name=name)) for name in names
        ))
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(("Rank", "EntryId", "EntryName", "Points", "Lineup"))
        writer.writerow((
            1, "mine", "nick_demarinis", 200,
            "QB Quarterback One RB Runner One RB Runner Two "
            "WR Receiver One WR Receiver Two WR Receiver Three "
            "FLEX Flex Player S-FLEX Super Quarterback",
        ))

        review = review_contest_results(
            output.getvalue().encode(), "results.csv", (lineup,),
            Platform.DRAFTKINGS, ContestFormat.CLASSIC,
        )

        self.assertEqual(review.lineups[0].score, 200)
        self.assertFalse(review.unmatched_lineups)

    def test_fanduel_single_game_preserves_mvp_role_and_finds_actual_entries(self) -> None:
        names = ("Alpha One", "Bravo Two", "Charlie Three", "Delta Four", "Echo Five", "Foxtrot Six")
        lineup = SimpleNamespace(entries=tuple(
            SimpleNamespace(player=SimpleNamespace(name=name)) for name in names
        ))
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(("Rank", "EntryId", "EntryName", "Points", "Lineup"))
        writer.writerow((
            1, "winner", "other", 100,
            ", ".join(f"WR {name} ({index})" for index, name in enumerate(names[1:] + names[:1])),
        ))
        writer.writerow((
            2, "mine", "nick_demarinis", 90,
            ", ".join(f"WR {name} ({index})" for index, name in enumerate(names)),
        ))
        content = output.getvalue().encode()

        review = review_contest_results(
            content, "results.csv", (lineup,), Platform.FANDUEL,
            ContestFormat.SINGLE_GAME, "nick_demarinis",
        )
        submitted = extract_submitted_entries(
            content, "results.csv", Platform.FANDUEL,
            ContestFormat.SINGLE_GAME, "nick_demarinis",
        )

        self.assertEqual(review.lineups[0].rank, 2)
        self.assertEqual(submitted[0].lineup[0], ("MVP", "Alpha One"))
        self.assertEqual(submitted[0].duplication, 1)

    def test_labels_current_older_and_unverified_submitted_entries(self) -> None:
        def lineup(*names):
            return SimpleNamespace(entries=tuple(
                SimpleNamespace(player=SimpleNamespace(name=name)) for name in names
            ))

        current = lineup("Alpha", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot")
        older = lineup("Golf", "Hotel", "India", "Juliet", "Kilo", "Lima")
        submitted = (
            SimpleNamespace(
                rank=1, score=100, entry_name="mine", duplication=1,
                lineup=(("MVP", "Alpha"), *(
                    ("FLEX", name) for name in sorted(("Bravo", "Charlie", "Delta", "Echo", "Foxtrot"))
                )),
            ),
            SimpleNamespace(
                rank=2, score=90, entry_name="mine", duplication=1,
                lineup=(("MVP", "Golf"), *(
                    ("FLEX", name) for name in sorted(("Hotel", "India", "Juliet", "Kilo", "Lima"))
                )),
            ),
            SimpleNamespace(
                rank=3, score=80, entry_name="mine", duplication=1,
                lineup=(("MVP", "Other"), *(
                    ("FLEX", name) for name in ("P1", "P2", "P3", "P4", "P5")
                )),
            ),
        )

        result = classify_submitted_entry_provenance(
            submitted,
            (
                SavedPortfolio("current", "Final", (current,), True),
                SavedPortfolio("older", "Wednesday", (older,)),
            ),
            Platform.FANDUEL,
            ContestFormat.SINGLE_GAME,
        )

        self.assertEqual([item.source for item in result], [
            "Current run", "Earlier saved run", "Unverified",
        ])
        self.assertEqual(result[0].lineup_number, 1)
        self.assertIsNone(result[2].run_id)

    def test_current_run_takes_priority_when_lineup_exists_in_two_runs(self) -> None:
        names = ("Alpha", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot")
        lineup = SimpleNamespace(entries=tuple(
            SimpleNamespace(player=SimpleNamespace(name=name)) for name in names
        ))
        submitted = SimpleNamespace(
            lineup=(("MVP", names[0]), *(
                ("FLEX", name) for name in sorted(names[1:])
            )),
        )

        result = classify_submitted_entry_provenance(
            (submitted,),
            (
                SavedPortfolio("current", "Final", (lineup,), True),
                SavedPortfolio("older", "Earlier", (lineup,)),
            ),
            Platform.FANDUEL,
            ContestFormat.SINGLE_GAME,
        )

        self.assertEqual(result[0].run_id, "current")

    def test_labels_captured_manual_submission_without_counting_it_as_current(self) -> None:
        submitted = SimpleNamespace(
            lineup=(("MVP", "Alpha"), *(
                ("FLEX", name) for name in ("Bravo", "Charlie", "Delta", "Echo", "Foxtrot")
            )),
        )
        roster = SimpleNamespace(
            lineup_number=2,
            players=(
                ("MVP", "1", "Alpha"),
                ("FLEX", "2", "Bravo"),
                ("FLEX", "3", "Charlie"),
                ("FLEX", "4", "Delta"),
                ("FLEX", "5", "Echo"),
                ("FLEX", "6", "Foxtrot"),
            ),
        )

        result = classify_submitted_entry_provenance(
            (submitted,),
            (),
            Platform.FANDUEL,
            ContestFormat.SINGLE_GAME,
            (CapturedSubmission("run-1", "Final submission", (roster,)),),
        )

        self.assertEqual(result[0].source, "Captured submission change")
        self.assertTrue(result[0].verified)
        self.assertFalse(result[0].current_run)
        self.assertEqual(result[0].lineup_number, 2)

    def test_classifies_classic_lineup_with_display_roles_removed(self) -> None:
        names = (
            "QB One", "RB One", "RB Two", "WR One", "WR Two",
            "WR Three", "TE One", "Flex One", "Defense One",
        )
        lineup = SimpleNamespace(entries=tuple(
            SimpleNamespace(player=SimpleNamespace(name=name)) for name in names
        ))
        submitted = SimpleNamespace(
            lineup=tuple(("", name) for name in sorted(names)),
        )

        result = classify_submitted_entry_provenance(
            (submitted,),
            (SavedPortfolio("classic", "Classic run", (lineup,), True),),
            Platform.DRAFTKINGS,
            ContestFormat.CLASSIC,
        )

        self.assertEqual(result[0].source, "Current run")


if __name__ == "__main__":
    unittest.main()
