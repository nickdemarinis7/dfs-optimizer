from __future__ import annotations

import csv
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


def _optional_float(value: str) -> float | None:
    return None if value.strip().lower() in {"", "null"} else float(value)

