from __future__ import annotations

from dataclasses import dataclass
import statistics

import requests


CFB_ODDS_URL = (
    "https://api.the-odds-api.com/v4/sports/americanfootball_ncaaf/odds"
)


@dataclass(frozen=True, slots=True)
class CFBConsensusLine:
    home_team: str
    away_team: str
    game_total: float
    home_spread: float
    away_spread: float


def fetch_cfb_consensus_lines(api_key: str) -> tuple[CFBConsensusLine, ...]:
    """Fetch current US-book consensus NCAAF spreads and totals."""
    if not api_key.strip():
        raise ValueError("The Odds API key cannot be empty")
    try:
        response = requests.get(
            CFB_ODDS_URL,
            params={
                "apiKey": api_key,
                "regions": "us",
                "markets": "spreads,totals",
                "oddsFormat": "american",
            },
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise OSError(f"could not download current college odds: {exc}") from exc
    if not isinstance(payload, list):
        raise OSError("college odds provider returned an unexpected response")
    return parse_cfb_consensus_lines(payload)


def parse_cfb_consensus_lines(payload: list[dict]) -> tuple[CFBConsensusLine, ...]:
    lines = []
    for event in payload:
        home = str(event.get("home_team") or "").strip()
        away = str(event.get("away_team") or "").strip()
        if not home or not away:
            continue
        totals: list[float] = []
        spreads: dict[str, list[float]] = {home: [], away: []}
        for bookmaker in event.get("bookmakers") or ():
            for market in bookmaker.get("markets") or ():
                key = market.get("key")
                outcomes = market.get("outcomes") or ()
                if key == "totals":
                    points = [
                        _number(outcome.get("point"))
                        for outcome in outcomes
                        if str(outcome.get("name") or "").lower() == "over"
                    ]
                    totals.extend(value for value in points if value is not None)
                elif key == "spreads":
                    for outcome in outcomes:
                        name = str(outcome.get("name") or "").strip()
                        point = _number(outcome.get("point"))
                        if name in spreads and point is not None:
                            spreads[name].append(point)
        if not totals or not spreads[home] or not spreads[away]:
            continue
        lines.append(CFBConsensusLine(
            home_team=home,
            away_team=away,
            game_total=statistics.median(totals),
            home_spread=statistics.median(spreads[home]),
            away_spread=statistics.median(spreads[away]),
        ))
    return tuple(lines)


def _number(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
