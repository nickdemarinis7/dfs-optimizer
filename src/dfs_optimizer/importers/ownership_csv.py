from __future__ import annotations

import csv
import re
from dataclasses import replace
from pathlib import Path

from dfs_optimizer.models import Projection, Slate

from .projections_csv import ProjectionImportError, match_projections


_COLUMN_ALIASES = {
    "name": {"name", "player", "playername", "nickname"},
    "team": {"team", "tm", "teamabbrev", "teamabbr"},
    "projected_ownership": {
        "projectedownership", "projectedown", "ownership", "own", "ownpct",
        "projectedownershippct", "projectedownershippercentage", "pown",
    },
    "platform_id": {"platformid", "id", "playerid"},
}


def _normalized_header(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.casefold())


def _resolve_columns(fieldnames: list[str]) -> dict[str, str]:
    normalized = {_normalized_header(value): value for value in fieldnames if value}
    resolved = {
        canonical: next(
            (normalized[alias] for alias in aliases if alias in normalized), None
        )
        for canonical, aliases in _COLUMN_ALIASES.items()
    }
    missing = {
        name for name in ("name", "team", "projected_ownership")
        if resolved[name] is None
    }
    if missing:
        raise ProjectionImportError(
            "ownership file is missing required columns: " + ", ".join(sorted(missing))
        )
    return resolved


def apply_ownership_csv(
    slate: Slate,
    projections: tuple[Projection, ...],
    path: str | Path,
) -> tuple[tuple[Projection, ...], int]:
    """Merge name/team ownership percentages into an existing projection set."""
    source = Path(path)
    with source.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        columns = _resolve_columns(reader.fieldnames or [])
        ownership = []
        for row_number, row in enumerate(reader, 2):
            try:
                raw_ownership = row[columns["projected_ownership"]].strip().rstrip("%")
                ownership.append(Projection(
                    name=row[columns["name"]].strip(),
                    team=row[columns["team"]].strip().upper(),
                    projected_points=0,
                    platform_id=(
                        row.get(columns["platform_id"] or "", "").strip() or None
                    ),
                    projected_ownership=float(raw_ownership),
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
