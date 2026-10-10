from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
import unicodedata
from zoneinfo import ZoneInfo

from dfs_optimizer.data_sources import load_sleeper_players
from dfs_optimizer.models import Position, Slate


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


@dataclass(frozen=True, slots=True)
class PrelockSummary:
    unmatched_player_ids: frozenset[str]
    questionable_player_ids: frozenset[str]
    unavailable_player_ids: frozenset[str]
    backup_quarterback_ids: frozenset[str]
    games_starting_soon: tuple[str, ...]
    started_games: tuple[str, ...]
    timed_games: int
    total_games: int


def fetch_player_context(
    slate: Slate,
    cache_dir: str = "data/cache",
    *,
    refresh: bool = False,
    max_age_hours: float = 12,
) -> tuple[PlayerContext, ...]:
    return match_player_context(
        slate,
        load_sleeper_players(
            cache_dir, refresh=refresh, max_age_hours=max_age_hours
        ),
    )


def summarize_prelock_context(
    slate: Slate,
    contexts: tuple[PlayerContext, ...],
    *,
    now: datetime | None = None,
    soon_hours: float = 3,
) -> PrelockSummary:
    """Summarize live role and slate-time risks for the final review screen."""
    context_by_id = {item.platform_id: item for item in contexts}
    relevant_ids = {
        player.platform_id
        for player in slate.players
        if player.primary_position != Position.DST
    }
    unavailable_statuses = {"IR", "O", "OUT", "INJURED RESERVE", "INACTIVE"}
    questionable_statuses = {"Q", "QUESTIONABLE", "D", "DOUBTFUL"}
    limited_practice = {"DNP", "DID NOT PARTICIPATE", "LIMITED", "LIMITED PARTICIPATION"}

    unavailable = set()
    questionable = set()
    backups = set()
    for player in slate.players:
        context = context_by_id.get(player.platform_id)
        salary_status = (player.status or "").strip().upper()
        injury_status = (context.injury_status or "").strip().upper() if context else ""
        practice = (
            (context.practice_participation or "").strip().upper()
            if context else ""
        )
        if (
            salary_status in unavailable_statuses
            or injury_status in unavailable_statuses
            or (context is not None and context.active is False)
        ):
            unavailable.add(player.platform_id)
        elif (
            salary_status in questionable_statuses
            or injury_status in questionable_statuses
            or practice in limited_practice
        ):
            questionable.add(player.platform_id)
        if (
            player.primary_position == Position.QB
            and context is not None
            and (context.depth_chart_position or 1) > 1
        ):
            backups.add(player.platform_id)

    current_time = now or datetime.now(timezone.utc)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    starts = {
        game: start
        for game in slate.games
        if (start := _game_start(game)) is not None
    }
    soon = tuple(sorted(
        game for game, start in starts.items()
        if 0 <= (start - current_time).total_seconds() <= soon_hours * 3600
    ))
    started = tuple(sorted(
        game for game, start in starts.items()
        if start < current_time
    ))
    return PrelockSummary(
        unmatched_player_ids=frozenset(relevant_ids - context_by_id.keys()),
        questionable_player_ids=frozenset(questionable),
        unavailable_player_ids=frozenset(unavailable),
        backup_quarterback_ids=frozenset(backups),
        games_starting_soon=soon,
        started_games=started,
        timed_games=len(starts),
        total_games=len(slate.games),
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


def _game_start(value: str) -> datetime | None:
    match = re.search(
        r"\b(\d{2}/\d{2}/\d{4})\s+(\d{1,2}:\d{2}(?:AM|PM))\s+ET\b",
        value,
        re.IGNORECASE,
    )
    if not match:
        return None
    local = datetime.strptime(
        f"{match.group(1)} {match.group(2).upper()}", "%m/%d/%Y %I:%M%p"
    )
    return local.replace(tzinfo=ZoneInfo("America/New_York")).astimezone(timezone.utc)
