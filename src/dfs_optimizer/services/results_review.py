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
    roster_slots: int = 0
    zero_point_players: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ResultsReview:
    field_size: int
    scored_entries: int
    winning_score: float
    lineups: tuple[ReviewedLineup, ...]
    unmatched_lineups: tuple[int, ...]
    ambiguous_lineups: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class WinnerStrategyBand:
    label: str
    unique_lineups: int
    average_score: float
    average_duplication: float
    average_salary_left: float | None
    average_ownership: float | None
    average_low_owned_players: float | None
    qb_stack_rate: float | None
    bring_back_rate: float | None
    double_te_rate: float | None
    average_quarterbacks: float | None
    average_kickers_and_defenses: float | None
    average_max_team_players: float | None
    receiver_multiplier_qb_pair_rate: float | None


@dataclass(frozen=True, slots=True)
class WinnerStrategyReport:
    field_size: int
    winning_score: float
    winner_lineups: tuple[SubmittedEntry, ...]
    bands: tuple[WinnerStrategyBand, ...]


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
    player_points: dict[str, float] = {}
    for result_row in rows:
        name = re.sub(
            r"\s+\([^()]+\)\s*$", "", (result_row.get("Player") or "").strip()
        )
        points = (result_row.get("FPTS") or "").strip()
        if not name or not points:
            continue
        try:
            player_points[_normalize_name(name)] = float(points)
        except ValueError:
            continue
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
        lineup_names = tuple(entry.player.name for entry in lineup.entries)
        zero_point_players = tuple(
            name for name in lineup_names
            if player_points.get(_normalize_name(name)) == 0
        )
        reviewed.append(ReviewedLineup(
            lineup_number=number,
            score=score,
            rank=rank,
            top_percent=100 * rank / len(entries),
            duplication=len(all_matches),
            entry_name=row["EntryName"],
            roster_slots=len(lineup_names),
            zero_point_players=zero_point_players,
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


def analyze_winner_strategies(content: bytes, filename: str, slate) -> WinnerStrategyReport:
    """Summarize field construction by finish band using unique lineups.

    Exact copies are collapsed before calculating construction rates so one
    duplicated roster does not masquerade as many independent strategies.
    """
    rows = _read_rows(content, filename)
    required = {"Rank", "EntryId", "EntryName", "Points", "Lineup"}
    missing = required - set(rows[0]) if rows else required
    if missing:
        raise ValueError(
            "contest results are missing columns: " + ", ".join(sorted(missing))
        )
    entries = tuple({row["EntryId"]: row for row in rows}.values())
    scored = tuple(
        row for row in entries
        if row["Points"].strip().lower() not in {"", "null"}
    )
    if not scored:
        raise ValueError("contest results do not contain any final scores")

    field_size = len(entries)
    keys = tuple(
        _field_lineup_key(row["Lineup"], slate.platform, slate.contest_format)
        for row in entries
    )
    duplications = Counter(keys)
    unique_rows: dict[object, dict[str, str]] = {}
    for row, key in zip(entries, keys, strict=True):
        if row["Points"].strip().lower() in {"", "null"}:
            continue
        prior = unique_rows.get(key)
        if prior is None or int(row["Rank"]) < int(prior["Rank"]):
            unique_rows[key] = row

    players = {
        _normalize_name(player.name): player for player in slate.players
    }
    ownership_by_name: dict[str, float] = {}
    ownership_parts: dict[str, dict[str, float]] = {}
    for row in rows:
        name = re.sub(r"\s+\([^()]+\)\s*$", "", (row.get("Player") or "").strip())
        role = (row.get("Roster Position") or "").strip()
        raw_ownership = (row.get("%Drafted") or "").strip().rstrip("%")
        if not name or not raw_ownership:
            continue
        try:
            ownership_parts.setdefault(_normalize_name(name), {})[role] = float(raw_ownership)
        except ValueError:
            continue
    for name, role_values in ownership_parts.items():
        ownership_by_name[name] = sum(role_values.values())

    records = []
    for key, row in unique_rows.items():
        parsed = _parse_field_lineup(row["Lineup"], slate.platform)
        selected = [
            (role, players.get(_normalize_name(name))) for role, name in parsed
        ]
        matched = [(role, player) for role, player in selected if player is not None]
        salary_used = None
        if len(matched) == len(parsed):
            salary_used = sum(
                (
                    player.multiplier_salary
                    if role in {"CPT", "MVP"} and player.multiplier_salary is not None
                    else player.salary
                )
                for role, player in matched
            )
        from dfs_optimizer.rules import classic_rules_for, single_game_rules_for
        rules = (
            single_game_rules_for(slate.platform)
            if slate.contest_format == ContestFormat.SINGLE_GAME
            else classic_rules_for(slate.platform, slate.sport)
        )
        ownerships = [
            ownership_by_name.get(_normalize_name(name)) for _, name in parsed
        ]
        ownership_complete = all(value is not None for value in ownerships)
        positions = [player.primary_position.value for _, player in matched]
        quarterbacks = [player for _, player in matched if player.primary_position.value == "QB"]
        kickers_and_defenses = sum(
            player.primary_position.value in {"K", "DST"}
            for _, player in matched
        )
        team_counts = Counter(player.team for _, player in matched)
        multiplier_player = next(
            (player for role, player in matched if role in {"CPT", "MVP"}),
            None,
        )
        receiver_multiplier_qb_pair = None
        if (
            slate.contest_format == ContestFormat.SINGLE_GAME
            and multiplier_player is not None
            and multiplier_player.primary_position.value in {"WR", "TE"}
        ):
            receiver_multiplier_qb_pair = any(
                quarterback.team == multiplier_player.team
                for quarterback in quarterbacks
            )
        qb_stack = bring_back = None
        if slate.contest_format == ContestFormat.CLASSIC and quarterbacks:
            qb_stack = any(
                any(
                    teammate.team == quarterback.team
                    and teammate.primary_position.value in {"WR", "TE"}
                    and teammate.platform_id != quarterback.platform_id
                    for _, teammate in matched
                )
                for quarterback in quarterbacks
            )
            bring_back = any(
                any(
                    opponent.team == quarterback.opponent
                    and opponent.primary_position.value in {"RB", "WR", "TE"}
                    for _, opponent in matched
                )
                for quarterback in quarterbacks
            )
        records.append({
            "rank": int(row["Rank"]),
            "score": float(row["Points"]),
            "duplication": duplications[key],
            "salary_left": rules.salary_cap - salary_used if salary_used is not None else None,
            "average_ownership": (
                sum(ownerships) / len(ownerships) if ownership_complete and ownerships else None
            ),
            "low_owned": (
                sum(value < 5 for value in ownerships) if ownership_complete else None
            ),
            "qb_stack": qb_stack,
            "bring_back": bring_back,
            "double_te": positions.count("TE") >= 2,
            "quarterbacks": len(quarterbacks),
            "kickers_and_defenses": kickers_and_defenses,
            "max_team_players": max(team_counts.values()) if team_counts else None,
            "receiver_multiplier_qb_pair": receiver_multiplier_qb_pair,
        })

    winning_score = max(float(row["Points"]) for row in scored)
    winning_rank = min(int(row["Rank"]) for row in scored)
    winners = tuple(
        SubmittedEntry(
            rank=int(row["Rank"]),
            score=float(row["Points"]),
            entry_name=row["EntryName"],
            duplication=duplications[key],
            lineup=_display_lineup(row["Lineup"], slate.platform, slate.contest_format),
        )
        for key, row in unique_rows.items()
        if int(row["Rank"]) == winning_rank
    )

    bands = []
    for label, fraction in (("Winner", 0), ("Top 0.1%", .001), ("Top 1%", .01), ("Top 5%", .05)):
        selected_records = [
            record for record in records
            if record["rank"] == winning_rank
            if fraction == 0
        ] if fraction == 0 else [
            record for record in records if record["rank"] / field_size <= fraction
        ]
        if not selected_records:
            continue

        def average_optional(name):
            values = [record[name] for record in selected_records if record[name] is not None]
            return sum(values) / len(values) if values else None

        bands.append(WinnerStrategyBand(
            label=label,
            unique_lineups=len(selected_records),
            average_score=sum(record["score"] for record in selected_records) / len(selected_records),
            average_duplication=sum(record["duplication"] for record in selected_records) / len(selected_records),
            average_salary_left=average_optional("salary_left"),
            average_ownership=average_optional("average_ownership"),
            average_low_owned_players=average_optional("low_owned"),
            qb_stack_rate=average_optional("qb_stack"),
            bring_back_rate=average_optional("bring_back"),
            double_te_rate=average_optional("double_te"),
            average_quarterbacks=average_optional("quarterbacks"),
            average_kickers_and_defenses=average_optional(
                "kickers_and_defenses"
            ),
            average_max_team_players=average_optional("max_team_players"),
            receiver_multiplier_qb_pair_rate=average_optional(
                "receiver_multiplier_qb_pair"
            ),
        ))
    return WinnerStrategyReport(field_size, winning_score, winners, tuple(bands))


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


def _normalize_name(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())


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
    parsed = _parse_field_lineup(value, platform)
    names = [name for _, name in parsed]
    if contest_format == ContestFormat.SINGLE_GAME and names:
        multiplier = "CPT" if platform == Platform.DRAFTKINGS else "MVP"
        multiplier_name = next(
            (name for role, name in parsed if role == multiplier), names[0]
        )
        flex = sorted(name for role, name in parsed if name != multiplier_name or role != multiplier)
        return ((multiplier, multiplier_name), *(('FLEX', name) for name in flex))
    return tuple(sorted(names))


def _parse_field_lineup(value: str, platform: Platform) -> tuple[tuple[str, str], ...]:
    if platform == Platform.FANDUEL:
        parsed = []
        for item in value.split(","):
            item = re.sub(r"\s*\([^)]*\)\s*$", "", item.strip())
            if item and " " in item:
                role, name = item.split(" ", 1)
                parsed.append(("MVP" if not parsed else role, name))
        return tuple(parsed)
    markers = list(re.finditer(
        r"(?:^|\s{1,2})(CPT|S-FLEX|FLEX|QB|RB|WR|TE|DST)\s+", value.strip()
    ))
    parsed = []
    for index, marker in enumerate(markers):
        end = markers[index + 1].start() if index + 1 < len(markers) else len(value.strip())
        parsed.append((marker.group(1), value.strip()[marker.end():end].strip()))
    return tuple(parsed)


def _display_lineup(
    value: str, platform: Platform, contest_format: ContestFormat
) -> tuple[tuple[str, str], ...]:
    key = _field_lineup_key(value, platform, contest_format)
    if contest_format == ContestFormat.SINGLE_GAME:
        return key
    return tuple(("", name) for name in key)
