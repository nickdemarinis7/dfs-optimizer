from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from dfs_optimizer.models import ProjectedKickerStats, ProjectedOffensiveStats


REQUIRED_STAT_COLUMNS = frozenset({"name", "team"})
STAT_COLUMNS = (
    "passing_yards",
    "passing_touchdowns",
    "interceptions_thrown",
    "rushing_yards",
    "rushing_touchdowns",
    "receptions",
    "receiving_yards",
    "receiving_touchdowns",
    "return_touchdowns",
    "fumbles_lost",
    "two_point_conversions",
    "offensive_fumble_recovery_touchdowns",
    "passing_bonus_probability",
    "rushing_bonus_probability",
    "receiving_bonus_probability",
)


class StatProjectionImportError(ValueError):
    """Raised when an expected-stat projection file is invalid."""


@dataclass(frozen=True, slots=True)
class PlayerStatProjection:
    name: str
    team: str
    stats: ProjectedOffensiveStats | ProjectedKickerStats


def import_stat_projections_csv(path: str | Path) -> tuple[PlayerStatProjection, ...]:
    source = Path(path)
    try:
        with source.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            headers = set(reader.fieldnames or ())
            missing = REQUIRED_STAT_COLUMNS - headers
            if missing:
                raise StatProjectionImportError(
                    "stat projection file is missing required columns: "
                    + ", ".join(sorted(missing))
                )
            rows = list(reader)
    except OSError as exc:
        raise StatProjectionImportError(f"could not read {source}: {exc}") from exc

    results: list[PlayerStatProjection] = []
    seen: set[tuple[str, str]] = set()
    for row_number, row in enumerate(rows, start=2):
        try:
            name = row["name"].strip()
            team = row["team"].strip().upper()
            if not name or not team:
                raise ValueError("name and team cannot be empty")
            values = {column: _number(row.get(column)) for column in STAT_COLUMNS}
            item = PlayerStatProjection(
                name=name,
                team=team,
                stats=ProjectedOffensiveStats(**values),
            )
        except (TypeError, ValueError) as exc:
            raise StatProjectionImportError(
                f"invalid stat projection row {row_number} in {source.name}: {exc}"
            ) from exc
        key = (name.casefold(), team)
        if key in seen:
            raise StatProjectionImportError(f"duplicate stat projection for {name} ({team})")
        seen.add(key)
        results.append(item)
    if not results:
        raise StatProjectionImportError(f"stat projection file is empty: {source}")
    return tuple(results)


def _number(value: str | None) -> float:
    return float(value) if value and value.strip() else 0.0
