from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from dfs_optimizer.models import ContestFormat, Platform, Projection, Sport
from dfs_optimizer.optimization import (
    LineupEntry,
    OptimizedLineup,
    OptimizedSingleGameLineup,
    SingleGameEntry,
)
from dfs_optimizer.rules import classic_rules_for, single_game_rules_for
from dfs_optimizer.services.slates import load_uploaded_salary_file
from dfs_optimizer.services.player_context import PlayerContext


MAX_RUN_ARCHIVE_BYTES = 50 * 1024 * 1024
MAX_RUN_ARCHIVE_FILES = 32
MAX_RUN_ARCHIVE_UNCOMPRESSED_BYTES = 200 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class RunRecord:
    run_id: str
    label: str
    created_at: datetime
    platform: Platform
    sport: Sport
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
    context_changes: tuple[dict[str, object], ...] = ()


@dataclass(frozen=True, slots=True)
class RunContextInputs:
    player_context: tuple[PlayerContext, ...]
    source: str | None
    checked_at: datetime | None
    final_status_content: bytes | None


def import_run_archive(
    content: bytes,
    directory: str | Path = "data/runs",
) -> RunRecord:
    """Validate and persist a downloaded run package for later restoration."""
    if not content:
        raise ValueError("the selected run package is empty")
    if len(content) > MAX_RUN_ARCHIVE_BYTES:
        raise ValueError("the run package is larger than the 50 MB import limit")

    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            members = archive.infolist()
            if len(members) > MAX_RUN_ARCHIVE_FILES:
                raise ValueError("the run package contains too many files")
            if sum(item.file_size for item in members) > MAX_RUN_ARCHIVE_UNCOMPRESSED_BYTES:
                raise ValueError("the run package expands beyond the safe import limit")
            names = {item.filename for item in members}
            required = {"manifest.json", "lineups.csv", "projections.csv"}
            missing = sorted(required - names)
            if missing:
                raise ValueError(
                    "the run package is incomplete; missing " + ", ".join(missing)
                )
            salary_names = [name for name in names if name.startswith("salary/")]
            if len(salary_names) != 1:
                raise ValueError("the run package must contain exactly one salary file")
            manifest = json.loads(archive.read("manifest.json"))
            _validate_import_manifest(manifest)
            integrity_errors = _archive_integrity_errors(archive, manifest)
            if integrity_errors:
                raise ValueError(
                    "run package integrity check failed: " + "; ".join(integrity_errors)
                )
    except zipfile.BadZipFile as exc:
        raise ValueError("the selected file is not a valid run package") from exc
    except (AttributeError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("the run package manifest is invalid") from exc

    root = Path(directory).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(content).hexdigest()
    raw_run_id = str(manifest.get("run_id") or "").strip()
    safe_run_id = re.sub(r"[^A-Za-z0-9._-]+", "-", raw_run_id).strip("-._")
    if not safe_run_id:
        created = datetime.fromisoformat(manifest["created_at_utc"])
        safe_run_id = (
            f"{created:%Y%m%dT%H%M%SZ}-{manifest['platform']}-"
            f"{manifest['contest_format']}-{digest[:6]}"
        )
    destination = root / f"{safe_run_id}.zip"
    if destination.exists():
        if hashlib.sha256(destination.read_bytes()).hexdigest() == digest:
            records = {item.path: item for item in list_run_records(root)}
            if destination in records:
                return records[destination]
        destination = root / f"{safe_run_id}-{digest[:8]}.zip"
    destination.write_bytes(content)
    records = {item.path: item for item in list_run_records(root)}
    try:
        return records[destination]
    except KeyError as exc:
        destination.unlink(missing_ok=True)
        raise ValueError("the imported run package could not be indexed") from exc


def _validate_import_manifest(manifest: dict) -> None:
    for key in (
        "created_at_utc", "platform", "contest_format", "salary_source",
        "lineup_count", "projection_count",
    ):
        if key not in manifest:
            raise ValueError(f"the run package manifest is missing {key}")
    datetime.fromisoformat(manifest["created_at_utc"])
    Platform(manifest["platform"])
    Sport(manifest.get("sport", "nfl"))
    ContestFormat(manifest["contest_format"])
    if int(manifest["lineup_count"]) < 1 or int(manifest["projection_count"]) < 1:
        raise ValueError("the run package does not contain a usable portfolio")


def _archive_integrity_errors(archive: zipfile.ZipFile, manifest: dict) -> list[str]:
    expected = {
        **manifest.get("artifacts", {}),
        **{
            f"inputs/{name}": detail
            for name, detail in manifest.get("input_snapshots", {}).items()
        },
    }
    names = set(archive.namelist())
    errors = []
    for name, detail in expected.items():
        if name not in names:
            errors.append(f"missing archived file: {name}")
            continue
        value = archive.read(name)
        if len(value) != detail.get("bytes"):
            errors.append(f"byte count changed: {name}")
        if hashlib.sha256(value).hexdigest() != detail.get("sha256"):
            errors.append(f"SHA-256 changed: {name}")
    return errors


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
                sport=Sport(manifest.get("sport", "nfl")),
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


def load_run_context_inputs(record: RunRecord) -> RunContextInputs:
    """Restore optional player-context inputs saved by newer run archives."""
    with zipfile.ZipFile(record.path) as archive:
        names = set(archive.namelist())
        if "inputs/player-context.json" not in names:
            return RunContextInputs((), None, None, None)
        payload = json.loads(archive.read("inputs/player-context.json"))
        final_status_content = (
            archive.read("inputs/final-status.csv")
            if "inputs/final-status.csv" in names else None
        )
    checked_value = payload.get("checked_at")
    try:
        checked_at = datetime.fromisoformat(checked_value) if checked_value else None
    except (TypeError, ValueError):
        checked_at = None
    contexts = tuple(PlayerContext(
        platform_id=item["platform_id"],
        depth_chart_position=item.get("depth_chart_position"),
        injury_status=item.get("injury_status"),
        practice_participation=item.get("practice_participation"),
        active=item.get("active"),
        verified_projection=item.get("verified_projection"),
        expected_role=item.get("expected_role"),
        role_note=item.get("role_note"),
        injury_reported=bool(item.get("injury_reported")),
    ) for item in payload.get("players", ()))
    return RunContextInputs(
        contexts, payload.get("source"), checked_at, final_status_content
    )


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
    context_changes = _compare_weekly_context_inputs(older, newer)
    return RunComparison(
        projection_changes=tuple(sorted(changes, key=lambda row: abs(row["Change"] or 999), reverse=True)),
        changed_projection_count=len(changes),
        material_projection_count=sum(1 for row in changes if row["Change"] is None or abs(row["Change"]) >= 2),
        lineup_overlap_percent=overlap,
        shared_lineups=shared,
        context_changes=context_changes,
    )


def run_input_coverage(record: RunRecord) -> dict[str, bool]:
    """Report which optional decision inputs were preserved in a run."""
    with zipfile.ZipFile(record.path) as archive:
        names = set(archive.namelist())
    return {
        "Player status": "inputs/player-context.json" in names,
        "Weekly context": "inputs/weekly-context.json" in names,
        "Weather": "inputs/weekly-context.json" in names,
        "News scan": "inputs/nfl-news-candidates.json" in names,
        "Final inactives": "inputs/final-status.csv" in names,
        "Ownership": "inputs/uploaded-ownership.csv" in names,
        "Player props": "inputs/nfl-prop-consensus.json" in names,
    }


def _compare_weekly_context_inputs(
    older: RunRecord, newer: RunRecord
) -> tuple[dict[str, object], ...]:
    def load(record):
        with zipfile.ZipFile(record.path) as archive:
            name = "inputs/weekly-context.json"
            return json.loads(archive.read(name)) if name in archive.namelist() else {}

    before, after = load(older), load(newer)
    changes = []
    before_players = {
        item.get("platform_id"): item
        for item in before.get("player_observations", ())
        if item.get("platform_id")
    }
    after_players = {
        item.get("platform_id"): item
        for item in after.get("player_observations", ())
        if item.get("platform_id")
    }
    fields = (
        ("practice_participation", "Practice"),
        ("injury_status", "Injury"),
        ("active", "Active"),
        ("depth_chart_position", "Depth"),
        ("expected_role", "Role"),
    )
    for player_id in sorted(before_players.keys() | after_players.keys()):
        left, right = before_players.get(player_id, {}), after_players.get(player_id, {})
        for key, label in fields:
            if left.get(key) != right.get(key):
                changes.append({
                    "Subject": right.get("name") or left.get("name") or player_id,
                    "Signal": label,
                    "Earlier": left.get(key),
                    "Later": right.get(key),
                })
    before_teams = {
        item.get("team"): item for item in before.get("teams", ())
        if item.get("team")
    }
    after_teams = {
        item.get("team"): item for item in after.get("teams", ())
        if item.get("team")
    }
    for team in sorted(before_teams.keys() | after_teams.keys()):
        left, right = before_teams.get(team, {}), after_teams.get(team, {})
        for key, label in (
            ("wind_mph", "Wind"),
            ("temperature_f", "Temperature"),
            ("precipitation_probability", "Precipitation"),
            ("weather_summary", "Weather"),
            ("defensive_absences", "Opponent defensive injuries"),
        ):
            if left.get(key) != right.get(key):
                changes.append({
                    "Subject": team,
                    "Signal": label,
                    "Earlier": left.get(key),
                    "Later": right.get(key),
                })
    return tuple(changes)


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
    lineups = _restore_lineups_from_rows(slate, projections, rows, record)
    return slate, projections, lineups, salary_content, manifest.get("settings", {})


def restore_shadow_run(record: RunRecord):
    """Restore the optional no-weekly-context A/B portfolio."""
    slate, _, _, _, _ = restore_run(record)
    with zipfile.ZipFile(record.path) as archive:
        names = set(archive.namelist())
        required = {"shadow/projections.csv", "shadow/lineups.csv"}
        if not required <= names:
            return (), ()
        projections = _read_projections(archive.read("shadow/projections.csv"))
        rows = list(csv.reader(io.StringIO(
            archive.read("shadow/lineups.csv").decode("utf-8-sig")
        )))
    return projections, _restore_lineups_from_rows(slate, projections, rows, record)


def _restore_lineups_from_rows(slate, projections, rows, record):
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
        rules = (
            classic_rules_for(record.platform, record.sport)
            if record.contest_format == ContestFormat.CLASSIC
            else single_game_rules_for(record.platform)
        )
        lineups.append((OptimizedLineup if record.contest_format == ContestFormat.CLASSIC else OptimizedSingleGameLineup)(
            tuple(entries),
            sum(entry.player.salary if record.contest_format == ContestFormat.CLASSIC else entry.salary for entry in entries),
            sum(entry.projection.projected_points * getattr(entry, "point_multiplier", 1) for entry in entries),
            rules.salary_cap,
        ))
    return tuple(lineups)


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
        sample_size=(
            int(row["sample_size"]) if row.get("sample_size") not in {None, ""} else None
        ),
        opportunity_stability=optional(row.get("opportunity_stability")),
        data_age_periods=(
            int(row["data_age_periods"])
            if row.get("data_age_periods") not in {None, ""} else None
        ),
        recent_return_games=(
            int(row["recent_return_games"])
            if row.get("recent_return_games") not in {None, ""} else None
        ),
        confidence_score=optional(row.get("confidence_score")),
        confidence_tier=row.get("confidence_tier") or None,
        confidence_reasons=tuple(json.loads(row.get("confidence_reasons") or "[]")),
        prop_market_count=(
            int(row["prop_market_count"])
            if row.get("prop_market_count") not in {None, ""} else None
        ),
        prop_coverage_checked=(row.get("prop_coverage_checked") == "True"),
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
