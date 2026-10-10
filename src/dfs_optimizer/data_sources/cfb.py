from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import requests


CFB_PLAYER_STATS_URL = (
    "https://raw.githubusercontent.com/sportsdataverse/cfbfastR-data/"
    "main/player_stats/csv/player_stats_{season}.csv"
)


def download_cfb_player_stats(
    season: int,
    cache_dir: str | Path = "data/cache/cfb",
    *,
    refresh: bool = False,
    max_age_hours: float = 6,
) -> Path:
    """Download the current cfbfastR play-level player statistics."""
    destination = Path(cache_dir).expanduser()
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / f"player_stats_{season}.csv"
    fresh = False
    if target.is_file() and not refresh:
        age = datetime.now(timezone.utc).timestamp() - target.stat().st_mtime
        fresh = age <= max_age_hours * 3600
    if fresh:
        return target

    temporary = target.with_suffix(".csv.tmp")
    try:
        with requests.get(
            CFB_PLAYER_STATS_URL.format(season=season),
            timeout=120,
            stream=True,
        ) as response:
            response.raise_for_status()
            with temporary.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        handle.write(chunk)
        temporary.replace(target)
    except (OSError, requests.RequestException) as exc:
        temporary.unlink(missing_ok=True)
        if target.is_file():
            return target
        raise OSError(f"could not download CFB player history: {exc}") from exc
    return target
