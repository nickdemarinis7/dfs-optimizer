from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import requests


SLEEPER_PLAYERS_URL = "https://api.sleeper.app/v1/players/nfl?active=true"


def load_sleeper_players(
    cache_dir: str | Path = "data/cache",
    *,
    refresh: bool = False,
    max_age_hours: float = 12,
) -> dict[str, dict]:
    """Return the current Sleeper NFL player map with a bounded disk cache."""
    destination = Path(cache_dir).expanduser()
    destination.mkdir(parents=True, exist_ok=True)
    cache_file = destination / "sleeper_players.json"
    fresh = False
    if cache_file.is_file() and not refresh:
        age = datetime.now(timezone.utc).timestamp() - cache_file.stat().st_mtime
        fresh = age <= max_age_hours * 3600
    if not fresh:
        try:
            response = requests.get(SLEEPER_PLAYERS_URL, timeout=60)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise OSError(f"could not refresh current player context: {exc}") from exc
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("Sleeper player response was not an object")
        temporary = cache_file.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(payload), encoding="utf-8")
        temporary.replace(cache_file)
    payload = json.loads(cache_file.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("cached Sleeper player data was not an object")
    return payload
