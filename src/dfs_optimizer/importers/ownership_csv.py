from __future__ import annotations

import csv
from dataclasses import replace
from pathlib import Path

from dfs_optimizer.models import Projection, Slate

from .projections_csv import ProjectionImportError, match_projections


def apply_ownership_csv(
    slate: Slate,
    projections: tuple[Projection, ...],
    path: str | Path,
) -> tuple[tuple[Projection, ...], int]:
    """Merge name/team ownership percentages into an existing projection set."""
    source = Path(path)
    with source.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"name", "team", "projected_ownership"}
        missing = required - set(reader.fieldnames or ())
        if missing:
            raise ProjectionImportError(
                "ownership file is missing required columns: " + ", ".join(sorted(missing))
            )
        ownership = []
        for row_number, row in enumerate(reader, 2):
            try:
                ownership.append(Projection(
                    name=row["name"].strip(),
                    team=row["team"].strip().upper(),
                    projected_points=0,
                    platform_id=(row.get("platform_id") or "").strip() or None,
                    projected_ownership=float(row["projected_ownership"]),
                ))
            except (TypeError, ValueError) as exc:
                raise ProjectionImportError(
                    f"invalid ownership row {row_number} in {source.name}: {exc}"
                ) from exc
    matches = match_projections(slate, tuple(ownership))
    by_id = {
        player_id: item.projected_ownership
        for player_id, item in matches.by_player_id.items()
    }
    projection_ids = {
        item: player_id
        for player_id, item in match_projections(slate, projections).by_player_id.items()
    }
    return tuple(
        replace(item, projected_ownership=by_id.get(projection_ids.get(item, "")))
        for item in projections
    ), len(by_id)
