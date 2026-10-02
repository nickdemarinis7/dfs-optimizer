from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tempfile

from dfs_optimizer.data_sources import download_nflverse_season
from dfs_optimizer.importers import apply_ownership_csv
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
    games_file: Path

    @property
    def missing(self) -> tuple[Path, ...]:
        return tuple(
            path
            for path in (*self.player_files, *self.team_files, self.games_file)
            if not path.is_file()
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
        root / "games.csv",
    )


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
