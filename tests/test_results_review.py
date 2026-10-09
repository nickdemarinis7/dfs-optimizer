from __future__ import annotations

import csv
import io
import unittest
from types import SimpleNamespace

from dfs_optimizer.models import ContestFormat, Platform
from dfs_optimizer.optimization import generate_classic_lineups
from dfs_optimizer.services import extract_submitted_entries, review_contest_results
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


if __name__ == "__main__":
    unittest.main()
