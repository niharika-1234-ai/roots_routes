from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from app import create_app
from services.destination_service import get_destinations
from services.weather_service import WeatherServiceError, get_destination_weather


class WeatherApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        self.app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "test-session-secret",
                "DATABASE_PATH": str(Path(self.temp_directory.name) / "test.sqlite3"),
                "OPENWEATHER_API_KEY": "",
            }
        )
        self.client = self.app.test_client()
        self.destination = get_destinations(self.app.config["DESTINATIONS_PATH"])[0]

    def tearDown(self) -> None:
        self.temp_directory.cleanup()

    def register_user(self) -> None:
        self.client.get("/register")
        with self.client.session_transaction() as browser_session:
            csrf_token = browser_session["_csrf_token"]
        self.client.post(
            "/register",
            data={
                "csrf_token": csrf_token,
                "full_name": "Asha Munda",
                "email": "asha@example.com",
            },
        )

    def test_weather_workspace_exposes_destination_picker_without_sample_weather(self) -> None:
        self.register_user()

        response = self.client.get("/workspace/weather-insights")

        self.assertEqual(response.status_code, 200)
        for expected in (
            b'id="weather-form"',
            b'id="weather-destination"',
            b'id="weather-load"',
            b'id="weather-results" class="weather-results" hidden',
            b'id="weather-temperature"',
            b'id="weather-rain-probability"',
            b'id="weather-forecast"',
            b'id="weather-updated-time"',
            b'id="weather-recommendations"',
            b"static/js/weather.js",
            b"OpenWeatherMap",
            b"does not access device location",
        ):
            self.assertIn(expected, response.data)
        self.assertNotIn(b"32.0 \xc2\xb0C", response.data)

    def test_weather_api_requires_authentication_and_catalogue_destination(self) -> None:
        anonymous = self.client.get("/api/weather?destination_id=hundru-falls")
        self.assertEqual(anonymous.status_code, 401)

        self.register_user()
        invalid = self.client.get("/api/weather?destination_id=outside-catalogue")
        self.assertEqual(invalid.status_code, 400)

    def test_missing_api_key_returns_unavailable_without_calling_provider(self) -> None:
        self.register_user()

        with patch("routes.api.get_destination_weather") as get_weather:
            response = self.client.get(
                f"/api/weather?destination_id={self.destination.id}"
            )

        self.assertEqual(response.status_code, 503)
        self.assertIn("OPENWEATHER_API_KEY", response.get_json()["error"])
        get_weather.assert_not_called()

    def test_provider_failure_never_returns_a_weather_shaped_fallback(self) -> None:
        self.register_user()
        self.app.config["OPENWEATHER_API_KEY"] = "server-only-test-key"

        with patch(
            "routes.api.get_destination_weather",
            side_effect=WeatherServiceError("provider unavailable"),
        ):
            response = self.client.get(
                f"/api/weather?destination_id={self.destination.id}"
            )

        self.assertEqual(response.status_code, 502)
        self.assertNotIn("current", response.get_json())
        self.assertNotIn("forecast", response.get_json())

    def test_weather_api_returns_live_provider_result_without_exposing_key(self) -> None:
        self.register_user()
        self.app.config["OPENWEATHER_API_KEY"] = "server-only-test-key"
        result = {
            "provider": "OpenWeatherMap",
            "destination": {
                "id": self.destination.id,
                "name": self.destination.name,
                "district": self.destination.district,
            },
            "current": {
                "temperature_c": 25.0,
                "condition": "clear sky",
                "condition_group": "Clear",
                "rain_probability_next_period": 0,
            },
            "forecast": [],
            "last_updated": "2026-11-18T10:00:00+00:00",
            "recommendations": ["Check local conditions before travelling."],
        }

        with patch("routes.api.get_destination_weather", return_value=result) as get_weather:
            response = self.client.get(
                f"/api/weather?destination_id={self.destination.id}"
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), result)
        self.assertNotIn(b"server-only-test-key", response.data)
        get_weather.assert_called_once_with(self.destination, "server-only-test-key")


class WeatherServiceTests(unittest.TestCase):
    @staticmethod
    def current_payload() -> dict:
        return {
            "dt": 1_800_000_000,
            "main": {"temp": 29.26},
            "weather": [{"id": 800, "main": "Clear", "description": "clear sky"}],
        }

    @staticmethod
    def forecast_payload() -> dict:
        base_timestamp = 1_800_000_000
        return {
            "city": {"timezone": 19800},
            "list": [
                {
                    "dt": base_timestamp + 3600,
                    "main": {"temp_min": 24, "temp_max": 30},
                    "pop": 0.1,
                    "weather": [{"id": 500, "main": "Rain", "description": "light rain"}],
                },
                {
                    "dt": base_timestamp + 7200,
                    "main": {"temp_min": 23, "temp_max": 29},
                    "pop": 0.85,
                    "weather": [
                        {
                            "id": 502,
                            "main": "Rain",
                            "description": "heavy intensity rain",
                        }
                    ],
                },
                {
                    "dt": base_timestamp + 90000,
                    "main": {"temp_min": 22, "temp_max": 31},
                    "pop": 0.2,
                    "weather": [{"id": 800, "main": "Clear", "description": "clear sky"}],
                },
            ],
        }

    @staticmethod
    def response(payload: dict):
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _limit: int) -> bytes:
                return json.dumps(payload).encode("utf-8")

        return FakeResponse()

    def test_live_observation_forecast_and_waterfall_recommendation_use_provider_values(self) -> None:
        destination = get_destinations(
            Path(__file__).resolve().parents[1] / "data" / "destinations.csv"
        )[0]
        with patch(
            "services.weather_service.urlopen",
            side_effect=[
                self.response(self.current_payload()),
                self.response(self.forecast_payload()),
            ],
        ) as request:
            weather = get_destination_weather(destination, "private-test-key")

        self.assertEqual(weather["provider"], "OpenWeatherMap")
        self.assertEqual(weather["current"]["temperature_c"], 29.3)
        self.assertEqual(weather["current"]["condition"], "clear sky")
        self.assertEqual(weather["current"]["rain_probability_next_period"], 10)
        self.assertEqual(weather["forecast"][0]["rain_probability"], 85)
        self.assertEqual(
            weather["last_updated"],
            datetime.fromtimestamp(1_800_000_000, tz=timezone.utc).isoformat(),
        )
        self.assertIn("Waterfall areas can become hazardous", weather["recommendations"][0])
        self.assertIn("another destination's forecast", weather["recommendations"][0])
        self.assertEqual(request.call_count, 2)
        for call in request.call_args_list:
            parsed_url = urlparse(call.args[0].full_url)
            query = parse_qs(parsed_url.query)
            self.assertEqual(query["appid"], ["private-test-key"])
            self.assertEqual(query["units"], ["metric"])
            self.assertEqual(query["lat"], [f"{destination.latitude:.6f}"])
            self.assertEqual(query["lon"], [f"{destination.longitude:.6f}"])
        self.assertEqual(
            [
                urlparse(call.args[0].full_url).path
                for call in request.call_args_list
            ],
            ["/data/2.5/weather", "/data/2.5/forecast"],
        )

    def test_malformed_provider_data_is_rejected_instead_of_showing_zero_rain(self) -> None:
        destination = get_destinations(
            Path(__file__).resolve().parents[1] / "data" / "destinations.csv"
        )[0]
        invalid_forecast = {
            "city": {"timezone": 19800},
            "list": [
                {
                    "dt": 1_800_003_600,
                    "main": {"temp_min": 24, "temp_max": 30},
                    "pop": None,
                    "weather": [{"id": 800, "main": "Clear", "description": "clear sky"}],
                }
            ],
        }
        with patch(
            "services.weather_service.urlopen",
            side_effect=[
                self.response(self.current_payload()),
                self.response(invalid_forecast),
            ],
        ):
            with self.assertRaises(WeatherServiceError):
                get_destination_weather(destination, "private-test-key")


if __name__ == "__main__":
    unittest.main()
