from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from dfs_optimizer.importers import (
    ProjectionImportError,
    apply_ownership_csv,
    import_projections_csv,
    import_salary_csv,
    match_projections,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class ProjectionImporterTests(unittest.TestCase):
    def test_imports_and_matches_platform_neutral_projections(self) -> None:
        slate = import_salary_csv(PROJECT_ROOT / "samples" / "DKSalaries.csv")
        projections = import_projections_csv(PROJECT_ROOT / "examples" / "projections.csv")
        result = match_projections(slate, projections)

        self.assertEqual(len(projections), 2)
        self.assertEqual(len(result.by_player_id), 2)
        self.assertEqual(result.unmatched_projections, ())
        self.assertEqual(len(result.players_without_projections), 627)

    def test_rejects_missing_required_column(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.csv"
            path.write_text("name,team\nPlayer,ABC\n", encoding="utf-8")
            with self.assertRaisesRegex(ProjectionImportError, "projected_points"):
                import_projections_csv(path)

    def test_rejects_duplicate_player(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "duplicate.csv"
            path.write_text(
                "name,team,projected_points\nA Player,ABC,10\nA Player,ABC,11\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ProjectionImportError, "duplicate"):
                import_projections_csv(path)

    def test_merges_projected_ownership_without_replacing_points(self) -> None:
        slate = import_salary_csv(PROJECT_ROOT / "samples" / "DKSalaries.csv")
        projections = import_projections_csv(PROJECT_ROOT / "examples" / "projections.csv")

        merged, matched = apply_ownership_csv(
            slate, projections, PROJECT_ROOT / "examples" / "ownership.csv"
        )

        self.assertEqual(matched, 2)
        self.assertEqual(
            [item.projected_points for item in merged],
            [item.projected_points for item in projections],
        )
        self.assertEqual([item.projected_ownership for item in merged], [12.5, 18.2])


if __name__ == "__main__":
    unittest.main()
