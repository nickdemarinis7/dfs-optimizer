from __future__ import annotations

import csv
import io
import json
import re
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from dfs_optimizer.models import ContestFormat, Platform, Projection
from dfs_optimizer.optimization import (
    LineupEntry,
    OptimizedLineup,
    OptimizedSingleGameLineup,
    SingleGameEntry,
)
from dfs_optimizer.rules import classic_rules_for, single_game_rules_for
from dfs_optimizer.services.slates import load_uploaded_salary_file


@dataclass(frozen=True, slots=True)
class RunRecord:
    run_id: str
    label: str
    created_at: datetime
    platform: Platform
    contest_format: ContestFormat
    slate_id: str
    source_name: str
    lineup_count: int
    projection_count: int
    path: Path
    is_final: bool = False


@dataclass(frozen=True, slots=True)
class RunSnapshot:
    record: RunRecord
    projections: tuple[Projection, ...]
    lineup_players: tuple[tuple[str, ...], ...]


@dataclass(frozen=True, slots=True)
class RunComparison:
    projection_changes: tuple[dict[str, object], ...]
    changed_projection_count: int
    material_projection_count: int
    lineup_overlap_percent: float
    shared_lineups: int


def list_run_records(directory: str | Path = "data/runs") -> tuple[RunRecord, ...]:
    root = Path(directory)
    index = _read_index(root)
    records = []
    for path in root.glob("*.zip") if root.is_dir() else ():
        try:
            with zipfile.ZipFile(path) as archive:
                manifest = json.loads(archive.read("manifest.json"))
            run_id = manifest.get("run_id") or path.stem
            created = datetime.fromisoformat(manifest["created_at_utc"])
            label = index.get("labels", {}).get(run_id) or manifest.get("run_label") or run_id
            records.append(RunRecord(
                run_id=run_id,
                label=label,
                created_at=created,
                platform=Platform(manifest["platform"]),
                contest_format=ContestFormat(manifest["contest_format"]),
                slate_id=manifest.get("slate_id", "legacy"),
                source_name=manifest["salary_source"],
                lineup_count=int(manifest["lineup_count"]),
                projection_count=int(manifest["projection_count"]),
                path=path,
                is_final=index.get("final_by_slate", {}).get(manifest.get("slate_id", "legacy")) == run_id,
            ))
        except (KeyError, ValueError, OSError, json.JSONDecodeError, zipfile.BadZipFile):
            continue
    return tuple(sorted(records, key=lambda item: item.created_at, reverse=True))


def update_run_label(run_id: str, label: str, directory: str | Path = "data/runs") -> None:
    root = Path(directory)
    index = _read_index(root)
    index.setdefault("labels", {})[run_id] = label.strip() or run_id
    _write_index(root, index)


def mark_run_final(record: RunRecord, directory: str | Path = "data/runs") -> None:
    root = Path(directory)
    index = _read_index(root)
    index.setdefault("final_by_slate", {})[record.slate_id] = record.run_id
    _write_index(root, index)


def load_run_snapshot(record: RunRecord) -> RunSnapshot:
    with zipfile.ZipFile(record.path) as archive:
        projections = _read_projections(archive.read("projections.csv"))
        lineup_players = _read_lineup_players(archive.read("lineups.csv"), record.platform)
    return RunSnapshot(record, projections, lineup_players)


def compare_runs(older: RunRecord, newer: RunRecord) -> RunComparison:
    before, after = load_run_snapshot(older), load_run_snapshot(newer)
    before_by_key = {_projection_key(item): item for item in before.projections}
    after_by_key = {_projection_key(item): item for item in after.projections}
    changes = []
    for key in sorted(before_by_key.keys() | after_by_key.keys()):
        left, right = before_by_key.get(key), after_by_key.get(key)
        delta = None if left is None or right is None else right.projected_points - left.projected_points
        if left is None or right is None or abs(delta or 0) >= .01:
            item = right or left
            changes.append({
                "Player": item.name,
                "Team": item.team,
                "Earlier": left.projected_points if left else None,
                "Later": right.projected_points if right else None,
                "Change": delta,
            })
    left_sets = [set(lineup) for lineup in before.lineup_players]
    right_sets = [set(lineup) for lineup in after.lineup_players]
    pair_count = min(len(left_sets), len(right_sets))
    overlap = (
        sum(len(left_sets[i] & right_sets[i]) / max(1, len(left_sets[i] | right_sets[i])) for i in range(pair_count))
        / pair_count * 100 if pair_count else 0
    )
    shared = sum(1 for lineup in left_sets if lineup in right_sets)
    return RunComparison(
        projection_changes=tuple(sorted(changes, key=lambda row: abs(row["Change"] or 999), reverse=True)),
        changed_projection_count=len(changes),
        material_projection_count=sum(1 for row in changes if row["Change"] is None or abs(row["Change"]) >= 2),
        lineup_overlap_percent=overlap,
        shared_lineups=shared,
    )


def restore_run(record: RunRecord):
    with zipfile.ZipFile(record.path) as archive:
        salary_names = [name for name in archive.namelist() if name.startswith("salary/")]
        if len(salary_names) != 1:
            raise ValueError("this run does not contain exactly one salary file")
        salary_content = archive.read(salary_names[0])
        slate = load_uploaded_salary_file(Path(salary_names[0]).name, salary_content)
        projections = _read_projections(archive.read("projections.csv"))
        rows = list(csv.reader(io.StringIO(archive.read("lineups.csv").decode("utf-8-sig"))))
        manifest = json.loads(archive.read("manifest.json"))
    players_by_id = {player.platform_id: player for player in slate.players}
    players_by_name = {player.name: player for player in slate.players}
    projections_by_id = {item.platform_id: item for item in projections if item.platform_id}
    projections_by_name = {(item.name, item.team): item for item in projections}
    lineups = []
    for values in rows[1:]:
        entries = []
        for index, value in enumerate(values):
            player = _resolve_player(value, record.platform, players_by_id, players_by_name)
            projection = projections_by_id.get(player.platform_id) or projections_by_name[(player.name, player.team)]
            if record.contest_format == ContestFormat.CLASSIC:
                slot = rows[0][index]
                seen = sum(1 for entry in entries if entry.slot.rstrip("123") == slot)
                slot = f"{slot}{seen + 1}" if slot in {"RB", "WR"} else slot
                entries.append(LineupEntry(slot, player, projection))
            else:
                multiplier = 1.5 if index == 0 else 1.0
                salary = player.multiplier_salary if multiplier > 1 else player.salary
                entries.append(SingleGameEntry(rows[0][index], player, projection, salary, multiplier))
        rules = classic_rules_for(record.platform) if record.contest_format == ContestFormat.CLASSIC else single_game_rules_for(record.platform)
        lineups.append((OptimizedLineup if record.contest_format == ContestFormat.CLASSIC else OptimizedSingleGameLineup)(
            tuple(entries),
            sum(entry.player.salary if record.contest_format == ContestFormat.CLASSIC else entry.salary for entry in entries),
            sum(entry.projection.projected_points * getattr(entry, "point_multiplier", 1) for entry in entries),
            rules.salary_cap,
        ))
    return slate, projections, tuple(lineups), salary_content, manifest.get("settings", {})


def _read_projections(content: bytes) -> tuple[Projection, ...]:
    rows = csv.DictReader(io.StringIO(content.decode("utf-8-sig")))
    optional = lambda value: float(value) if value not in {None, ""} else None
    return tuple(Projection(
        name=row["name"], team=row["team"], platform_id=row["platform_id"] or None,
        projected_points=float(row["projected_points"]), floor=optional(row["floor"]),
        ceiling=optional(row["ceiling"]), projected_ownership=optional(row.get("projected_ownership")),
        p10=optional(row.get("p10")), p25=optional(row.get("p25")),
        p75=optional(row.get("p75")), p90=optional(row.get("p90")),
        bust_probability=optional(row.get("bust_probability")),
    ) for row in rows)


def _read_lineup_players(content: bytes, platform: Platform) -> tuple[tuple[str, ...], ...]:
    rows = list(csv.reader(io.StringIO(content.decode("utf-8-sig"))))
    return tuple(tuple(_cell_identity(value, platform) for value in row) for row in rows[1:])


def _cell_identity(value: str, platform: Platform) -> str:
    if platform == Platform.DRAFTKINGS:
        match = re.search(r"\(([^()]*)\)\s*$", value)
        return match.group(1) if match else value
    return value


def _resolve_player(value, platform, players_by_id, players_by_name):
    if platform == Platform.FANDUEL:
        return players_by_id[value]
    match = re.match(r"(.*) \(([^()]*)\)$", value)
    if not match:
        raise ValueError(f"could not restore player from {value!r}")
    return players_by_id.get(match.group(2)) or players_by_name[match.group(1)]


def _projection_key(item: Projection) -> str:
    return item.platform_id or f"{item.name.casefold()}|{item.team}"


def _read_index(root: Path) -> dict:
    try:
        return json.loads((root / "index.json").read_text())
    except (OSError, json.JSONDecodeError):
        return {"labels": {}, "final_by_slate": {}}


def _write_index(root: Path, index: dict) -> None:
    root.mkdir(parents=True, exist_ok=True)
    temporary = root / "index.json.tmp"
    temporary.write_text(json.dumps(index, indent=2) + "\n")
    temporary.replace(root / "index.json")
