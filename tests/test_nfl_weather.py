from __future__ import annotations

from datetime import datetime, timezone
import unittest
from unittest.mock import Mock, patch

from dfs_optimizer.data_sources.nfl_weather import fetch_nws_hourly_forecast


class NFLWeatherTests(unittest.TestCase):
    @patch("dfs_optimizer.data_sources.nfl_weather.requests.get")
    def test_fetches_hour_nearest_kickoff(self, get: Mock) -> None:
        point = Mock()
        point.raise_for_status.return_value = None
        point.json.return_value = {
            "properties": {"forecastHourly": "https://api.weather.gov/gridpoints/X/1,1/forecast/hourly"}
        }
        hourly = Mock()
        hourly.raise_for_status.return_value = None
        hourly.json.return_value = {"properties": {"periods": [{
            "startTime": "2026-10-27T20:00:00+00:00",
            "temperature": 49,
            "windSpeed": "12 to 18 mph",
            "probabilityOfPrecipitation": {"value": 65},
            "shortForecast": "Rain Likely",
        }]}}
        get.side_effect = (point, hourly)

        forecast = fetch_nws_hourly_forecast(
            40.0, -75.0, datetime(2026, 10, 27, 20, 15, tzinfo=timezone.utc)
        )

        self.assertEqual(forecast.temperature_f, 49)
        self.assertEqual(forecast.wind_mph, 18)
        self.assertEqual(forecast.precipitation_probability, 65)
        self.assertEqual(forecast.source, "National Weather Service")

