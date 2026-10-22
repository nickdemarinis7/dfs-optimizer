from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
import csv
import io
import json
import re
import unicodedata
from zoneinfo import ZoneInfo

from dfs_optimizer.data_sources.sleeper import load_sleeper_players
from dfs_optimizer.data_sources.nflverse import download_nflverse_current_context
from dfs_optimizer.models import Position, Slate


TEAM_ALIASES = {"JAC": "JAX", "LAR": "LA"}


@dataclass(frozen=True, slots=True)
class PlayerContext:
    platform_id: str
    depth_chart_position: int | None
    injury_status: str | None
    practice_participation: str | None
    active: bool | None
    verified_projection: float | None = None
    expected_role: str | None = None
    role_note: str | None = None
    injury_reported: bool = False

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
    subordinate_skill_player_ids: frozenset[str]
    games_starting_soon: tuple[str, ...]
    started_games: tuple[str, ...]
    timed_games: int
    total_games: int


def verified_player_context_ids(
    contexts: tuple[PlayerContext, ...],
) -> frozenset[str]:
    """Return players whose context row contains an actual pre-lock signal.

    A name/team match with every optional field blank is not verification. This
    prevents a blank bulk upload from reporting full context coverage.
    """
    return frozenset(
        item.platform_id
        for item in contexts
        if item.active is not None
        or item.depth_chart_position is not None
        or bool((item.injury_status or "").strip())
        or bool((item.practice_participation or "").strip())
        or item.injury_reported
        or item.verified_projection is not None
        or bool((item.expected_role or "").strip())
    )


def unverified_selected_player_ids(
    selected_player_ids,
    contexts: tuple[PlayerContext, ...],
    acknowledged_player_ids=frozenset(),
) -> frozenset[str]:
    """Return selected players lacking context and an explicit manual check."""
    return (
        frozenset(selected_player_ids)
        - verified_player_context_ids(contexts)
        - frozenset(acknowledged_player_ids)
    )


def fetch_player_context(
    slate: Slate,
    cache_dir: str = "data/cache",
    *,
    refresh: bool = False,
    max_age_hours: float = 12,
    season: int | None = None,
) -> tuple[PlayerContext, ...]:
    sleeper_context = match_player_context(
        slate,
        load_sleeper_players(
            cache_dir, refresh=refresh, max_age_hours=max_age_hours
        ),
    )
    current_season = season or (
        date.today().year if date.today().month >= 3 else date.today().year - 1
    )
    try:
        paths = _current_nflverse_context_paths(
            current_season, cache_dir, refresh=refresh, max_age_hours=max_age_hours
        )
        nflverse_context = match_nflverse_player_context(
            slate, paths["depth_charts"], paths["injuries"]
        )
    except (OSError, ValueError):
        return sleeper_context
    return merge_player_context_sources(sleeper_context, nflverse_context)


def merge_player_context_sources(
    primary: tuple[PlayerContext, ...],
    secondary: tuple[PlayerContext, ...],
) -> tuple[PlayerContext, ...]:
    """Merge current sources while preserving manual-only context fields."""
    merged = {item.platform_id: item for item in primary}
    for item in secondary:
        current = merged.get(item.platform_id)
        if current is None:
            merged[item.platform_id] = item
            continue
        merged[item.platform_id] = PlayerContext(
            item.platform_id,
            item.depth_chart_position or current.depth_chart_position,
            item.injury_status if item.injury_reported else current.injury_status,
            (
                item.practice_participation
                if item.injury_reported
                else current.practice_participation
            ),
            current.active if current.active is not None else item.active,
            current.verified_projection,
            current.expected_role,
            current.role_note,
            current.injury_reported or item.injury_reported,
        )
    return tuple(merged.values())


def apply_final_status_overrides(
    contexts: tuple[PlayerContext, ...],
    final_statuses: tuple[PlayerContext, ...],
) -> tuple[PlayerContext, ...]:
    """Apply an official active/inactive list as the authoritative status layer.

    Final game status supersedes stale salary-file and practice designations,
    while depth, projections, and manually recorded workload reports remain
    intact.
    """
    merged = {item.platform_id: item for item in contexts}
    for final in final_statuses:
        current = merged.get(final.platform_id)
        if current is None:
            merged[final.platform_id] = final
            continue
        merged[final.platform_id] = replace_player_context_status(current, final)
    return tuple(merged.values())


def replace_player_context_status(
    current: PlayerContext, final: PlayerContext
) -> PlayerContext:
    return PlayerContext(
        platform_id=current.platform_id,
        depth_chart_position=current.depth_chart_position,
        injury_status=final.injury_status,
        practice_participation=current.practice_participation,
        active=final.active,
        verified_projection=current.verified_projection,
        expected_role=current.expected_role,
        role_note=current.role_note,
        injury_reported=True,
    )


def import_final_status_csv(
    slate: Slate, content: bytes | str
) -> tuple[PlayerContext, ...]:
    """Import an official final active/inactive report for the current slate."""
    text = content.decode("utf-8-sig") if isinstance(content, bytes) else content
    reader = csv.DictReader(io.StringIO(text))
    fields = {field.strip().casefold() for field in (reader.fieldnames or ())}
    missing = {"name", "team", "final_status"} - fields
    if missing:
        raise ValueError(
            "final-status CSV is missing columns: " + ", ".join(sorted(missing))
        )
    players_by_key: dict[tuple[str, str], list] = {}
    for player in slate.players:
        players_by_key.setdefault(
            (_normalize(player.name), player.team.strip().upper()), []
        ).append(player)

    contexts = []
    seen_ids: set[str] = set()
    unmatched: list[str] = []
    allowed = {"ACTIVE", "INACTIVE", "OUT"}
    for row_number, raw_row in enumerate(reader, start=2):
        row = {
            str(key).strip().casefold(): value
            for key, value in raw_row.items() if key is not None
        }
        name = _text(row.get("name"))
        team = (_text(row.get("team")) or "").upper()
        status = (_text(row.get("final_status")) or "").upper()
        if not status:
            continue
        if not name or not team:
            raise ValueError(f"final-status row {row_number} needs name and team")
        if status not in allowed:
            raise ValueError(
                f"final-status row {row_number} must be ACTIVE, INACTIVE, OUT, or blank"
            )
        candidates = players_by_key.get((_normalize(name), team), ())
        if len(candidates) != 1:
            unmatched.append(f"{name} ({team})")
            continue
        player = candidates[0]
        if player.platform_id in seen_ids:
            raise ValueError(f"final-status CSV contains duplicate player {name}")
        seen_ids.add(player.platform_id)
        contexts.append(PlayerContext(
            platform_id=player.platform_id,
            depth_chart_position=None,
            injury_status=status,
            practice_participation=None,
            active=status == "ACTIVE",
            injury_reported=True,
        ))
    if unmatched:
        preview = ", ".join(unmatched[:5])
        remainder = len(unmatched) - 5
        raise ValueError(
            "final-status rows did not match the slate: " + preview
            + (f" and {remainder} more" if remainder > 0 else "")
        )
    if not contexts:
        raise ValueError("final-status CSV did not contain any completed statuses")
    return tuple(contexts)


def final_status_csv_template(slate: Slate) -> bytes:
    """Return a compact final-status template for every player on the slate."""
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(("name", "team", "final_status"))
    for player in sorted(slate.players, key=lambda item: (item.team, item.name)):
        writer.writerow((player.name, player.team, ""))
    return output.getvalue().encode()


def player_context_snapshot(
    contexts: tuple[PlayerContext, ...], *, source: str | None, checked_at: datetime | None
) -> bytes:
    """Serialize the exact context layer used by a run for later replay/audit."""
    payload = {
        "source": source,
        "checked_at": checked_at.isoformat() if checked_at else None,
        "players": [
            {
                "platform_id": item.platform_id,
                "depth_chart_position": item.depth_chart_position,
                "injury_status": item.injury_status,
                "practice_participation": item.practice_participation,
                "active": item.active,
                "verified_projection": item.verified_projection,
                "expected_role": item.expected_role,
                "role_note": item.role_note,
                "injury_reported": item.injury_reported,
            }
            for item in contexts
        ],
    }
    return json.dumps(payload, indent=2, sort_keys=True).encode()


def match_nflverse_player_context(
    slate: Slate, depth_path: str | Path, injury_path: str | Path
) -> tuple[PlayerContext, ...]:
    """Match the freshest free nflverse depth and injury records to a slate."""
    players_by_key = {
        (_normalize(player.name), TEAM_ALIASES.get(player.team, player.team)): player
        for player in slate.players
    }
    depth_rows: dict[tuple[str, str], tuple[str, int]] = {}
    with Path(depth_path).open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            key = (
                _normalize(row.get("player_name") or ""),
                TEAM_ALIASES.get((row.get("team") or "").upper(), (row.get("team") or "").upper()),
            )
            try:
                rank = int(float(row.get("pos_rank") or ""))
            except ValueError:
                continue
            timestamp = row.get("dt") or ""
            if key in players_by_key and (key not in depth_rows or timestamp >= depth_rows[key][0]):
                depth_rows[key] = (timestamp, rank)

    injury_rows: dict[tuple[str, str], tuple[int, str, str | None, str | None]] = {}
    with Path(injury_path).open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            key = (
                _normalize(row.get("full_name") or ""),
                TEAM_ALIASES.get((row.get("team") or "").upper(), (row.get("team") or "").upper()),
            )
            try:
                week = int(row.get("week") or 0)
            except ValueError:
                continue
            candidate = (
                week,
                row.get("date_modified") or "",
                _text(row.get("report_status")),
                _text(row.get("practice_status")),
            )
            if key in players_by_key and (
                key not in injury_rows or candidate[:2] >= injury_rows[key][:2]
            ):
                injury_rows[key] = candidate

    contexts = []
    for key, player in players_by_key.items():
        depth = depth_rows.get(key)
        injury = injury_rows.get(key)
        if depth is None and injury is None:
            continue
        contexts.append(PlayerContext(
            player.platform_id,
            depth[1] if depth else None,
            injury[2] if injury else None,
            injury[3] if injury else None,
            None,
            injury_reported=injury is not None,
        ))
    return tuple(contexts)


def _current_nflverse_context_paths(
    season: int,
    cache_dir: str | Path,
    *,
    refresh: bool,
    max_age_hours: float,
) -> dict[str, Path]:
    root = Path(cache_dir)
    paths = {
        "depth_charts": root / f"depth_charts_{season}.csv",
        "injuries": root / f"injuries_{season}.csv",
    }
    now = datetime.now(timezone.utc).timestamp()
    stale = any(
        not path.is_file() or (now - path.stat().st_mtime) / 3600 > max_age_hours
        for path in paths.values()
    )
    return download_nflverse_current_context(season, cache_dir) if refresh or stale else paths


def import_player_context_csv(
    slate: Slate, content: bytes | str
) -> tuple[PlayerContext, ...]:
    """Import a pre-lock availability/depth-chart snapshot.

    Required columns are ``name`` and ``team``. Optional columns are
    ``status``, ``depth_chart_position``, ``active``, and
    ``practice_participation``, ``verified_projection``, ``expected_role``, and
    ``role_note``. Expected role may be ``expanded``, ``normal``, ``committee``,
    or ``limited``. Rows must match exactly one slate player so a
    similarly named player cannot silently receive somebody else's status.
    """
    text = content.decode("utf-8-sig") if isinstance(content, bytes) else content
    reader = csv.DictReader(io.StringIO(text))
    fields = {field.strip().casefold() for field in (reader.fieldnames or ())}
    missing = {"name", "team"} - fields
    if missing:
        raise ValueError(
            "player-context CSV is missing columns: " + ", ".join(sorted(missing))
        )
    players_by_key: dict[tuple[str, str], list] = {}
    for player in slate.players:
        players_by_key.setdefault(
            (_normalize(player.name), player.team.strip().upper()), []
        ).append(player)

    contexts = []
    seen_ids: set[str] = set()
    unmatched: list[str] = []
    for row_number, raw_row in enumerate(reader, start=2):
        row = {
            str(key).strip().casefold(): value
            for key, value in raw_row.items() if key is not None
        }
        name = _text(row.get("name"))
        team = (_text(row.get("team")) or "").upper()
        if not name or not team:
            raise ValueError(f"player-context row {row_number} needs name and team")
        candidates = players_by_key.get((_normalize(name), team), ())
        if len(candidates) != 1:
            unmatched.append(f"{name} ({team})")
            continue
        player = candidates[0]
        if player.platform_id in seen_ids:
            raise ValueError(f"player-context CSV contains duplicate player {name}")
        seen_ids.add(player.platform_id)
        depth_text = _text(row.get("depth_chart_position"))
        try:
            depth = int(depth_text) if depth_text else None
        except ValueError as exc:
            raise ValueError(
                f"player-context row {row_number} has an invalid depth position"
            ) from exc
        if depth is not None and depth < 1:
            raise ValueError(
                f"player-context row {row_number} depth position must be at least 1"
            )
        active = _optional_bool(row.get("active"), row_number)
        projection_text = _text(row.get("verified_projection"))
        try:
            verified_projection = (
                float(projection_text) if projection_text else None
            )
        except ValueError as exc:
            raise ValueError(
                f"player-context row {row_number} has an invalid verified projection"
            ) from exc
        if verified_projection is not None and verified_projection <= 0:
            raise ValueError(
                f"player-context row {row_number} verified projection must be positive"
            )
        expected_role = (_text(row.get("expected_role")) or "").casefold() or None
        if expected_role not in {None, "expanded", "normal", "committee", "limited"}:
            raise ValueError(
                f"player-context row {row_number} expected role must be expanded, "
                "normal, committee, limited, or blank"
            )
        contexts.append(PlayerContext(
            platform_id=player.platform_id,
            depth_chart_position=depth,
            injury_status=_text(row.get("status")),
            practice_participation=_text(row.get("practice_participation")),
            active=active,
            verified_projection=verified_projection,
            expected_role=expected_role,
            role_note=_text(row.get("role_note")),
            injury_reported=bool(
                _text(row.get("status"))
                or _text(row.get("practice_participation"))
            ),
        ))
    if unmatched:
        preview = ", ".join(unmatched[:5])
        remainder = len(unmatched) - 5
        raise ValueError(
            "player-context rows did not match the slate: " + preview
            + (f" and {remainder} more" if remainder > 0 else "")
        )
    if not contexts:
        raise ValueError("player-context CSV did not contain any matched players")
    return tuple(contexts)


def player_context_csv_template(slate: Slate) -> bytes:
    """Return an editable pre-lock context template for the current slate."""
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow((
        "name", "team", "status", "depth_chart_position", "active",
        "practice_participation",
        "verified_projection",
        "expected_role",
        "role_note",
    ))
    for player in sorted(slate.players, key=lambda item: (item.team, item.name)):
        writer.writerow((
            player.name, player.team, player.status or "", "", "", "", "", "", "",
        ))
    return output.getvalue().encode()


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
    subordinate_skill_players = set()
    for player in slate.players:
        context = context_by_id.get(player.platform_id)
        salary_status = (player.status or "").strip().upper()
        injury_status = (context.injury_status or "").strip().upper() if context else ""
        practice = (
            (context.practice_participation or "").strip().upper()
            if context else ""
        )
        final_status_reported = injury_status in {"ACTIVE", "INACTIVE", "OUT"}
        if (
            (not final_status_reported and salary_status in unavailable_statuses)
            or injury_status in unavailable_statuses
            or (context is not None and context.active is False)
        ):
            unavailable.add(player.platform_id)
        elif (
            (not final_status_reported and salary_status in questionable_statuses)
            or injury_status in questionable_statuses
            or (not final_status_reported and practice in limited_practice)
        ):
            questionable.add(player.platform_id)
        if context is not None and (
            (
                player.primary_position == Position.TE
                and (context.depth_chart_position or 0) >= 2
            )
            or (
                player.primary_position in {Position.RB, Position.WR}
                and (context.depth_chart_position or 0) >= 3
            )
        ):
            subordinate_skill_players.add(player.platform_id)

    available_qb1_teams = {
        player.team
        for player in slate.players
        if player.primary_position == Position.QB
        and player.platform_id not in unavailable
        and (context := context_by_id.get(player.platform_id)) is not None
        and context.depth_chart_position == 1
    }
    backups = {
        player.platform_id
        for player in slate.players
        if player.primary_position == Position.QB
        and player.team in available_qb1_teams
        and player.platform_id not in unavailable
        and (context := context_by_id.get(player.platform_id)) is not None
        and (context.depth_chart_position or 1) > 1
    }

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
        subordinate_skill_player_ids=frozenset(subordinate_skill_players),
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
        # Sleeper's depth_chart_position is the position label (for example,
        # "TE"). depth_chart_order is the actual 1/2/3 role rank.
        depth = record.get("depth_chart_order")
        if depth in (None, ""):
            # Retain compatibility with older/captured payloads that used the
            # position field for a numeric order.
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
            injury_reported=bool(
                _text(record.get("injury_status"))
                or _text(record.get("practice_participation"))
            ),
        ))
    return tuple(contexts)


def _normalize(value: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    normalized = re.sub(r"[^a-z0-9]", "", ascii_name.casefold())
    return re.sub(r"(?:jr|sr|ii|iii|iv)$", "", normalized)


def _text(value) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _optional_bool(value, row_number: int) -> bool | None:
    text = (_text(value) or "").casefold()
    if not text:
        return None
    if text in {"true", "yes", "y", "1", "active", "available"}:
        return True
    if text in {"false", "no", "n", "0", "inactive", "unavailable"}:
        return False
    raise ValueError(
        f"player-context row {row_number} active must be true, false, or blank"
    )


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
