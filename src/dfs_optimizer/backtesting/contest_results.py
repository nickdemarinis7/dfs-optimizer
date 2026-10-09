from __future__ import annotations

import csv
import io
import re
import zipfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class FieldEntry:
    entry_id: str
    rank: int
    entry_name: str
    points: float | None
    lineup: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PlayerResult:
    name: str
    position: str
    drafted_percent: float
    fantasy_points: float


@dataclass(frozen=True, slots=True)
class ContestResults:
    entries: tuple[FieldEntry, ...]
    players: tuple[PlayerResult, ...]

    @property
    def scored_entries(self) -> tuple[FieldEntry, ...]:
        return tuple(entry for entry in self.entries if entry.points is not None)

    @property
    def duplicated_lineups(self) -> Counter[tuple[str, ...]]:
        return Counter(tuple(sorted(entry.lineup)) for entry in self.entries)

    def score_percentile(self, score: float) -> float:
        scores = [entry.points for entry in self.scored_entries]
        if not scores:
            raise ValueError("contest has no scored entries")
        return 100 * sum(value <= score for value in scores) / len(scores)


def import_fanduel_results(path: str | Path) -> ContestResults:
    entries: dict[str, FieldEntry] = {}
    players: dict[str, PlayerResult] = {}
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        for row_number, row in enumerate(csv.DictReader(handle), start=2):
            try:
                entry_id = row["EntryId"]
                if entry_id not in entries:
                    lineup = tuple(part.strip() for part in row["Lineup"].split(",") if part.strip())
                    entries[entry_id] = FieldEntry(
                        entry_id=entry_id,
                        rank=int(row["Rank"]),
                        entry_name=row["EntryName"],
                        points=_optional_float(row["Points"]),
                        lineup=lineup,
                    )
                name = row.get("Player", "").strip()
                if name and name not in players:
                    players[name] = PlayerResult(
                        name=name,
                        position=row["Roster Position"].strip(),
                        drafted_percent=float(row["%Drafted"].strip().rstrip("%")),
                        fantasy_points=float(row["FPTS"]),
                    )
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"invalid FanDuel result row {row_number}: {exc}") from exc
    if not entries:
        raise ValueError("FanDuel result file contains no entries")
    return ContestResults(tuple(entries.values()), tuple(players.values()))


def import_player_results_content(
    content: bytes,
    filename: str,
    positions_by_name: dict[str, str] | None = None,
) -> tuple[PlayerResult, ...]:
    """Extract one unmultiplied final score per player from DK or FD standings."""
    if Path(filename).suffix.casefold() == ".zip":
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                names = [name for name in archive.namelist() if name.casefold().endswith(".csv")]
                if len(names) != 1:
                    raise ValueError("results ZIP must contain exactly one CSV file")
                text = archive.read(names[0]).decode("utf-8-sig")
        except zipfile.BadZipFile as exc:
            raise ValueError("results ZIP could not be opened") from exc
    else:
        text = content.decode("utf-8-sig")
    candidates: dict[str, list[tuple[str, PlayerResult]]] = {}
    normalized_positions = {
        _normalize_result_name(name): position
        for name, position in (positions_by_name or {}).items()
    }
    for row_number, row in enumerate(csv.DictReader(io.StringIO(text)), start=2):
        name = re.sub(r"\s+\([^()]+\)\s*$", "", row.get("Player", "").strip())
        if not name:
            continue
        try:
            result = PlayerResult(
                name=name,
                position=(
                    normalized_positions.get(_normalize_result_name(name))
                    or row.get("Roster Position", "").strip()
                ),
                drafted_percent=float(row["%Drafted"].strip().rstrip("%")),
                fantasy_points=float(row["FPTS"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"invalid player result row {row_number}: {exc}") from exc
        candidates.setdefault(_normalize_result_name(name), []).append((
            row.get("Roster Position", "").strip(), result
        ))
    selected = []
    for rows in candidates.values():
        # DraftKings Showdown publishes both CPT and FLEX summaries. FLEX is the
        # unmultiplied player outcome required for projection evaluation.
        selected.append(next(
            (result for role, result in rows if role == "FLEX"),
            rows[0][1],
        ))
    if not selected:
        raise ValueError("contest results contain no player outcomes")
    return tuple(selected)


def _optional_float(value: str) -> float | None:
    return None if value.strip().lower() in {"", "null"} else float(value)


def _normalize_result_name(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())
