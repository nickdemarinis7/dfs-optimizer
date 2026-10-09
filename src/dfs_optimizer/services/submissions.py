from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from dfs_optimizer.models import ContestFormat, Platform


@dataclass(frozen=True, slots=True)
class SubmittedRoster:
    lineup_number: int
    players: tuple[tuple[str, str, str], ...]

    @property
    def display(self) -> str:
        return ", ".join(f"{slot} {name}" for slot, _, name in self.players)


@dataclass(frozen=True, slots=True)
class SubmissionComparison:
    submitted_count: int
    generated_count: int
    exact_matches: int
    changed_count: int


def import_submitted_rosters(content: bytes, slate) -> tuple[SubmittedRoster, ...]:
    rows = list(csv.reader(io.StringIO(content.decode("utf-8-sig"))))
    if len(rows) < 2:
        raise ValueError("submitted lineup file must contain a header and at least one row")
    header = tuple(value.strip().upper() for value in rows[0])
    expected = (
        (("CPT", "MVP"), "FLEX", "FLEX", "FLEX", "FLEX", "FLEX")
        if slate.contest_format == ContestFormat.SINGLE_GAME
        else (("QB",), "RB", "RB", "WR", "WR", "WR", "TE", "FLEX", ("DST", "D", "DEF"))
    )
    start = _find_roster_start(header, expected)
    if start is None:
        raise ValueError("could not find the expected roster columns in submitted lineup file")
    width = len(expected)
    player_by_id = {}
    player_by_name = {}
    for player in slate.players:
        player_by_id[player.platform_id] = player
        if player.multiplier_platform_id:
            player_by_id[player.multiplier_platform_id] = player
        player_by_name[player.name.casefold()] = player
    rosters = []
    for row in rows[1:]:
        values = row[start:start + width]
        if len(values) < width or not any(value.strip() for value in values):
            continue
        if any(not value.strip() for value in values):
            continue
        players = []
        for index, value in enumerate(values):
            player = _resolve_player(value.strip(), slate.platform, player_by_id, player_by_name)
            raw_slot = header[start + index]
            slot = (
                ("CPT" if slate.platform == Platform.DRAFTKINGS else "MVP")
                if slate.contest_format == ContestFormat.SINGLE_GAME and index == 0
                else "FLEX" if slate.contest_format == ContestFormat.SINGLE_GAME
                else "DST" if raw_slot in {"D", "DEF", "DST"}
                else raw_slot
            )
            players.append((slot, player.platform_id, player.name))
        rosters.append(SubmittedRoster(len(rosters) + 1, tuple(players)))
    if not rosters:
        raise ValueError("submitted lineup file does not contain any complete rosters")
    return tuple(rosters)


def compare_submitted_rosters(rosters, generated) -> SubmissionComparison:
    submitted_keys = [_roster_key(item.players) for item in rosters]
    generated_keys = [_roster_key(tuple(
        (
            "CPT" if getattr(entry, "point_multiplier", 1) > 1 and entry.slot == "CPT"
            else "MVP" if getattr(entry, "point_multiplier", 1) > 1
            else "FLEX" if hasattr(entry, "point_multiplier")
            else entry.slot.rstrip("123"),
            entry.player.platform_id,
            entry.player.name,
        )
        for entry in lineup.entries
    )) for lineup in generated]
    unmatched = list(generated_keys)
    exact = 0
    for key in submitted_keys:
        if key in unmatched:
            exact += 1
            unmatched.remove(key)
    return SubmissionComparison(
        submitted_count=len(submitted_keys),
        generated_count=len(generated_keys),
        exact_matches=exact,
        changed_count=max(len(submitted_keys), len(generated_keys)) - exact,
    )


def submission_snapshot_bytes(run_id: str, slate, rosters, comparison) -> bytes:
    payload = {
        "run_id": run_id,
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "platform": slate.platform.value,
        "contest_format": slate.contest_format.value,
        "salary_source": slate.source_name,
        "comparison": {
            "submitted_count": comparison.submitted_count,
            "generated_count": comparison.generated_count,
            "exact_matches": comparison.exact_matches,
            "changed_count": comparison.changed_count,
        },
        "submitted_rosters": [
            {
                "lineup_number": roster.lineup_number,
                "players": [
                    {"slot": slot, "platform_id": player_id, "name": name}
                    for slot, player_id, name in roster.players
                ],
            }
            for roster in rosters
        ],
    }
    return (json.dumps(payload, indent=2) + "\n").encode()


def save_submission_snapshot(
    content: bytes, run_id: str, directory: str | Path = "data/submissions"
) -> Path:
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    destination = root / f"{run_id}.json"
    temporary = root / f"{run_id}.json.tmp"
    temporary.write_bytes(content)
    temporary.replace(destination)
    return destination


def _find_roster_start(header, expected):
    for start in range(len(header) - len(expected) + 1):
        if all(
            header[start + index] in allowed
            if isinstance(allowed, tuple) else header[start + index] == allowed
            for index, allowed in enumerate(expected)
        ):
            return start
    return None


def _resolve_player(value, platform, player_by_id, player_by_name):
    if platform == Platform.FANDUEL:
        player = player_by_id.get(value)
    else:
        match = re.match(r"(.*) \(([^()]*)\)$", value)
        player = (
            player_by_id.get(match.group(2)) or player_by_name.get(match.group(1).casefold())
            if match else player_by_name.get(value.casefold())
        )
    if player is None:
        raise ValueError(f"submitted player could not be matched to the slate: {value}")
    return player


def _roster_key(players):
    multiplier = tuple(
        player_id for slot, player_id, _ in players if slot in {"CPT", "MVP"}
    )
    grouped = {}
    for slot, player_id, _ in players:
        if slot in {"CPT", "MVP"}:
            continue
        grouped.setdefault(slot, []).append(player_id)
    return multiplier, tuple(
        (slot, tuple(sorted(ids))) for slot, ids in sorted(grouped.items())
    )
