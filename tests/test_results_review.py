from __future__ import annotations

import csv
import io
import unittest

from dfs_optimizer.models import Platform
from dfs_optimizer.optimization import generate_classic_lineups
from dfs_optimizer.services import review_contest_results
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


if __name__ == "__main__":
    unittest.main()
