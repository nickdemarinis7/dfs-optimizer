from __future__ import annotations

import csv
import io
import re
import zipfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from dfs_optimizer.models import ContestFormat, Platform


@dataclass(frozen=True, slots=True)
class ReviewedLineup:
    lineup_number: int
    score: float
    rank: int
    top_percent: float
    duplication: int
    entry_name: str


@dataclass(frozen=True, slots=True)
class ResultsReview:
    field_size: int
    scored_entries: int
    winning_score: float
    lineups: tuple[ReviewedLineup, ...]
    unmatched_lineups: tuple[int, ...]
    ambiguous_lineups: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class SubmittedEntry:
    rank: int
    score: float
    entry_name: str
    duplication: int
    lineup: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class SavedPortfolio:
    run_id: str
    label: str
    lineups: tuple
    is_current: bool = False


@dataclass(frozen=True, slots=True)
class CapturedSubmission:
    run_id: str
    label: str
    rosters: tuple


@dataclass(frozen=True, slots=True)
class ProvenancedEntry:
    entry: SubmittedEntry
    source: str
    run_id: str | None
    run_label: str | None
    lineup_number: int | None

    @property
    def verified(self) -> bool:
        return self.run_id is not None

    @property
    def current_run(self) -> bool:
        return self.source == "Current run"


def review_contest_results(
    content: bytes,
    filename: str,
    lineups,
    platform: Platform,
    contest_format: ContestFormat,
    entry_name_contains: str = "",
) -> ResultsReview:
    rows = _read_rows(content, filename)
    required = {"Rank", "EntryId", "EntryName", "Points", "Lineup"}
    missing = required - set(rows[0]) if rows else required
    if missing:
        raise ValueError(
            "contest results are missing columns: " + ", ".join(sorted(missing))
        )
    entries = {row["EntryId"]: row for row in rows}.values()
    entries = tuple(entries)
    scored = tuple(
        row for row in entries if row["Points"].strip().lower() not in {"", "null"}
    )

    if not scored:
        raise ValueError("contest results do not contain any final scores")

    field_keys = [
        _field_lineup_key(row["Lineup"], platform, contest_format)
        for row in entries
    ]
    needle = entry_name_contains.strip().casefold()
    reviewed = []
    unmatched = []
    ambiguous = []
    for number, lineup in enumerate(lineups, 1):
        key = _generated_lineup_key(lineup, platform, contest_format)
        all_matches = [
            row for row, field_key in zip(entries, field_keys, strict=True)
            if field_key == key
        ]
        matches = [
            row for row in all_matches
            if not needle or needle in row["EntryName"].casefold()
        ]
        if not matches:
            unmatched.append(number)
            continue
        distinct_scores = {
            row["Points"] for row in matches
            if row["Points"].strip().lower() not in {"", "null"}
        }
        if len(distinct_scores) > 1:
            ambiguous.append(number)
            continue
        row = matches[0]
        score = float(row["Points"])
        rank = int(row["Rank"])
        reviewed.append(ReviewedLineup(
            lineup_number=number,
            score=score,
            rank=rank,
            top_percent=100 * rank / len(entries),
            duplication=len(all_matches),
            entry_name=row["EntryName"],
        ))
    return ResultsReview(
        field_size=len(entries),
        scored_entries=len(scored),
        winning_score=max(float(row["Points"]) for row in scored),
        lineups=tuple(reviewed),
        unmatched_lineups=tuple(unmatched),
        ambiguous_lineups=tuple(ambiguous),
    )


def extract_submitted_entries(
    content: bytes,
    filename: str,
    platform: Platform,
    contest_format: ContestFormat,
    entry_name_contains: str,
) -> tuple[SubmittedEntry, ...]:
    """Return actual submitted entries directly from final contest standings."""
    needle = entry_name_contains.strip().casefold()
    if not needle:
        raise ValueError("enter a username to find submitted entries")
    rows = _read_rows(content, filename)
    required = {"Rank", "EntryId", "EntryName", "Points", "Lineup"}
    missing = required - set(rows[0]) if rows else required
    if missing:
        raise ValueError(
            "contest results are missing columns: " + ", ".join(sorted(missing))
        )
    entries = tuple({row["EntryId"]: row for row in rows}.values())
    keys = tuple(
        _field_lineup_key(row["Lineup"], platform, contest_format) for row in entries
    )
    duplications = Counter(keys)
    submitted = []
    for row, key in zip(entries, keys, strict=True):
        if needle not in row["EntryName"].casefold():
            continue
        if row["Points"].strip().lower() in {"", "null"}:
            continue
        submitted.append(SubmittedEntry(
            rank=int(row["Rank"]),
            score=float(row["Points"]),
            entry_name=row["EntryName"],
            duplication=duplications[key],
            lineup=_display_lineup(row["Lineup"], platform, contest_format),
        ))
    return tuple(sorted(submitted, key=lambda item: item.rank))


def classify_submitted_entry_provenance(
    entries: tuple[SubmittedEntry, ...],
    portfolios: tuple[SavedPortfolio, ...],
    platform: Platform,
    contest_format: ContestFormat,
    captured_submissions: tuple[CapturedSubmission, ...] = (),
) -> tuple[ProvenancedEntry, ...]:
    """Match submitted entries only to exact lineups from saved app runs.

    Portfolios are evaluated in the supplied order, so callers should put the
    current run first. A lineup present in both the current and an older run is
    attributed to the current run rather than double-counted.
    """
    saved: dict[object, tuple[SavedPortfolio, int]] = {}
    for portfolio in portfolios:
        for number, lineup in enumerate(portfolio.lineups, 1):
            key = _generated_lineup_key(lineup, platform, contest_format)
            saved.setdefault(key, (portfolio, number))

    captured: dict[object, tuple[CapturedSubmission, int]] = {}
    for submission in captured_submissions:
        for roster in submission.rosters:
            key = _captured_roster_key(roster, contest_format)
            captured.setdefault(key, (submission, roster.lineup_number))

    classified = []
    for entry in entries:
        entry_key = _submitted_entry_key(entry, contest_format)
        match = saved.get(entry_key)
        if match is not None:
            portfolio, lineup_number = match
            classified.append(ProvenancedEntry(
                entry=entry,
                source="Current run" if portfolio.is_current else "Earlier saved run",
                run_id=portfolio.run_id,
                run_label=portfolio.label,
                lineup_number=lineup_number,
            ))
            continue
        captured_match = captured.get(entry_key)
        if captured_match is not None:
            submission, lineup_number = captured_match
            classified.append(ProvenancedEntry(
                entry=entry,
                source="Captured submission change",
                run_id=submission.run_id,
                run_label=submission.label,
                lineup_number=lineup_number,
            ))
            continue
        if match is None:
            classified.append(ProvenancedEntry(
                entry=entry,
                source="Unverified",
                run_id=None,
                run_label=None,
                lineup_number=None,
            ))
            continue
    return tuple(classified)


def _submitted_entry_key(entry: SubmittedEntry, contest_format: ContestFormat):
    if contest_format == ContestFormat.SINGLE_GAME:
        return entry.lineup
    return tuple(sorted(name for _, name in entry.lineup))


def _captured_roster_key(roster, contest_format: ContestFormat):
    if contest_format == ContestFormat.SINGLE_GAME:
        multiplier = next(
            (name for slot, _, name in roster.players if slot in {"CPT", "MVP"}),
            "",
        )
        flex = sorted(
            name for slot, _, name in roster.players if slot not in {"CPT", "MVP"}
        )
        role = next(
            (slot for slot, _, _ in roster.players if slot in {"CPT", "MVP"}),
            "MVP",
        )
        return ((role, multiplier), *(("FLEX", name) for name in flex))
    return tuple(sorted(name for _, _, name in roster.players))


def _read_rows(content: bytes, filename: str) -> list[dict[str, str]]:
    try:
        if Path(filename).suffix.casefold() == ".zip":
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                csv_names = [name for name in archive.namelist() if name.casefold().endswith(".csv")]
                if len(csv_names) != 1:
                    raise ValueError("results ZIP must contain exactly one CSV file")
                text = archive.read(csv_names[0]).decode("utf-8-sig")
        else:
            text = content.decode("utf-8-sig")
    except zipfile.BadZipFile as exc:
        raise ValueError("results ZIP could not be opened") from exc
    except UnicodeDecodeError as exc:
        raise ValueError("results file must be a UTF-8 CSV") from exc
    return list(csv.DictReader(io.StringIO(text)))


def _generated_lineup_key(lineup, platform: Platform, contest_format: ContestFormat):
    if contest_format == ContestFormat.SINGLE_GAME:
        multiplier = "CPT" if platform == Platform.DRAFTKINGS else "MVP"
        return (
            (multiplier, lineup.entries[0].player.name),
            *(('FLEX', name) for name in sorted(
                entry.player.name for entry in lineup.entries[1:]
            )),
        )
    return tuple(sorted(entry.player.name for entry in lineup.entries))


def _field_lineup_key(value: str, platform: Platform, contest_format: ContestFormat):
    if platform == Platform.FANDUEL:
        names = []
        for item in value.split(","):
            item = re.sub(r"\s*\([^)]*\)\s*$", "", item.strip())
            if item and " " in item:
                names.append(item.split(" ", 1)[1])
        if contest_format == ContestFormat.SINGLE_GAME and names:
            return (("MVP", names[0]), *(('FLEX', name) for name in sorted(names[1:])))
        return tuple(sorted(names))
    markers = list(re.finditer(
        r"(?:^|\s{1,2})(CPT|S-FLEX|FLEX|QB|RB|WR|TE|DST)\s+", value.strip()
    ))
    parsed = []
    for index, marker in enumerate(markers):
        end = markers[index + 1].start() if index + 1 < len(markers) else len(value.strip())
        parsed.append((marker.group(1), value.strip()[marker.end():end].strip()))
    if contest_format == ContestFormat.SINGLE_GAME:
        captain = next((name for role, name in parsed if role == "CPT"), "")
        flex = sorted(name for role, name in parsed if role == "FLEX")
        return (("CPT", captain), *(('FLEX', name) for name in flex))
    return tuple(sorted(name for _, name in parsed))


def _display_lineup(
    value: str, platform: Platform, contest_format: ContestFormat
) -> tuple[tuple[str, str], ...]:
    key = _field_lineup_key(value, platform, contest_format)
    if contest_format == ContestFormat.SINGLE_GAME:
        return key
    return tuple(("", name) for name in key)
