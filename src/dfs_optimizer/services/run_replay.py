from __future__ import annotations

import csv
import hashlib
import io
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import re
import tempfile
import zipfile

from dfs_optimizer.importers import match_projections
from dfs_optimizer.models import ContestFormat, Platform, Projection, Sport
from dfs_optimizer.optimization import ClassicOptimizationSettings, generate_classic_lineups

from .cfb_projections import (
    CFB_FORECAST_MODEL_VERSION,
    apply_cfb_game_lines,
    build_cfb_projections_from_file,
    restore_verified_cfb_starters,
)
from .confidence import apply_projection_confidence
from .player_context import PlayerContext
from .projections import apply_uploaded_ownership
from .slates import load_uploaded_salary_file


@dataclass(frozen=True, slots=True)
class ArchiveReplayReport:
    integrity_ok: bool
    integrity_errors: tuple[str, ...]
    reconstructable: bool
    reason: str | None
    archived_model_version: str | None
    current_model_version: str | None
    model_version_match: bool
    archived_projection_count: int
    rebuilt_projection_count: int | None
    changed_projection_count: int | None
    maximum_projection_delta: float | None
    missing_projection_ids: tuple[str, ...]
    unexpected_projection_ids: tuple[str, ...]
    archived_lineup_count: int
    rebuilt_lineup_count: int | None
    exact_lineup_matches: int | None
    changed_confidence_count: int | None = None
    maximum_confidence_delta: float | None = None

    @property
    def projections_match(self) -> bool:
        return (
            self.reconstructable
            and self.changed_projection_count == 0
            and self.changed_confidence_count in {None, 0}
            and not self.missing_projection_ids
            and not self.unexpected_projection_ids
        )

    @property
    def lineups_match(self) -> bool:
        return (
            self.reconstructable
            and self.rebuilt_lineup_count == self.archived_lineup_count
            and self.exact_lineup_matches == self.archived_lineup_count
        )


def replay_run_archive(content: bytes | str | Path) -> ArchiveReplayReport:
    """Verify a run package and deterministically replay supported CFB runs."""
    payload = Path(content).read_bytes() if isinstance(content, (str, Path)) else content
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        integrity_errors = _integrity_errors(archive, manifest)
        if integrity_errors:
            settings = manifest.get("settings", {})
            return ArchiveReplayReport(
                False, tuple(integrity_errors), False,
                "archive integrity verification failed",
                settings.get("projection_model_version"),
                CFB_FORECAST_MODEL_VERSION,
                settings.get("projection_model_version") == CFB_FORECAST_MODEL_VERSION,
                int(manifest.get("projection_count", 0)), None, None, None,
                (), (), int(manifest.get("lineup_count", 0)), None, None,
            )
        archived = _read_projections(archive.read("projections.csv"))
        archived_lineups = _read_lineups(
            archive.read("lineups.csv"), Platform(manifest["platform"])
        )
        settings = manifest.get("settings", {})
        archived_version = settings.get("projection_model_version")
        salary_names = [name for name in archive.namelist() if name.startswith("salary/")]
        history_names = [
            name for name in archive.namelist()
            if name.startswith("inputs/cfb-") and "through-week" in name
        ]
        reason = _unsupported_reason(manifest, settings, salary_names, history_names)
        if reason:
            return ArchiveReplayReport(
                not integrity_errors, tuple(integrity_errors), False, reason,
                archived_version, CFB_FORECAST_MODEL_VERSION,
                archived_version == CFB_FORECAST_MODEL_VERSION,
                len(archived), None, None, None, (), (), len(archived_lineups),
                None, None,
            )
        salary_content = archive.read(salary_names[0])
        history_content = archive.read(history_names[0])
        lines_content = (
            archive.read("inputs/cfb-game-lines.csv")
            if "inputs/cfb-game-lines.csv" in archive.namelist() else None
        )
        ownership_content = (
            archive.read("inputs/uploaded-ownership.csv")
            if "inputs/uploaded-ownership.csv" in archive.namelist() else None
        )
        if settings.get("ownership_source") == "uploaded" and ownership_content is None:
            return ArchiveReplayReport(
                True, (), False,
                "archive uses uploaded ownership but lacks its input snapshot",
                archived_version, CFB_FORECAST_MODEL_VERSION,
                archived_version == CFB_FORECAST_MODEL_VERSION,
                len(archived), None, None, None, (), (), len(archived_lineups),
                None, None,
            )

    slate = load_uploaded_salary_file(Path(salary_names[0]).name, salary_content)
    target_week = int(settings["cfb_target_week"])
    with tempfile.TemporaryDirectory() as directory:
        history_path = Path(directory) / "cfb-history.csv"
        history_path.write_bytes(history_content)
        rebuilt = build_cfb_projections_from_file(slate, history_path, target_week)
    if lines_content:
        rebuilt, _ = apply_cfb_game_lines(slate, rebuilt, lines_content)
    contexts = _contexts_from_settings(slate, settings)
    rebuilt = restore_verified_cfb_starters(slate, rebuilt, contexts)
    if ownership_content:
        rebuilt, _ = apply_uploaded_ownership(
            slate, rebuilt, "uploaded-ownership.csv", ownership_content
        )
    context_age = None
    checked_at = settings.get("player_context_checked_at")
    created_at = manifest.get("created_at_utc")
    if checked_at and created_at:
        context_age = max(0.0, (
            datetime.fromisoformat(created_at) - datetime.fromisoformat(checked_at)
        ).total_seconds() / 60)
    rebuilt = apply_projection_confidence(
        slate, rebuilt, contexts, context_age_minutes=context_age
    )

    archived_by_id = {item.platform_id: item for item in archived if item.platform_id}
    rebuilt_by_id = {item.platform_id: item for item in rebuilt if item.platform_id}
    shared_ids = archived_by_id.keys() & rebuilt_by_id.keys()
    deltas = {
        player_id: abs(
            archived_by_id[player_id].projected_points
            - rebuilt_by_id[player_id].projected_points
        )
        for player_id in shared_ids
    }
    tolerance = .001
    changed = sum(delta > tolerance for delta in deltas.values())
    confidence_deltas = {
        player_id: abs(
            (archived_by_id[player_id].confidence_score or 0)
            - (rebuilt_by_id[player_id].confidence_score or 0)
        )
        for player_id in shared_ids
        if archived_by_id[player_id].confidence_score is not None
        or rebuilt_by_id[player_id].confidence_score is not None
    }
    missing = tuple(sorted(archived_by_id.keys() - rebuilt_by_id.keys()))
    unexpected = tuple(sorted(rebuilt_by_id.keys() - archived_by_id.keys()))

    rebuilt_lineups = _rebuild_lineups(slate, rebuilt, settings)
    rebuilt_id_sets = tuple(
        frozenset(entry.player.platform_id for entry in lineup.entries)
        for lineup in rebuilt_lineups
    )
    exact_matches = sum(
        left == right
        for left, right in zip(archived_lineups, rebuilt_id_sets)
    )
    return ArchiveReplayReport(
        not integrity_errors,
        tuple(integrity_errors),
        True,
        None,
        archived_version,
        CFB_FORECAST_MODEL_VERSION,
        archived_version == CFB_FORECAST_MODEL_VERSION,
        len(archived),
        len(rebuilt),
        changed,
        max(deltas.values(), default=0.0),
        missing,
        unexpected,
        len(archived_lineups),
        len(rebuilt_lineups),
        exact_matches,
        sum(delta > tolerance for delta in confidence_deltas.values()),
        max(confidence_deltas.values(), default=0.0),
    )


def _integrity_errors(archive: zipfile.ZipFile, manifest: dict) -> list[str]:
    errors = []
    expected = {
        **manifest.get("artifacts", {}),
        **{
            f"inputs/{name}": detail
            for name, detail in manifest.get("input_snapshots", {}).items()
        },
    }
    names = set(archive.namelist())
    for name, detail in expected.items():
        if name not in names:
            errors.append(f"missing archived file: {name}")
            continue
        content = archive.read(name)
        if len(content) != detail.get("bytes"):
            errors.append(f"byte count changed: {name}")
        if hashlib.sha256(content).hexdigest() != detail.get("sha256"):
            errors.append(f"SHA-256 changed: {name}")
    return errors


def _unsupported_reason(manifest, settings, salary_names, history_names) -> str | None:
    if Sport(manifest.get("sport", "nfl")) != Sport.CFB:
        return "projection replay currently supports CFB archives"
    if ContestFormat(manifest["contest_format"]) != ContestFormat.CLASSIC:
        return "lineup replay currently supports Classic archives"
    if len(salary_names) != 1:
        return "archive must contain exactly one salary file"
    if len(history_names) != 1:
        return "archive lacks a unique CFB projection-input snapshot"
    if settings.get("cfb_target_week") is None:
        return "archive does not record the CFB target week"
    return None


def _contexts_from_settings(slate, settings) -> tuple[PlayerContext, ...]:
    players_by_name = {player.name: player for player in slate.players}
    contexts = []
    for item in settings.get("player_context", ()):
        player = players_by_name.get(item.get("player"))
        if player is None:
            continue
        contexts.append(PlayerContext(
            player.platform_id,
            item.get("depth_chart_position"),
            item.get("injury_status"),
            item.get("practice_participation"),
            item.get("active"),
            item.get("verified_projection"),
            item.get("expected_role"),
            item.get("role_note"),
        ))
    return tuple(contexts)


def _rebuild_lineups(slate, projections, settings):
    ids_by_name = {player.name: player.platform_id for player in slate.players}
    ids = lambda names: frozenset(
        ids_by_name[name] for name in names if name in ids_by_name
    )
    exposure_limits = tuple(
        (ids_by_name[item["player"]], float(item["maximum_exposure"]))
        for item in settings.get("automatic_player_exposure_limits", ())
        if item.get("player") in ids_by_name
    )
    optimization_settings = ClassicOptimizationSettings(
        locked_player_ids=ids(settings.get("locked_players", ())),
        excluded_player_ids=ids(settings.get("excluded_players", ())),
        limited_player_ids=ids(settings.get("maximum_once_players", ())),
        player_exposure_limits=exposure_limits,
        maximum_fragile_players=settings.get("maximum_fragile_players_per_lineup"),
        qb_stack_size=1 if settings.get("require_qb_stack") else 0,
        require_opponent_bring_back=bool(settings.get("require_opponent_bring_back")),
        ceiling_weight=.3,
        ownership_penalty=float(settings.get("ownership_penalty") or 0),
        minimum_stack_projection=float(settings.get("minimum_stack_projection") or 0),
        minimum_bring_back_projection=float(
            settings.get("minimum_bring_back_projection") or 0
        ),
        minimum_stack_ceiling=12 if settings.get("require_qb_stack") else 0,
        minimum_bring_back_ceiling=(
            12 if settings.get("require_opponent_bring_back") else 0
        ),
        unique_primary_stacks=bool(settings.get("require_qb_stack")),
    )
    count = int(settings.get("lineups") or 1)
    include_ceiling = settings.get("ceiling_lineup_number") is not None
    weights = None
    if include_ceiling:
        weights = (
            (.15, .40, .70) if count == 3
            else (*([.3] * (count - 1)), .7)
        )
    return generate_classic_lineups(
        slate,
        match_projections(slate, projections),
        count,
        minimum_unique_players=int(settings.get("minimum_unique_players") or 1),
        settings=optimization_settings,
        maximum_player_exposure=float(settings.get("maximum_player_exposure") or 1),
        maximum_qb_exposure=float(settings.get("maximum_qb_exposure") or 1),
        maximum_dst_exposure=float(settings.get("maximum_dst_exposure") or 1),
        lineup_ceiling_weights=weights,
    )


def _read_projections(content: bytes) -> tuple[Projection, ...]:
    rows = csv.DictReader(io.StringIO(content.decode("utf-8-sig")))
    optional = lambda value: float(value) if value not in {None, ""} else None
    return tuple(Projection(
        row["name"], row["team"], float(row["projected_points"]),
        platform_id=row["platform_id"] or None,
        floor=optional(row.get("floor")), ceiling=optional(row.get("ceiling")),
        projected_ownership=optional(row.get("projected_ownership")),
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


def _read_lineups(content: bytes, platform: Platform) -> tuple[frozenset[str], ...]:
    rows = tuple(csv.reader(io.StringIO(content.decode("utf-8-sig"))))
    output = []
    for row in rows[1:]:
        if platform == Platform.DRAFTKINGS:
            output.append(frozenset(
                match.group(1) if (match := re.search(r"\(([^()]*)\)\s*$", value)) else value
                for value in row
            ))
        else:
            output.append(frozenset(row))
    return tuple(output)
