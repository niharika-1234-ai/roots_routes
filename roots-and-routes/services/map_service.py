from __future__ import annotations

import json
import math
import re
import threading
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import Request, urlopen


class MapServiceError(Exception):
    """Raised when an external geocoding, routing, or nearby-place service fails."""


_geocode_lock = threading.Lock()
_geocode_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_last_geocode_request = 0.0
_nearby_lock = threading.Lock()
_nearby_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}

_NEARBY_SELECTORS = {
    "restaurants": (
        '["amenity"="restaurant"]',
        '["amenity"="fast_food"]',
        '["amenity"="cafe"]',
    ),
    "hotels": (
        '["tourism"~"^(hotel|motel|guest_house|hostel|apartment|resort|chalet|camp_site)$"]',
        '["tourism"="homestay"]',
        '["homestay"="yes"]',
        '["accommodation"~"^(homestay|budget_hotel)$"]',
        '["budget"="yes"]',
    ),
    "events": (
        '["amenity"="events_venue"]',
        '["leisure"="events_venue"]',
    ),
    "attractions": (
        '["tourism"~"^(attraction|museum|viewpoint|theme_park)$"]',
    ),
    "hospitals": (
        '["amenity"="hospital"]',
    ),
    "police": (
        '["amenity"="police"]',
    ),
}
NEARBY_CATEGORIES = frozenset(_NEARBY_SELECTORS)


def geocode_locations(
    query: str,
    base_url: str,
    user_agent: str,
) -> list[dict[str, Any]]:
    global _last_geocode_request

    cache_key = f"{base_url.rstrip('/')}:{query.casefold()}"
    now = time.monotonic()
    with _geocode_lock:
        cached = _geocode_cache.get(cache_key)
        if cached and cached[0] > now:
            return [dict(result) for result in cached[1]]

        delay = 1.0 - (now - _last_geocode_request)
        if delay > 0:
            time.sleep(delay)
        _last_geocode_request = time.monotonic()

        url = f"{base_url.rstrip('/')}/search?{urlencode({'q': query, 'format': 'jsonv2', 'limit': 5})}"
        payload = _request_json(url, user_agent=user_agent, timeout=12)

        results = []
        if isinstance(payload, list):
            for item in payload:
                if not isinstance(item, dict):
                    continue
                try:
                    latitude = float(item["lat"])
                    longitude = float(item["lon"])
                except (KeyError, TypeError, ValueError):
                    continue
                if not _valid_coordinates(latitude, longitude):
                    continue
                label = str(item.get("display_name", "")).strip()
                if not label:
                    continue
                osm_type = str(item.get("osm_type", "")).lower()
                osm_id = item.get("osm_id")
                source_url = (
                    f"https://www.openstreetmap.org/{osm_type}/{osm_id}"
                    if osm_type in {"node", "way", "relation"} and osm_id
                    else "https://www.openstreetmap.org/"
                )
                results.append(
                    {
                        "label": label,
                        "latitude": latitude,
                        "longitude": longitude,
                        "source_url": source_url,
                    }
                )
        _geocode_cache[cache_key] = (time.monotonic() + 3600, results)
        if len(_geocode_cache) > 256:
            _geocode_cache.pop(next(iter(_geocode_cache)))
        return [dict(result) for result in results]


def get_road_routes(
    source_latitude: float,
    source_longitude: float,
    destination_latitude: float,
    destination_longitude: float,
    base_url: str,
    user_agent: str,
) -> dict[str, Any]:
    coordinates = (
        f"{source_longitude:.6f},{source_latitude:.6f};"
        f"{destination_longitude:.6f},{destination_latitude:.6f}"
    )
    options = urlencode(
        {
            "alternatives": "true",
            "steps": "true",
            "overview": "full",
            "geometries": "geojson",
        }
    )
    url = f"{base_url.rstrip('/')}/route/v1/driving/{coordinates}?{options}"
    payload = _request_json(url, user_agent=user_agent, timeout=25)
    if not isinstance(payload, dict):
        raise MapServiceError("The routing service returned an invalid response.")
    if payload.get("code") in {"NoRoute", "NoSegment"}:
        return {"code": "NoRoute", "routes": []}
    if payload.get("code") != "Ok" or not payload.get("routes"):
        raise MapServiceError("The routing service could not calculate a road route.")
    return payload


def get_nearby_places(
    category: str,
    latitude: float,
    longitude: float,
    radius: int,
    endpoint: str,
    user_agent: str,
) -> list[dict[str, Any]]:
    selectors = _NEARBY_SELECTORS.get(category)
    if selectors is None:
        raise ValueError("Unsupported nearby category.")

    cacheable = category not in {"hospitals", "police"}
    cache_key = f"{category}:{latitude:.4f}:{longitude:.4f}:{radius}"
    now = time.monotonic()
    with _nearby_lock:
        if cacheable:
            cached = _nearby_cache.get(cache_key)
            if cached and cached[0] > now:
                return [dict(place) for place in cached[1]]

        selector_query = "\n".join(
            f'nwr{selector}(around:{radius},{latitude:.6f},{longitude:.6f});'
            for selector in selectors
        )
        query = f"[out:json][timeout:12];\n(\n{selector_query}\n);\nout center tags 30;"
        body = urlencode({"data": query}).encode("utf-8")
        payload = _request_json(
            endpoint,
            user_agent=user_agent,
            timeout=15,
            body=body,
        )

        places = []
        if isinstance(payload, dict) and isinstance(payload.get("elements"), list):
            for item in payload["elements"]:
                if not isinstance(item, dict):
                    continue
                center = item.get("center", {})
                if not isinstance(center, dict):
                    center = {}
                try:
                    place_latitude = float(item.get("lat", center.get("lat")))
                    place_longitude = float(item.get("lon", center.get("lon")))
                except (TypeError, ValueError):
                    continue
                tags = item.get("tags", {})
                if not isinstance(tags, dict):
                    continue
                name = str(tags.get("name") or tags.get("brand") or "").strip()
                osm_type = str(item.get("type", "")).lower()
                osm_id = item.get("id")
                if (
                    not name
                    or not _valid_coordinates(place_latitude, place_longitude)
                    or osm_type not in {"node", "way", "relation"}
                    or not osm_id
                ):
                    continue
                image_url, image_source_url = _image_urls(tags)
                places.append(
                    {
                        "name": name,
                        "category": category,
                        "place_type": _place_type(tags, category),
                        "latitude": place_latitude,
                        "longitude": place_longitude,
                        "distance_km": round(
                            distance_km(latitude, longitude, place_latitude, place_longitude),
                            2,
                        ),
                        "cuisine": _display_cuisine(tags.get("cuisine")) if category == "restaurants" else "",
                        "rating": _display_tag(tags.get("rating")),
                        "stars": _display_tag(tags.get("stars")),
                        "price_label": _price_label(tags),
                        "price": _price_value(tags),
                        "budget_tagged": _is_budget_tagged(tags),
                        "image_url": image_url,
                        "image_source_url": image_source_url,
                        "website_url": _safe_external_url(
                            tags.get("website") or tags.get("contact:website")
                        ),
                        "booking_url": _safe_external_url(
                            tags.get("booking:website") or tags.get("contact:booking")
                        ),
                        "details": _place_details(tags),
                        "source_url": f"https://www.openstreetmap.org/{osm_type}/{osm_id}",
                    }
                )
        places.sort(key=lambda place: place["distance_km"])
        if cacheable:
            _nearby_cache[cache_key] = (time.monotonic() + 300, places)
            if len(_nearby_cache) > 256:
                _nearby_cache.pop(next(iter(_nearby_cache)))
        return [dict(place) for place in places]


def _request_json(
    url: str,
    user_agent: str,
    timeout: int,
    body: bytes | None = None,
) -> Any:
    headers = {
        "User-Agent": user_agent,
        "Accept": "application/json",
    }
    if body is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"
    request = Request(url, data=body, headers=headers)
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read())
    except HTTPError as error:
        raise MapServiceError(
            f"The map provider returned HTTP {error.code}."
        ) from error
    except (URLError, TimeoutError, OSError) as error:
        raise MapServiceError("The map provider could not be reached.") from error
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise MapServiceError("The map provider returned invalid JSON.") from error


def _valid_coordinates(latitude: float, longitude: float) -> bool:
    return (
        math.isfinite(latitude)
        and math.isfinite(longitude)
        and -90 <= latitude <= 90
        and -180 <= longitude <= 180
    )


def distance_km(
    source_latitude: float,
    source_longitude: float,
    destination_latitude: float,
    destination_longitude: float,
) -> float:
    latitude_delta = math.radians(destination_latitude - source_latitude)
    longitude_delta = math.radians(destination_longitude - source_longitude)
    source_latitude_radians = math.radians(source_latitude)
    destination_latitude_radians = math.radians(destination_latitude)
    haversine = (
        math.sin(latitude_delta / 2) ** 2
        + math.cos(source_latitude_radians)
        * math.cos(destination_latitude_radians)
        * math.sin(longitude_delta / 2) ** 2
    )
    return 6371 * 2 * math.asin(math.sqrt(min(1.0, haversine)))


def _place_details(tags: dict[str, Any]) -> str:
    details = []
    for key in ("tourism", "amenity", "opening_hours"):
        value = tags.get(key)
        if value:
            details.append(re.sub(r"[_;]", " ", str(value)))
    return " · ".join(details)


def _display_tag(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"[_;]", " ", value).strip()


def _display_cuisine(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return value.replace("_", " ").strip()


def _place_type(tags: dict[str, Any], category: str) -> str:
    if category == "hospitals":
        return "Hospital"
    if category == "police":
        return "Police station"
    if category == "restaurants":
        return _display_tag(tags.get("amenity")) or "Restaurant"

    if str(tags.get("homestay", "")).casefold() == "yes" or str(tags.get("accommodation", "")).casefold() == "homestay":
        return "Homestay"

    tourism = str(tags.get("tourism", "")).casefold()
    stay_type = {
        "hotel": "Hotel",
        "motel": "Motel",
        "resort": "Resort",
        "guest_house": "Guest house",
        "hostel": "Hostel",
        "apartment": "Apartment",
        "chalet": "Chalet",
        "camp_site": "Camp site",
        "homestay": "Homestay",
    }.get(tourism)
    if category == "hotels":
        if stay_type:
            return stay_type
        if (
            str(tags.get("budget", "")).casefold() in {"yes", "true", "1"}
            or str(tags.get("accommodation", "")).casefold() == "budget_hotel"
        ):
            return "Budget-tagged stay"
        return "Accommodation"
    return (
        _display_tag(tags.get("amenity") or tags.get("leisure") or tourism)
        or category
    )


def _price_label(tags: dict[str, Any]) -> str:
    for key, label in (
        ("price:per_night", "Listed price per night"),
        ("price", "Listed price"),
        ("charge", "Listed charge"),
        ("fee", "Listed fee"),
    ):
        if tags.get(key):
            return label
    return ""


def _price_value(tags: dict[str, Any]) -> str:
    for key in ("price:per_night", "price", "charge", "fee"):
        value = _display_tag(tags.get(key))
        if value:
            return value
    return ""


def _is_budget_tagged(tags: dict[str, Any]) -> bool:
    return (
        str(tags.get("budget", "")).casefold() in {"yes", "true", "1"}
        or str(tags.get("accommodation", "")).casefold() == "budget_hotel"
    )


def _safe_external_url(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    url = value.strip()
    parts = urlsplit(url)
    return url if parts.scheme in {"http", "https"} and parts.netloc else ""


def _image_urls(tags: dict[str, Any]) -> tuple[str, str]:
    commons_value = tags.get("wikimedia_commons")
    if not isinstance(commons_value, str):
        return "", ""
    commons_file = commons_value.strip()
    if commons_file.casefold().startswith("file:"):
        commons_file = commons_file[5:].strip()
    if not commons_file or commons_file.startswith("http") or ":" in commons_file:
        return "", ""
    encoded_file = quote(commons_file, safe="")
    return (
        f"https://commons.wikimedia.org/wiki/Special:FilePath/{encoded_file}?width=720",
        f"https://commons.wikimedia.org/wiki/File:{encoded_file}",
    )
