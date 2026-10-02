from __future__ import annotations

from pathlib import Path

import requests


PLAYER_URL = "https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_{season}.csv"
TEAM_URL = "https://github.com/nflverse/nflverse-data/releases/download/stats_team/stats_team_week_{season}.csv"
GAMES_URL = "https://github.com/nflverse/nfldata/raw/master/data/games.csv"


def download_nflverse_season(season: int, cache_dir: str | Path) -> dict[str, Path]:
    """Download nflverse inputs into a local, git-ignored cache."""
    destination = Path(cache_dir)
    destination.mkdir(parents=True, exist_ok=True)
    targets = {
        "players": (PLAYER_URL.format(season=season), destination / f"players_{season}.csv"),
        "teams": (TEAM_URL.format(season=season), destination / f"teams_{season}.csv"),
        "games": (GAMES_URL, destination / "games.csv"),
    }
    for url, path in targets.values():
        response = requests.get(url, timeout=60)
        response.raise_for_status()
        path.write_bytes(response.content)
    return {name: path for name, (_, path) in targets.items()}
