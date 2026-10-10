from __future__ import annotations

import csv
import io
from pathlib import Path

from dfs_optimizer.models import Platform
from dfs_optimizer.optimization import OptimizedLineup


ROSTER_HEADERS = ("QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX", "DST")


def export_lineups_csv(
    lineups: tuple[OptimizedLineup, ...], platform: Platform, path: str | Path
) -> Path:
    """Export roster columns suitable for a platform bulk-upload template.

    DraftKings cells use its `Name (ID)` representation. FanDuel cells use its
    slate-qualified player IDs. Contest-entry metadata columns are deliberately
    not fabricated; users can paste these roster columns into a downloaded
    contest template when that metadata is required.
    """
    if not lineups:
        raise ValueError("at least one lineup is required for export")
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(lineups_csv_text(lineups, platform), encoding="utf-8")
    return destination


def lineups_csv_text(lineups, platform: Platform) -> str:
    if not lineups:
        raise ValueError("at least one lineup is required for export")
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    headers = _lineup_headers(lineups, platform)
    writer.writerow(headers)
    for lineup in lineups:
        writer.writerow(
            _player_value(entry.player.name, getattr(entry, "platform_id", entry.player.platform_id), platform)
            for entry in lineup.entries
        )
    return output.getvalue()


def merge_lineups_into_template(lineups, platform: Platform, template: bytes) -> bytes:
    rows = list(csv.reader(io.StringIO(template.decode("utf-8-sig"))))
    if len(rows) < 2:
        raise ValueError("entry template must contain a header and at least one entry row")
    header = rows[0]
    roster_headers = _lineup_headers(lineups, platform)
    normalized_roster = tuple(_normalize_header(value) for value in roster_headers)
    start = next((
        index for index in range(len(header) - len(roster_headers) + 1)
        if tuple(
            _normalize_header(value)
            for value in header[index:index + len(roster_headers)]
        ) == normalized_roster
    ), None)
    if start is None:
        raise ValueError("entry template does not contain the expected Classic roster columns")
    if len(rows) - 1 < len(lineups):
        raise ValueError(f"entry template has {len(rows) - 1} rows but {len(lineups)} lineups were generated")
    for row, lineup in zip(rows[1:], lineups, strict=False):
        if len(row) < len(header):
            row.extend([""] * (len(header) - len(row)))
        row[start:start + len(roster_headers)] = [
            _player_value(entry.player.name, getattr(entry, "platform_id", entry.player.platform_id), platform)
            for entry in lineup.entries
        ]
    output = io.StringIO(newline="")
    csv.writer(output).writerows(rows)
    return output.getvalue().encode("utf-8")


def _lineup_headers(lineups, platform: Platform) -> tuple[str, ...]:
    first_entries = lineups[0].entries
    if hasattr(first_entries[0], "point_multiplier"):
        return (first_entries[0].slot, "FLEX", "FLEX", "FLEX", "FLEX", "FLEX")
    if len(first_entries) == len(ROSTER_HEADERS):
        return ROSTER_HEADERS
    return tuple(
        "Super FLEX" if entry.slot == "S-FLEX" and platform == Platform.FANDUEL
        else entry.slot.rstrip("123")
        for entry in first_entries
    )


def _normalize_header(value: str) -> str:
    normalized = value.strip().upper().replace("SUPER FLEX", "S-FLEX")
    return "DST" if normalized in {"D", "DEF", "DST"} else normalized


def _player_value(name: str, player_id: str, platform: Platform) -> str:
    if platform == Platform.DRAFTKINGS:
        return f"{name} ({player_id})"
    return player_id
