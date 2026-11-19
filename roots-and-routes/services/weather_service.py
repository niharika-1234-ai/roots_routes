from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from models.destination import Destination

_OPENWEATHER_API_URL = "https://api.openweathermap.org/data/2.5"
_HEAVY_RAIN_CODES = frozenset({502, 503, 504, 522})


class WeatherServiceError(Exception):
    """Raised when live weather cannot be retrieved or validated."""


def get_destination_weather(
    destination: Destination,
    api_key: str,
) -> dict[str, Any]:
    if not api_key:
        raise WeatherServiceError("The live weather provider is not configured.")

    parameters = {
        "lat": f"{destination.latitude:.6f}",
        "lon": f"{destination.longitude:.6f}",
        "appid": api_key,
        "units": "metric",
    }
    current_payload = _request_weather("weather", parameters)
    forecast_payload = _request_weather("forecast", parameters)

    try:
        current_weather = current_payload["weather"][0]
        current_temperature = _finite_number(current_payload["main"]["temp"])
        current_timestamp = _timestamp(current_payload["dt"])
        current_condition = _condition(current_weather)
        timezone_offset = _integer(forecast_payload["city"]["timezone"])
    except (IndexError, KeyError, TypeError, ValueError) as error:
        raise WeatherServiceError("The weather provider returned incomplete current conditions.") from error
    if current_temperature is None:
        raise WeatherServiceError("The weather provider returned an invalid temperature.")

    forecast_items = forecast_payload.get("list")
    if not isinstance(forecast_items, list):
        raise WeatherServiceError("The weather provider returned an invalid forecast.")
    forecast_periods = [
        period
        for item in forecast_items
        if (period := _forecast_period(item)) is not None
    ]
    if not forecast_periods:
        raise WeatherServiceError("The weather provider returned no usable forecast periods.")
    forecast_periods.sort(key=lambda period: period["timestamp"])

    future_periods = [
        period
        for period in forecast_periods
        if period["timestamp"] >= current_timestamp
    ]
    if not future_periods:
        raise WeatherServiceError("The weather provider returned no future forecast periods.")
    next_period = future_periods[0]
    next_24_hours = [
        period
        for period in forecast_periods
        if current_timestamp <= period["timestamp"] <= current_timestamp + 86400
    ]
    daily_forecast = _daily_forecast(forecast_periods, timezone_offset)
    current = {
        "temperature_c": round(current_temperature, 1),
        "condition": current_condition["description"],
        "condition_group": current_condition["group"],
        "rain_probability_next_period": next_period["rain_probability"],
    }
    return {
        "provider": "OpenWeatherMap",
        "destination": {
            "id": destination.id,
            "name": destination.name,
            "district": destination.district,
        },
        "current": current,
        "forecast": daily_forecast,
        "last_updated": datetime.fromtimestamp(
            current_timestamp,
            tz=timezone.utc,
        ).isoformat(),
        "recommendations": _recommendations(
            destination,
            current_temperature,
            next_24_hours,
        ),
    }


def _request_weather(resource: str, parameters: dict[str, str]) -> dict[str, Any]:
    url = f"{_OPENWEATHER_API_URL}/{resource}?{urlencode(parameters)}"
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "ROOTS-AND-ROUTES/1.0",
        },
    )
    try:
        with urlopen(request, timeout=12) as response:
            payload = json.loads(response.read(1_000_001))
    except HTTPError as error:
        if error.code == 401:
            message = "The weather provider rejected the configured API key."
        elif error.code == 429:
            message = "The weather provider rate limit was reached."
        else:
            message = "The weather provider returned a temporary error."
        raise WeatherServiceError(message) from error
    except (URLError, TimeoutError, OSError) as error:
        raise WeatherServiceError("The weather provider could not be reached.") from error
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise WeatherServiceError("The weather provider returned invalid data.") from error

    if not isinstance(payload, dict) or len(json.dumps(payload)) > 1_000_000:
        raise WeatherServiceError("The weather provider returned an invalid response.")
    return payload


def _forecast_period(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    try:
        timestamp = _timestamp(item["dt"])
        main = item["main"]
        temperature_min = _finite_number(main["temp_min"])
        temperature_max = _finite_number(main["temp_max"])
        rain_probability = _finite_number(item["pop"])
        condition = _condition(item["weather"][0])
    except (IndexError, KeyError, TypeError, ValueError):
        return None
    if (
        temperature_min is None
        or temperature_max is None
        or rain_probability is None
        or not 0 <= rain_probability <= 1
    ):
        return None
    return {
        "timestamp": timestamp,
        "temperature_min_c": temperature_min,
        "temperature_max_c": temperature_max,
        "rain_probability": round(rain_probability * 100),
        "condition": condition["description"],
        "condition_group": condition["group"],
        "condition_code": condition["code"],
    }


def _daily_forecast(
    forecast_periods: list[dict[str, Any]],
    timezone_offset: int,
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for period in forecast_periods:
        local_timestamp = period["timestamp"] + timezone_offset
        local_date = datetime.fromtimestamp(
            local_timestamp,
            tz=timezone.utc,
        ).date().isoformat()
        grouped[local_date].append(period)

    daily = []
    for forecast_date, periods in sorted(grouped.items())[:5]:
        representative = max(
            periods,
            key=lambda period: (
                period["rain_probability"],
                period["condition_code"] in _HEAVY_RAIN_CODES,
            ),
        )
        daily.append(
            {
                "date": forecast_date,
                "temperature_min_c": round(
                    min(period["temperature_min_c"] for period in periods),
                    1,
                ),
                "temperature_max_c": round(
                    max(period["temperature_max_c"] for period in periods),
                    1,
                ),
                "rain_probability": max(
                    period["rain_probability"] for period in periods
                ),
                "condition": representative["condition"],
            }
        )
    return daily


def _recommendations(
    destination: Destination,
    current_temperature: float,
    next_24_hours: list[dict[str, Any]],
) -> list[str]:
    heavy_rain_periods = [
        period
        for period in next_24_hours
        if period["condition_code"] in _HEAVY_RAIN_CODES
        and period["rain_probability"] >= 50
    ]
    thunderstorm_periods = [
        period
        for period in next_24_hours
        if 200 <= period["condition_code"] < 300
        and period["rain_probability"] >= 40
    ]
    peak_rain_probability = max(
        (period["rain_probability"] for period in next_24_hours),
        default=0,
    )

    if heavy_rain_periods:
        if destination.category.casefold() == "waterfall":
            advice = (
                "Heavy-rain conditions appear in the forecast for the next 24 hours. "
                "Waterfall areas can become hazardous during heavy rain. Check official "
                "local weather, administration, or tourism advisories and access status; "
                "consider postponing or checking another destination's forecast. "
                "This forecast is not an official warning."
            )
        else:
            advice = (
                "Heavy-rain conditions appear in the forecast for the next 24 hours. "
                "Check official local advisories and travel conditions, and consider "
                "choosing a less exposed alternative. This forecast is not an official warning."
            )
    elif thunderstorm_periods:
        advice = (
            "Thunderstorms appear in the forecast for the next 24 hours. Take care with "
            "outdoor plans and check official local advisories before travelling."
        )
    elif not next_24_hours:
        advice = (
            "The provider did not return forecast periods for the next 24 hours. "
            "Check a current local forecast and official advisories before travelling."
        )
    elif peak_rain_probability >= 60:
        advice = (
            f"A forecast period in the next 24 hours has a {peak_rain_probability}% "
            "chance of rain. Carry rain protection and keep an indoor or alternative "
            "plan; check local advisories before setting out."
        )
    else:
        advice = (
            "No high rain probability is indicated in the next 24 hours. Forecasts can "
            "change; check local conditions and advisories before travelling."
        )

    recommendations = [advice]
    if current_temperature >= 35:
        recommendations.append(
            "Current temperature is 35°C or higher. Plan shade and water breaks, "
            "especially during outdoor activities."
        )
    return recommendations


def _condition(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("Invalid weather condition.")
    code = _integer(value["id"])
    group = value["main"]
    description = value["description"]
    if not isinstance(group, str) or not group.strip():
        raise ValueError("Invalid weather condition group.")
    if not isinstance(description, str) or not description.strip():
        raise ValueError("Invalid weather description.")
    return {
        "code": code,
        "group": group.strip(),
        "description": description.strip(),
    }


def _timestamp(value: Any) -> int:
    timestamp = _integer(value)
    try:
        datetime.fromtimestamp(timestamp, tz=timezone.utc)
    except (OverflowError, OSError, ValueError) as error:
        raise ValueError("Invalid weather timestamp.") from error
    return timestamp


def _integer(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError("Expected an integer.")
    try:
        number = int(value)
        numeric_value = float(value)
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError("Expected an integer.") from error
    if number != numeric_value:
        raise ValueError("Expected an integer.")
    return number


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None
