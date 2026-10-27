from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re

import requests


NWS_HEADERS = {
    "User-Agent": "dfs-optimizer/0.1 (https://github.com/nickdemarinis7/dfs-optimizer)",
    "Accept": "application/geo+json",
}


@dataclass(frozen=True, slots=True)
class NFLWeatherForecast:
    kickoff_utc: datetime
    temperature_f: float | None
    wind_mph: float | None
    precipitation_probability: float | None
    summary: str | None
    source: str = "National Weather Service"


def fetch_nws_hourly_forecast(
    latitude: float,
    longitude: float,
    kickoff_utc: datetime,
    *,
    timeout: float = 12,
) -> NFLWeatherForecast:
    """Return the NWS hourly period closest to kickoff.

    The NWS points endpoint resolves the correct forecast office/grid, avoiding
    hard-coded weather stations. Callers should skip indoor games.
    """
    try:
        point_response = requests.get(
            f"https://api.weather.gov/points/{latitude:.4f},{longitude:.4f}",
            headers=NWS_HEADERS,
            timeout=timeout,
        )
        point_response.raise_for_status()
        hourly_url = point_response.json()["properties"]["forecastHourly"]
        forecast_response = requests.get(
            hourly_url, headers=NWS_HEADERS, timeout=timeout
        )
        forecast_response.raise_for_status()
        periods = forecast_response.json()["properties"]["periods"]
    except (KeyError, TypeError, ValueError, requests.RequestException) as exc:
        raise OSError(f"could not download kickoff weather: {exc}") from exc
    if not periods:
        raise OSError("could not download kickoff weather: hourly forecast was empty")

    def distance(period) -> float:
        start = datetime.fromisoformat(period["startTime"])
        return abs((start - kickoff_utc.astimezone(start.tzinfo)).total_seconds())

    period = min(periods, key=distance)
    if distance(period) > 12 * 3600:
        raise OSError("could not download kickoff weather: kickoff is outside the hourly forecast window")
    wind_values = [float(value) for value in re.findall(r"\d+(?:\.\d+)?", period.get("windSpeed", ""))]
    wind = max(wind_values) if wind_values else None
    precipitation = (period.get("probabilityOfPrecipitation") or {}).get("value")
    return NFLWeatherForecast(
        kickoff_utc=kickoff_utc,
        temperature_f=_number(period.get("temperature")),
        wind_mph=wind,
        precipitation_probability=_number(precipitation),
        summary=(period.get("shortForecast") or "").strip() or None,
    )


def _number(value) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
