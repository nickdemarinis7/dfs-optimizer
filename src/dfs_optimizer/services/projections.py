from __future__ import annotations

import csv
import io
from dataclasses import replace
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import zipfile

from dfs_optimizer.data_sources.nflverse import download_nflverse_season
from dfs_optimizer.importers import (
    apply_ownership_csv,
    import_projections_csv,
    match_projections,
)
from dfs_optimizer.models import Projection, Slate
from dfs_optimizer.projections import (
    add_historical_ranges,
    apply_pregame_context,
    build_stat_based_projections,
    forecast_from_nflverse,
)


@dataclass(frozen=True, slots=True)
class HistoricalDataPaths:
    player_files: tuple[Path, ...]
    team_files: tuple[Path, ...]
    snap_files: tuple[Path, ...]
    games_file: Path

    @property
    def missing(self) -> tuple[Path, ...]:
        return tuple(
            path
            for path in (
                *self.player_files, *self.team_files, *self.snap_files,
                self.games_file,
            )
            if not path.is_file()
        )

    @property
    def age_hours(self) -> float | None:
        existing = tuple(
            path for path in (
                *self.player_files, *self.team_files, *self.snap_files,
                self.games_file,
            )
            if path.is_file()
        )
        expected = len(self.player_files) + len(self.team_files) + len(self.snap_files) + 1
        if len(existing) != expected:
            return None
        oldest_update = min(path.stat().st_mtime for path in existing)
        return max(
            0.0,
            (datetime.now(timezone.utc).timestamp() - oldest_update) / 3600,
        )


@dataclass(frozen=True, slots=True)
class HistoricalDataCoverage:
    stats_week: int | None
    snap_week: int | None


def historical_data_coverage(
    paths: HistoricalDataPaths, target_season: int
) -> HistoricalDataCoverage:
    """Report the newest regular-season week available to each model input."""
    def newest_week(files: tuple[Path, ...]) -> int | None:
        latest: int | None = None
        for path in files:
            if not path.is_file():
                continue
            with path.open(newline="", encoding="utf-8-sig") as handle:
                for row in csv.DictReader(handle):
                    try:
                        season = int(row.get("season", ""))
                        week = int(row.get("week", ""))
                    except (TypeError, ValueError):
                        continue
                    game_type = (row.get("season_type") or row.get("game_type") or "REG").upper()
                    if season == target_season and game_type == "REG":
                        latest = week if latest is None else max(latest, week)
        return latest

    return HistoricalDataCoverage(
        stats_week=newest_week(paths.player_files),
        snap_week=newest_week(paths.snap_files),
    )


def historical_data_paths(
    target_season: int,
    cache_dir: str | Path = "data/cache",
) -> HistoricalDataPaths:
    root = Path(cache_dir).expanduser()
    seasons = (target_season - 1, target_season)
    return HistoricalDataPaths(
        tuple(root / f"players_{season}.csv" for season in seasons),
        tuple(root / f"teams_{season}.csv" for season in seasons),
        tuple(root / f"snap_counts_{season}.csv" for season in seasons),
        root / "games.csv",
    )


def nfl_historical_input_snapshot(
    target_season: int,
    cache_dir: str | Path = "data/cache",
) -> bytes:
    """Package the exact local NFL model inputs used by a forecast.

    The source CSVs are already season-scoped (except the games schedule), and
    ZIP compression keeps the archived run reasonably small. Keeping the raw
    files—not only their hashes—lets a future model version rebuild the slate
    without silently substituting newer nflverse data.
    """
    paths = historical_data_paths(target_season, cache_dir)
    if paths.missing:
        missing = ", ".join(str(path) for path in paths.missing)
        raise FileNotFoundError(f"missing historical data files: {missing}")
    output = io.BytesIO()
    source_paths = (
        *paths.player_files,
        *paths.team_files,
        *paths.snap_files,
        paths.games_file,
    )
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in source_paths:
            archive.writestr(path.name, path.read_bytes())
    return output.getvalue()


def download_historical_data(
    target_season: int,
    cache_dir: str | Path = "data/cache",
) -> HistoricalDataPaths:
    for season in (target_season - 1, target_season):
        download_nflverse_season(season, cache_dir)
    return historical_data_paths(target_season, cache_dir)


def build_historical_projections(
    slate: Slate,
    target_season: int,
    target_week: int,
    cache_dir: str | Path = "data/cache",
) -> tuple[Projection, ...]:
    if target_week < 1:
        raise ValueError("target week must be at least 1")
    paths = historical_data_paths(target_season, cache_dir)
    if paths.missing:
        missing = ", ".join(str(path) for path in paths.missing)
        raise FileNotFoundError(f"missing historical data files: {missing}")
    offense, defenses = forecast_from_nflverse(
        slate,
        paths.player_files,
        paths.team_files,
        paths.games_file,
        target_season,
        target_week,
        snap_files=paths.snap_files,
    )
    offense, defenses = apply_pregame_context(
        slate,
        offense,
        defenses,
        paths.team_files,
        paths.games_file,
        target_season,
        target_week,
    )
    projections = build_stat_based_projections(slate, offense, defenses)
    projections = tuple(
        projection for projection in projections if projection.projected_points > 0
    )
    return add_historical_ranges(
        slate,
        projections,
        paths.player_files,
        paths.team_files,
        paths.games_file,
        target_season,
        target_week,
        snap_files=paths.snap_files,
    )


def apply_uploaded_ownership(
    slate: Slate,
    projections: tuple[Projection, ...],
    filename: str,
    content: bytes,
) -> tuple[tuple[Projection, ...], int]:
    suffix = Path(filename).suffix or ".csv"
    with tempfile.NamedTemporaryFile(suffix=suffix) as handle:
        handle.write(content)
        handle.flush()
        return apply_ownership_csv(slate, projections, handle.name)


def apply_uploaded_projection_consensus(
    slate: Slate,
    projections: tuple[Projection, ...],
    filename: str,
    content: bytes,
    *,
    external_weight: float = .35,
) -> tuple[tuple[Projection, ...], int]:
    """Blend a trusted external median into the internal forecast.

    The internal model remains the majority input and retains ownership,
    sample, confidence, and opportunity metadata. External values are capped
    to 60%-140% of the internal median before blending so a bad row or stale
    provider value cannot dominate a lineup.
    """
    if not 0 <= external_weight <= .5:
        raise ValueError("external projection weight must be between 0 and 0.5")
    suffix = Path(filename).suffix or ".csv"
    with tempfile.NamedTemporaryFile(suffix=suffix) as handle:
        handle.write(content)
        handle.flush()
        imported = import_projections_csv(handle.name)
    matches = match_projections(slate, imported).by_player_id
    output = []
    matched = 0
    for projection in projections:
        external = matches.get(projection.platform_id or "")
        if external is None or external.projected_points <= 0:
            output.append(projection)
            continue
        baseline = projection.projected_points
        if baseline <= 0:
            output.append(projection)
            continue
        bounded_external = min(baseline * 1.4, max(baseline * .6, external.projected_points))
        blended = baseline * (1 - external_weight) + bounded_external * external_weight
        factor = blended / baseline
        scale = lambda value: value * factor if value is not None else None
        output.append(replace(
            projection,
            projected_points=blended,
            floor=scale(projection.floor),
            ceiling=scale(projection.ceiling),
            p10=scale(projection.p10),
            p25=scale(projection.p25),
            p75=scale(projection.p75),
            p90=scale(projection.p90),
        ))
        matched += 1
    return tuple(output), matched
