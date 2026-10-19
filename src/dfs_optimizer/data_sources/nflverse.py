from __future__ import annotations

from pathlib import Path

import requests


PLAYER_URL = "https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_{season}.csv"
TEAM_URL = "https://github.com/nflverse/nflverse-data/releases/download/stats_team/stats_team_week_{season}.csv"
GAMES_URL = "https://github.com/nflverse/nfldata/raw/master/data/games.csv"
SNAP_COUNTS_URL = (
    "https://github.com/nflverse/nflverse-data/releases/download/"
    "snap_counts/snap_counts_{season}.csv"
)
DEPTH_CHARTS_URL = (
    "https://github.com/nflverse/nflverse-data/releases/download/"
    "depth_charts/depth_charts_{season}.csv"
)
INJURIES_URL = (
    "https://github.com/nflverse/nflverse-data/releases/download/"
    "injuries/injuries_{season}.csv"
)


def download_nflverse_season(season: int, cache_dir: str | Path) -> dict[str, Path]:
    """Download nflverse inputs into a local, git-ignored cache."""
    destination = Path(cache_dir)
    destination.mkdir(parents=True, exist_ok=True)
    targets = {
        "players": (PLAYER_URL.format(season=season), destination / f"players_{season}.csv"),
        "teams": (TEAM_URL.format(season=season), destination / f"teams_{season}.csv"),
        "snaps": (
            SNAP_COUNTS_URL.format(season=season),
            destination / f"snap_counts_{season}.csv",
        ),
        "games": (GAMES_URL, destination / "games.csv"),
    }
    for url, path in targets.values():
        try:
            response = requests.get(url, timeout=60)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise OSError(f"could not download nflverse season data: {exc}") from exc
        path.write_bytes(response.content)
    return {name: path for name, (_, path) in targets.items()}


def download_nflverse_current_context(
    season: int, cache_dir: str | Path
) -> dict[str, Path]:
    """Download current depth charts and official weekly injury reports."""
    destination = Path(cache_dir)
    destination.mkdir(parents=True, exist_ok=True)
    targets = {
        "depth_charts": (
            DEPTH_CHARTS_URL.format(season=season),
            destination / f"depth_charts_{season}.csv",
        ),
        "injuries": (
            INJURIES_URL.format(season=season),
            destination / f"injuries_{season}.csv",
        ),
    }
    for url, path in targets.values():
        try:
            response = requests.get(url, timeout=60)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise OSError(f"could not download current nflverse context: {exc}") from exc
        path.write_bytes(response.content)
    return {name: path for name, (_, path) in targets.items()}
