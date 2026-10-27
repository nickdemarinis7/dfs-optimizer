from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
import csv
import io
import json
import math
from zoneinfo import ZoneInfo

from dfs_optimizer.data_sources.nfl_weather import fetch_nws_hourly_forecast
from dfs_optimizer.models import Slate
from .player_context import PlayerContext


TEAM_ALIASES = {"JAC": "JAX", "LA": "LAR", "WSH": "WAS"}

# Approximate home-stadium coordinates are sufficient for a travel-load signal;
# they are not used for navigation or for precise weather station selection.
TEAM_COORDINATES = {
    "ARI": (33.53, -112.26), "ATL": (33.76, -84.40), "BAL": (39.28, -76.62),
    "BUF": (42.77, -78.79), "CAR": (35.23, -80.85), "CHI": (41.86, -87.62),
    "CIN": (39.10, -84.52), "CLE": (41.51, -81.70), "DAL": (32.75, -97.09),
    "DEN": (39.74, -105.02), "DET": (42.34, -83.05), "GB": (44.50, -88.06),
    "HOU": (29.68, -95.41), "IND": (39.76, -86.16), "JAX": (30.32, -81.64),
    "KC": (39.05, -94.48), "LAC": (33.95, -118.34), "LAR": (33.95, -118.34),
    "LV": (36.09, -115.18), "MIA": (25.96, -80.24), "MIN": (44.97, -93.26),
    "NE": (42.09, -71.26), "NO": (29.95, -90.08), "NYG": (40.81, -74.07),
    "NYJ": (40.81, -74.07), "PHI": (39.90, -75.17), "PIT": (40.45, -80.02),
    "SEA": (47.60, -122.33), "SF": (37.40, -121.97), "TB": (27.98, -82.50),
    "TEN": (36.17, -86.77), "WAS": (38.91, -76.86),
}


@dataclass(frozen=True, slots=True)
class TeamWeeklyContext:
    team: str
    opponent: str
    game: str
    rest_days: int | None
    short_week: bool
    post_bye: bool
    travel_miles: int
    roof: str | None
    temperature_f: float | None
    wind_mph: float | None
    practice_counts: tuple[tuple[str, int], ...]
    defensive_absences: tuple[str, ...]
    notes: tuple[str, ...]
    home_team: str | None = None
    kickoff_utc: datetime | None = None
    precipitation_probability: float | None = None
    weather_summary: str | None = None
    weather_source: str | None = None


@dataclass(frozen=True, slots=True)
class CoachSignal:
    player: str
    team: str
    signal: str
    confidence: str
    speaker: str | None = None
    published_at: str | None = None
    source_url: str | None = None
    note: str | None = None


@dataclass(frozen=True, slots=True)
class PracticeTrajectory:
    platform_id: str
    name: str
    team: str
    observations: tuple[str, ...]
    latest: str
    improving: bool


def build_weekly_context(
    slate: Slate,
    season: int,
    week: int,
    cache_dir: str | Path = "data/cache",
) -> tuple[TeamWeeklyContext, ...]:
    root = Path(cache_dir).expanduser()
    games = _read_csv(root / "games.csv")
    injuries = _read_csv(root / f"injuries_{season}.csv")
    game_rows = {
        frozenset((_team(row.get("away_team")), _team(row.get("home_team")))): row
        for row in games
        if _integer(row.get("season")) == season and _integer(row.get("week")) == week
    }
    injury_rows = [
        row for row in injuries
        if _integer(row.get("season")) == season and _integer(row.get("week")) == week
    ]
    results = []
    for team in sorted(slate.teams):
        players = [player for player in slate.players if player.team == team]
        if not players:
            continue
        opponent = players[0].opponent
        row = game_rows.get(frozenset((_team(team), _team(opponent))), {})
        away = _team(row.get("away_team"))
        home = _team(row.get("home_team"))
        is_away = _team(team) == away
        rest = _integer(row.get("away_rest" if is_away else "home_rest"))
        travel = _travel_miles(team, home) if is_away and home else 0
        team_injuries = [item for item in injury_rows if _team(item.get("team")) == _team(team)]
        opponent_injuries = [
            item for item in injury_rows if _team(item.get("team")) == _team(opponent)
        ]
        practice = {}
        for item in team_injuries:
            status = _practice_label(item.get("practice_status"))
            if status:
                practice[status] = practice.get(status, 0) + 1
        defensive_absences = tuple(sorted(
            item.get("full_name", "").strip()
            for item in opponent_injuries
            if item.get("position", "").upper() in {"CB", "DB", "S", "FS", "SS", "DE", "DL", "DT", "LB"}
            and _is_limited_or_out(item)
            and item.get("full_name", "").strip()
        ))
        roof = (row.get("roof") or "").strip() or None
        kickoff = _kickoff_utc(row.get("gameday"), row.get("gametime"))
        temperature = _number(row.get("temp"))
        wind = _number(row.get("wind"))
        notes = []
        if rest is not None and rest <= 6:
            notes.append(f"Short week ({rest} days rest)")
        if rest is not None and rest >= 10:
            notes.append(f"Extended rest / post-bye ({rest} days)")
        if travel >= 1500:
            notes.append(f"Long trip (~{travel:,} miles)")
        if roof and roof.lower() not in {"dome", "closed"} and wind is not None and wind >= 15:
            notes.append(f"Wind watch ({wind:.0f} mph)")
        if defensive_absences:
            notes.append(f"Opponent defensive injury watch: {len(defensive_absences)}")
        results.append(TeamWeeklyContext(
            team=team,
            opponent=opponent,
            game=players[0].game,
            rest_days=rest,
            short_week=rest is not None and rest <= 6,
            post_bye=rest is not None and rest >= 10,
            travel_miles=travel,
            roof=roof,
            temperature_f=temperature,
            wind_mph=wind,
            practice_counts=tuple(sorted(practice.items())),
            defensive_absences=defensive_absences,
            notes=tuple(notes),
            home_team=home or None,
            kickoff_utc=kickoff,
        ))
    return tuple(results)


def apply_live_weather(
    contexts: tuple[TeamWeeklyContext, ...],
) -> tuple[TeamWeeklyContext, ...]:
    """Overlay live NWS forecasts on outdoor games, one request per game."""
    game_inputs = {}
    for item in contexts:
        indoor = (item.roof or "").lower() in {"dome", "closed"}
        coordinates = TEAM_COORDINATES.get(_team(item.home_team))
        if not indoor and coordinates and item.kickoff_utc is not None:
            game_inputs[(item.home_team, item.kickoff_utc)] = (
                coordinates, item.kickoff_utc
            )
    forecasts = {}
    with ThreadPoolExecutor(max_workers=min(6, len(game_inputs) or 1)) as executor:
        pending = {
            executor.submit(fetch_nws_hourly_forecast, *coordinates, kickoff): key
            for key, (coordinates, kickoff) in game_inputs.items()
        }
        for future in as_completed(pending):
            try:
                forecasts[pending[future]] = future.result()
            except OSError:
                pass
    results = []
    for item in contexts:
        indoor = (item.roof or "").lower() in {"dome", "closed"}
        coordinates = TEAM_COORDINATES.get(_team(item.home_team))
        if indoor or not coordinates or item.kickoff_utc is None:
            results.append(item)
            continue
        game_key = (item.home_team, item.kickoff_utc)
        forecast = forecasts.get(game_key)
        if forecast is None:
            results.append(item)
            continue
        notes = [note for note in item.notes if not note.startswith("Wind watch")]
        if forecast.wind_mph is not None and forecast.wind_mph >= 15:
            notes.append(f"Wind watch ({forecast.wind_mph:.0f} mph)")
        if (
            forecast.precipitation_probability is not None
            and forecast.precipitation_probability >= 50
        ):
            notes.append(
                f"Precipitation watch ({forecast.precipitation_probability:.0f}%)"
            )
        results.append(replace(
            item,
            temperature_f=forecast.temperature_f,
            wind_mph=forecast.wind_mph,
            precipitation_probability=forecast.precipitation_probability,
            weather_summary=forecast.summary,
            weather_source=forecast.source,
            notes=tuple(notes),
        ))
    return tuple(results)


def weekly_context_snapshot(
    contexts: tuple[TeamWeeklyContext, ...],
    *,
    season: int,
    week: int,
    checked_at: datetime | None = None,
    coach_signals: tuple[CoachSignal, ...] = (),
    slate: Slate | None = None,
    player_context: tuple = (),
) -> bytes:
    players = {player.platform_id: player for player in slate.players} if slate else {}
    payload = {
        "schema_version": 1,
        "season": season,
        "week": week,
        "checked_at_utc": (checked_at or datetime.now(timezone.utc)).isoformat(),
        "teams": [asdict(item) for item in contexts],
        "coach_signals": [asdict(item) for item in coach_signals],
        "player_observations": [
            {
                "platform_id": item.platform_id,
                "name": players[item.platform_id].name if item.platform_id in players else None,
                "team": players[item.platform_id].team if item.platform_id in players else None,
                "injury_status": item.injury_status,
                "practice_participation": item.practice_participation,
                "active": item.active,
                "depth_chart_position": item.depth_chart_position,
                "expected_role": item.expected_role,
                "role_note": item.role_note,
            }
            for item in player_context
        ],
    }
    return (json.dumps(payload, indent=2, default=_json_default) + "\n").encode()


def append_weekly_snapshot_history(path: str | Path, snapshot: bytes) -> bool:
    """Append a timestamped observation unless it duplicates the latest facts."""
    destination = Path(path).expanduser()
    current = json.loads(snapshot)
    comparable = {key: value for key, value in current.items() if key != "checked_at_utc"}
    if destination.exists():
        lines = [line for line in destination.read_text().splitlines() if line.strip()]
        if lines:
            previous_full = json.loads(lines[-1])
            previous = {
                key: value for key, value in previous_full.items()
                if key != "checked_at_utc"
            }
            previous_checked = _parsed_datetime(previous_full.get("checked_at_utc"))
            current_checked = _parsed_datetime(current.get("checked_at_utc"))
            same_day = (
                previous_checked is not None and current_checked is not None
                and previous_checked.date() == current_checked.date()
            )
            if previous == comparable and same_day:
                return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(current, separators=(",", ":")) + "\n")
    return True


def load_practice_trajectories(path: str | Path) -> tuple[PracticeTrajectory, ...]:
    source = Path(path).expanduser()
    if not source.exists():
        return ()
    histories: dict[str, dict] = {}
    for line in source.read_text().splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        checked = _parsed_datetime(payload.get("checked_at_utc"))
        day = checked.strftime("%a") if checked else "?"
        for item in payload.get("player_observations", []):
            practice = _practice_label(item.get("practice_participation"))
            injury = (item.get("injury_status") or "").strip().upper()
            label = practice or injury
            if not label:
                continue
            record = histories.setdefault(item["platform_id"], {
                "name": item.get("name") or item["platform_id"],
                "team": item.get("team") or "",
                "values": [],
            })
            record["values"].append(f"{day} {label}")
    rank = {"OUT": 0, "DNP": 1, "DOUBTFUL": 1, "LP": 2, "QUESTIONABLE": 2, "FP": 3, "ACTIVE": 3}
    results = []
    for player_id, record in histories.items():
        values = tuple(record["values"])
        raw = [value.split(maxsplit=1)[-1] for value in values]
        improving = len(raw) >= 2 and rank.get(raw[-1], 2) > rank.get(raw[0], 2)
        results.append(PracticeTrajectory(
            platform_id=player_id,
            name=record["name"],
            team=record["team"],
            observations=values,
            latest=raw[-1],
            improving=improving,
        ))
    return tuple(sorted(results, key=lambda item: (item.latest in {"FP", "ACTIVE"}, item.team, item.name)))


def coach_signal_csv_template(slate: Slate) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(("player", "team", "signal", "confidence", "speaker", "published_at", "source_url", "note"))
    for player in slate.players:
        writer.writerow((player.name, player.team, "", "", "", "", "", ""))
    return output.getvalue().encode()


def import_coach_signals(content: bytes) -> tuple[CoachSignal, ...]:
    allowed = {"expanded", "normal", "committee", "limited", "returning", "uncertain"}
    reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig")))
    results = []
    for number, row in enumerate(reader, start=2):
        signal = (row.get("signal") or "").strip().lower()
        if not signal:
            continue
        if signal not in allowed:
            raise ValueError(f"coach signal row {number} has unsupported signal: {signal}")
        player = (row.get("player") or "").strip()
        team = (row.get("team") or "").strip().upper()
        if not player or not team:
            raise ValueError(f"coach signal row {number} requires player and team")
        results.append(CoachSignal(
            player=player, team=team, signal=signal,
            confidence=(row.get("confidence") or "medium").strip().lower(),
            speaker=(row.get("speaker") or "").strip() or None,
            published_at=(row.get("published_at") or "").strip() or None,
            source_url=(row.get("source_url") or "").strip() or None,
            note=(row.get("note") or "").strip() or None,
        ))
    return tuple(results)


def apply_coach_signals_to_player_context(
    slate: Slate,
    contexts: tuple[PlayerContext, ...],
    signals: tuple[CoachSignal, ...],
) -> tuple[PlayerContext, ...]:
    """Merge explicitly reviewed coach reports into optimizer role context."""
    players_by_key = {
        (_normalized_name(player.name), _team(player.team)): player
        for player in slate.players
    }
    by_id = {item.platform_id: item for item in contexts}
    for signal in signals:
        player = players_by_key.get((_normalized_name(signal.player), _team(signal.team)))
        if player is None:
            raise ValueError(
                f"coach signal did not match this slate: {signal.player} ({signal.team})"
            )
        current = by_id.get(player.platform_id) or PlayerContext(
            player.platform_id, None, None, None, None
        )
        expected_role = {
            "expanded": "expanded", "normal": "normal",
            "committee": "committee", "limited": "limited",
            "returning": "returning", "uncertain": "uncertain",
        }[signal.signal]
        attribution = " · ".join(filter(None, (
            signal.note,
            f"Speaker: {signal.speaker}" if signal.speaker else None,
            f"Source: {signal.source_url}" if signal.source_url else None,
        )))
        by_id[player.platform_id] = replace(
            current,
            expected_role=expected_role,
            role_note=attribution or f"Imported coach signal: {signal.signal}",
        )
    return tuple(by_id.values())


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def _team(value: str | None) -> str:
    normalized = (value or "").strip().upper()
    return TEAM_ALIASES.get(normalized, normalized)


def _normalized_name(value: str) -> str:
    return " ".join(value.casefold().replace(".", "").split())


def _integer(value: str | None) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _number(value: str | None) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except ValueError:
        return None


def _practice_label(value: str | None) -> str | None:
    text = (value or "").lower()
    if "did not" in text or text in {"dnp", "none"}:
        return "DNP"
    if "limited" in text or text == "lp":
        return "LP"
    if "full" in text or text == "fp":
        return "FP"
    return None


def _is_limited_or_out(row: dict[str, str]) -> bool:
    text = " ".join((row.get("report_status", ""), row.get("practice_status", ""))).lower()
    return any(term in text for term in ("out", "doubtful", "did not", "limited"))


def _travel_miles(away: str, home: str) -> int:
    origin = TEAM_COORDINATES.get(_team(away))
    destination = TEAM_COORDINATES.get(_team(home))
    if not origin or not destination:
        return 0
    lat1, lon1, lat2, lon2 = map(math.radians, (*origin, *destination))
    value = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return round(3958.8 * 2 * math.asin(math.sqrt(value)))


def _kickoff_utc(gameday: str | None, gametime: str | None) -> datetime | None:
    if not gameday or not gametime:
        return None
    try:
        local = datetime.fromisoformat(f"{gameday}T{gametime}")
    except ValueError:
        return None
    return local.replace(tzinfo=ZoneInfo("America/New_York")).astimezone(timezone.utc)


def _json_default(value):
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"cannot serialize {type(value).__name__}")


def _parsed_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None
