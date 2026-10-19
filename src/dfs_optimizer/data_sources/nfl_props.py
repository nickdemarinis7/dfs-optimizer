from __future__ import annotations

from dataclasses import dataclass
import statistics

import requests


NFL_EVENTS_URL = "https://api.the-odds-api.com/v4/sports/americanfootball_nfl/events"
PROP_MARKETS = (
    "player_pass_yds",
    "player_pass_tds",
    "player_rush_reception_yds",
    "player_receptions",
)
NFL_TEAM_NAMES = {
    "ARI": "Arizona Cardinals", "ATL": "Atlanta Falcons", "BAL": "Baltimore Ravens",
    "BUF": "Buffalo Bills", "CAR": "Carolina Panthers", "CHI": "Chicago Bears",
    "CIN": "Cincinnati Bengals", "CLE": "Cleveland Browns", "DAL": "Dallas Cowboys",
    "DEN": "Denver Broncos", "DET": "Detroit Lions", "GB": "Green Bay Packers",
    "HOU": "Houston Texans", "IND": "Indianapolis Colts", "JAX": "Jacksonville Jaguars",
    "JAC": "Jacksonville Jaguars",
    "KC": "Kansas City Chiefs", "LV": "Las Vegas Raiders", "LAC": "Los Angeles Chargers",
    "LA": "Los Angeles Rams", "LAR": "Los Angeles Rams", "MIA": "Miami Dolphins",
    "MIN": "Minnesota Vikings", "NE": "New England Patriots", "NO": "New Orleans Saints",
    "NYG": "New York Giants", "NYJ": "New York Jets", "PHI": "Philadelphia Eagles",
    "PIT": "Pittsburgh Steelers", "SEA": "Seattle Seahawks", "SF": "San Francisco 49ers",
    "TB": "Tampa Bay Buccaneers", "TEN": "Tennessee Titans", "WAS": "Washington Commanders",
    "WSH": "Washington Commanders",
}


@dataclass(frozen=True, slots=True)
class NFLPropConsensus:
    player: str
    event_id: str
    markets: tuple[tuple[str, float], ...]


def fetch_nfl_prop_consensus(
    api_key: str,
    *,
    event_ids: frozenset[str] | None = None,
    teams: frozenset[str] | None = None,
) -> tuple[tuple[NFLPropConsensus, ...], int | None]:
    """Fetch median NFL prop lines for upcoming events.

    Event discovery is quota-free. Each selected event request asks for four
    markets in one US region, which costs at most four usage credits when all
    requested markets are returned.
    """
    key = api_key.strip()
    if not key:
        raise ValueError("The Odds API key cannot be empty")
    try:
        events_response = requests.get(
            NFL_EVENTS_URL, params={"apiKey": key}, timeout=30
        )
        events_response.raise_for_status()
        events = events_response.json()
    except (requests.RequestException, ValueError) as exc:
        raise OSError(f"could not download current NFL events: {exc}") from exc
    if not isinstance(events, list):
        raise OSError("NFL events provider returned an unexpected response")

    consensus = []
    remaining = None
    for event in events:
        event_id = str(event.get("id") or "")
        if not event_id or (event_ids is not None and event_id not in event_ids):
            continue
        if teams is not None and not {
            str(event.get("home_team") or ""), str(event.get("away_team") or "")
        } <= teams:
            continue
        try:
            response = requests.get(
                f"{NFL_EVENTS_URL}/{event_id}/odds",
                params={
                    "apiKey": key,
                    "regions": "us",
                    "markets": ",".join(PROP_MARKETS),
                    "oddsFormat": "american",
                },
                timeout=30,
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise OSError(f"could not download NFL player props: {exc}") from exc
        try:
            remaining = int(response.headers.get("x-requests-remaining", ""))
        except ValueError:
            pass
        consensus.extend(parse_nfl_prop_consensus(payload, event_id))
    return tuple(consensus), remaining


def parse_nfl_prop_consensus(
    payload: dict, event_id: str
) -> tuple[NFLPropConsensus, ...]:
    values: dict[tuple[str, str], list[float]] = {}
    for bookmaker in payload.get("bookmakers") or ():
        for market in bookmaker.get("markets") or ():
            market_key = str(market.get("key") or "")
            if market_key not in PROP_MARKETS:
                continue
            for outcome in market.get("outcomes") or ():
                if str(outcome.get("name") or "").casefold() != "over":
                    continue
                player = str(outcome.get("description") or "").strip()
                try:
                    point = float(outcome.get("point"))
                except (TypeError, ValueError):
                    continue
                if player:
                    values.setdefault((player, market_key), []).append(point)
    by_player: dict[str, list[tuple[str, float]]] = {}
    for (player, market), points in values.items():
        by_player.setdefault(player, []).append((market, statistics.median(points)))
    return tuple(
        NFLPropConsensus(player, event_id, tuple(sorted(markets)))
        for player, markets in sorted(by_player.items())
    )
