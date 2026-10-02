from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from dfs_optimizer.models import ProjectedDefenseStats


DEFENSE_COLUMNS = (
    "sacks",
    "interceptions",
    "fumble_recoveries",
    "return_touchdowns",
    "safeties",
    "blocked_kicks",
    "extra_point_returns",
    "probability_allow_0",
    "probability_allow_1_to_6",
    "probability_allow_7_to_13",
    "probability_allow_14_to_20",
    "probability_allow_21_to_27",
    "probability_allow_28_to_34",
    "probability_allow_35_plus",
)


class DefenseProjectionImportError(ValueError):
    """Raised when a projected defense CSV is invalid."""


@dataclass(frozen=True, slots=True)
class TeamDefenseProjection:
    team: str
    stats: ProjectedDefenseStats


def import_defense_projections_csv(
    path: str | Path,
) -> tuple[TeamDefenseProjection, ...]:
    source = Path(path)
    try:
        with source.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            headers = set(reader.fieldnames or ())
            required = {"team", *DEFENSE_COLUMNS}
            missing = required - headers
            if missing:
                raise DefenseProjectionImportError(
                    "defense projection file is missing required columns: "
                    + ", ".join(sorted(missing))
                )
            rows = list(reader)
    except OSError as exc:
        raise DefenseProjectionImportError(f"could not read {source}: {exc}") from exc

    results: list[TeamDefenseProjection] = []
    seen: set[str] = set()
    for row_number, row in enumerate(rows, start=2):
        try:
            team = row["team"].strip().upper()
            if not team:
                raise ValueError("team cannot be empty")
            if team in seen:
                raise ValueError(f"duplicate defense projection for {team}")
            stats = ProjectedDefenseStats(
                **{column: float(row[column]) for column in DEFENSE_COLUMNS}
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise DefenseProjectionImportError(
                f"invalid defense projection row {row_number} in {source.name}: {exc}"
            ) from exc
        seen.add(team)
        results.append(TeamDefenseProjection(team=team, stats=stats))
    if not results:
        raise DefenseProjectionImportError(f"defense projection file is empty: {source}")
    return tuple(results)

