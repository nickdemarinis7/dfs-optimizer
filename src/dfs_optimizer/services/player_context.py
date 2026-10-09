from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata

from dfs_optimizer.data_sources import load_sleeper_players
from dfs_optimizer.models import Slate


TEAM_ALIASES = {"JAC": "JAX", "LAR": "LA"}


@dataclass(frozen=True, slots=True)
class PlayerContext:
    platform_id: str
    depth_chart_position: int | None
    injury_status: str | None
    practice_participation: str | None
    active: bool | None

    @property
    def role_label(self) -> str:
        if self.injury_status:
            return self.injury_status
        if self.depth_chart_position:
            return f"Depth {self.depth_chart_position}"
        return "Active" if self.active else "Unknown"


def fetch_player_context(
    slate: Slate,
    cache_dir: str = "data/cache",
    *,
    refresh: bool = False,
) -> tuple[PlayerContext, ...]:
    return match_player_context(
        slate, load_sleeper_players(cache_dir, refresh=refresh)
    )


def match_player_context(
    slate: Slate,
    sleeper_players: dict[str, dict],
) -> tuple[PlayerContext, ...]:
    by_key: dict[tuple[str, str], list[dict]] = {}
    for record in sleeper_players.values():
        if not isinstance(record, dict):
            continue
        name = record.get("full_name") or " ".join(filter(None, (
            record.get("first_name"), record.get("last_name")
        )))
        team = TEAM_ALIASES.get(str(record.get("team") or "").upper(), str(record.get("team") or "").upper())
        if name and team:
            by_key.setdefault((_normalize(name), team), []).append(record)

    contexts = []
    for player in slate.players:
        team = TEAM_ALIASES.get(player.team, player.team)
        candidates = by_key.get((_normalize(player.name), team), ())
        if len(candidates) != 1:
            continue
        record = candidates[0]
        depth = record.get("depth_chart_position")
        try:
            depth = int(depth) if depth not in (None, "") else None
        except (TypeError, ValueError):
            depth = None
        contexts.append(PlayerContext(
            platform_id=player.platform_id,
            depth_chart_position=depth,
            injury_status=_text(record.get("injury_status")),
            practice_participation=_text(record.get("practice_participation")),
            active=record.get("active") if isinstance(record.get("active"), bool) else None,
        ))
    return tuple(contexts)


def _normalize(value: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    normalized = re.sub(r"[^a-z0-9]", "", ascii_name.casefold())
    return re.sub(r"(?:jr|sr|ii|iii|iv)$", "", normalized)


def _text(value) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None
