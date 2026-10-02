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
    first_entries = lineups[0].entries
    writer.writerow(
        (first_entries[0].slot, "FLEX", "FLEX", "FLEX", "FLEX", "FLEX")
        if hasattr(first_entries[0], "point_multiplier") else ROSTER_HEADERS
    )
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
    start = next((
        index for index in range(len(header) - len(ROSTER_HEADERS) + 1)
        if tuple(header[index:index + 8]) == ROSTER_HEADERS[:8]
        and header[index + 8].strip().upper() in {"D", "DEF", "DST"}
    ), None)
    if start is None:
        raise ValueError("entry template does not contain the expected Classic roster columns")
    if len(rows) - 1 < len(lineups):
        raise ValueError(f"entry template has {len(rows) - 1} rows but {len(lineups)} lineups were generated")
    for row, lineup in zip(rows[1:], lineups, strict=False):
        if len(row) < len(header):
            row.extend([""] * (len(header) - len(row)))
        row[start:start + len(ROSTER_HEADERS)] = [
            _player_value(entry.player.name, getattr(entry, "platform_id", entry.player.platform_id), platform)
            for entry in lineup.entries
        ]
    output = io.StringIO(newline="")
    csv.writer(output).writerows(rows)
    return output.getvalue().encode("utf-8")


def _player_value(name: str, player_id: str, platform: Platform) -> str:
    if platform == Platform.DRAFTKINGS:
        return f"{name} ({player_id})"
    return player_id
