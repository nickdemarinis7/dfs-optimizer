from __future__ import annotations

import csv
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from dfs_optimizer.models import Player, Projection, Slate


REQUIRED_COLUMNS = frozenset({"name", "team", "projected_points"})
OPTIONAL_COLUMNS = frozenset(
    {
        "platform_id", "floor", "ceiling", "projected_ownership",
        "p10", "p25", "p75", "p90", "bust_probability",
    }
)


class ProjectionImportError(ValueError):
    """Raised when projections cannot be parsed or matched safely."""


@dataclass(frozen=True, slots=True)
class ProjectionMatchResult:
    by_player_id: dict[str, Projection]
    unmatched_projections: tuple[Projection, ...]
    players_without_projections: tuple[Player, ...]


def import_projections_csv(path: str | Path) -> tuple[Projection, ...]:
    source = Path(path)
    try:
        with source.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            headers = set(reader.fieldnames or ())
            missing = REQUIRED_COLUMNS - headers
            if missing:
                raise ProjectionImportError(
                    "projection file is missing required columns: " + ", ".join(sorted(missing))
                )
            rows = list(reader)
    except OSError as exc:
        raise ProjectionImportError(f"could not read {source}: {exc}") from exc

    projections: list[Projection] = []
    seen_keys: set[tuple[str, str]] = set()
    for row_number, row in enumerate(rows, start=2):
        try:
            projection = Projection(
                name=row["name"].strip(),
                team=row["team"].strip().upper(),
                projected_points=float(row["projected_points"]),
                platform_id=_optional_text(row.get("platform_id")),
                floor=_optional_float(row.get("floor")),
                ceiling=_optional_float(row.get("ceiling")),
                projected_ownership=_optional_float(row.get("projected_ownership")),
                p10=_optional_float(row.get("p10")),
                p25=_optional_float(row.get("p25")),
                p75=_optional_float(row.get("p75")),
                p90=_optional_float(row.get("p90")),
                bust_probability=_optional_float(row.get("bust_probability")),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ProjectionImportError(
                f"invalid projection row {row_number} in {source.name}: {exc}"
            ) from exc
        key = (_normalize_name(projection.name), projection.team)
        if key in seen_keys:
            raise ProjectionImportError(
                f"duplicate projection for {projection.name} ({projection.team})"
            )
        seen_keys.add(key)
        projections.append(projection)
    if not projections:
        raise ProjectionImportError(f"projection file is empty: {source}")
    return tuple(projections)


def match_projections(slate: Slate, projections: tuple[Projection, ...]) -> ProjectionMatchResult:
    players_by_id = {player.platform_id: player for player in slate.players}
    players_by_name_team: dict[tuple[str, str], list[Player]] = {}
    for player in slate.players:
        key = (_normalize_name(player.name), player.team)
        players_by_name_team.setdefault(key, []).append(player)

    matches: dict[str, Projection] = {}
    unmatched: list[Projection] = []
    for projection in projections:
        player = players_by_id.get(projection.platform_id or "")
        if player is None:
            candidates = players_by_name_team.get(
                (_normalize_name(projection.name), projection.team), []
            )
            if len(candidates) == 1:
                player = candidates[0]
        if player is None or player.platform_id in matches:
            unmatched.append(projection)
        else:
            matches[player.platform_id] = projection

    missing = tuple(
        player for player in slate.players if player.platform_id not in matches
    )
    return ProjectionMatchResult(
        by_player_id=matches,
        unmatched_projections=tuple(unmatched),
        players_without_projections=missing,
    )


def _normalize_name(value: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", ascii_name.lower())


def _optional_text(value: str | None) -> str | None:
    return value.strip() or None if value is not None else None


def _optional_float(value: str | None) -> float | None:
    return float(value) if value and value.strip() else None
