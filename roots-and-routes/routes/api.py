import math

from flask import Blueprint, current_app, jsonify, request, session

from services.dashboard_service import filter_destinations
from services.destination_service import get_destinations
from services.carbon_service import (
    CarbonFactorDataError,
    calculate_carbon_footprint,
    get_transport_factors,
)
from services.event_service import (
    CULTURAL_EVENT_CATEGORIES,
    CulturalEventDataError,
    get_cultural_events,
)
from services.map_service import (
    NEARBY_CATEGORIES,
    MapServiceError,
    geocode_locations,
    get_nearby_places,
    get_road_routes,
)
from services.security import valid_csrf_token
from services.travel_companion_service import (
    MAX_MESSAGE_LENGTH,
    answer_travel_question,
)

api = Blueprint("api", __name__, url_prefix="/api")
SAFETY_NEARBY_CATEGORIES = frozenset({"hospitals", "police"})
STANDARD_NEARBY_CATEGORIES = NEARBY_CATEGORIES - SAFETY_NEARBY_CATEGORIES


@api.get("/health")
def health():
    return jsonify({"status": "ok"})


@api.post("/companion/chat")
def companion_chat():
    if not isinstance(session.get("user_id"), int):
        return jsonify({"error": "Sign in to use the travel companion."}), 401
    if request.content_length is not None and request.content_length > 8192:
        return jsonify({"error": "Chat requests must be 8 KB or smaller."}), 413

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "Send a JSON chat message."}), 400
    if not valid_csrf_token(payload.get("csrf_token")):
        return jsonify({"error": "Your session token expired. Reload the page and try again."}), 400

    message = payload.get("message")
    if not isinstance(message, str) or not message.strip():
        return jsonify({"error": "Enter a question for the travel companion."}), 400
    message = message.strip()
    if len(message) > MAX_MESSAGE_LENGTH:
        return jsonify({"error": f"Keep messages under {MAX_MESSAGE_LENGTH} characters."}), 400

    try:
        result = answer_travel_question(
            message,
            get_destinations(current_app.config["DESTINATIONS_PATH"]),
            session.get("travel_companion_context"),
            events_path=current_app.config["CULTURAL_EVENTS_PATH"],
            overpass_url=current_app.config["OVERPASS_URL"],
            user_agent=current_app.config["NOMINATIM_USER_AGENT"],
            llm_api_key=current_app.config["TRAVEL_COMPANION_LLM_API_KEY"],
            llm_endpoint=current_app.config["TRAVEL_COMPANION_LLM_ENDPOINT"],
            llm_model=current_app.config["TRAVEL_COMPANION_LLM_MODEL"],
        )
    except CulturalEventDataError:
        current_app.logger.exception("Verified cultural event data could not be loaded for chat.")
        return jsonify({"error": "Verified cultural event listings are temporarily unavailable."}), 500

    session["travel_companion_context"] = result["context"]
    session.modified = True
    return jsonify(result)


@api.post("/carbon-estimate")
def carbon_estimate():
    if not isinstance(session.get("user_id"), int):
        return jsonify({"error": "Sign in to calculate a travel footprint."}), 401
    if request.content_length is not None and request.content_length > 8192:
        return jsonify({"error": "Carbon estimate requests must be 8 KB or smaller."}), 413

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "Send the trip details as a JSON object."}), 400
    if not valid_csrf_token(payload.get("csrf_token")):
        return jsonify({"error": "Your session token expired. Reload the page and try again."}), 400

    source = payload.get("source")
    destination = payload.get("destination")
    mode = payload.get("mode")
    if (
        not isinstance(source, str)
        or not source.strip()
        or len(source.strip()) > 160
        or not isinstance(destination, str)
        or not destination.strip()
        or len(destination.strip()) > 160
    ):
        return jsonify({"error": "Enter a source and destination, up to 160 characters each."}), 400
    if not isinstance(mode, str):
        return jsonify({"error": "Choose a supported transport mode."}), 400

    try:
        travellers = _read_travellers(payload.get("travellers"))
        manual_distance = _read_manual_distance(payload.get("manual_distance_km"))
        source_coordinates = _read_point(payload.get("source_coordinates"))
        destination_coordinates = _read_point(payload.get("destination_coordinates"))
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    if (source_coordinates is None) != (destination_coordinates is None):
        return jsonify({"error": "Resolve both locations before requesting a road route."}), 400

    try:
        factors = get_transport_factors(
            current_app.config["TRANSPORT_EMISSION_FACTORS_PATH"]
        )
    except CarbonFactorDataError:
        current_app.logger.exception("Transport emissions factor data is unavailable or invalid.")
        return jsonify({"error": "Transport emissions factor data is temporarily unavailable."}), 500
    if mode.casefold() not in {factor["mode_id"] for factor in factors}:
        return jsonify({"error": "Choose a supported transport mode."}), 400

    distance_km = manual_distance
    distance_source = "manual"
    distance_note = (
        "User-entered one-way distance. OSRM road distance was not used because both "
        "locations were not resolved."
    )
    route_error = None
    if source_coordinates is not None and destination_coordinates is not None:
        try:
            route_result = get_road_routes(
                *source_coordinates,
                *destination_coordinates,
                current_app.config["OSRM_BASE_URL"],
                current_app.config["NOMINATIM_USER_AGENT"],
            )
            routes = route_result.get("routes")
            if route_result.get("code") == "Ok" and isinstance(routes, list) and routes:
                try:
                    road_distance_km = float(routes[0]["distance"]) / 1000
                except (KeyError, TypeError, ValueError):
                    road_distance_km = math.nan
                if math.isfinite(road_distance_km) and 0 <= road_distance_km <= 50000:
                    distance_km = road_distance_km
                    distance_source = "osrm"
                    distance_note = (
                        "OSRM road-network distance for one trip, used as the common "
                        "distance basis for every mode. Actual bus and rail route lengths "
                        "may differ."
                    )
                else:
                    route_error = "OSRM returned an invalid road distance."
            else:
                route_error = "OSRM could not find a road route for these locations."
        except MapServiceError as error:
            current_app.logger.warning("Carbon calculator OSRM request failed: %s", error)
            route_error = "OSRM road routing is temporarily unavailable."

        if distance_source != "osrm" and manual_distance is not None:
            distance_km = manual_distance
            distance_note = (
                f"{route_error or 'OSRM road routing is unavailable'} Using the "
                "user-entered one-way distance instead."
            )
        elif distance_source != "osrm":
            return jsonify(
                {
                    "error": (
                        f"{route_error or 'OSRM could not calculate the road distance'} "
                        "Enter a one-way distance to use as a fallback."
                    )
                }
            ), 502

    if distance_km is None:
        return jsonify(
            {"error": "Enter a one-way distance or resolve both locations for an OSRM road route."}
        ), 400

    try:
        result = calculate_carbon_footprint(
            factors,
            distance_km,
            travellers,
            mode.casefold(),
            source.strip(),
            destination.strip(),
            distance_source,
            distance_note,
        )
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    return jsonify(result)


@api.get("/destinations")
def destinations():
    records = get_destinations(current_app.config["DESTINATIONS_PATH"])
    query = request.args.get("q", "").strip()[:120].casefold()
    category = request.args.get("category", "").strip()[:80]
    records = filter_destinations(records, query, category or None)
    return jsonify([destination.to_dict() for destination in records])


@api.get("/geocode")
def geocode():
    query = request.args.get("q", "").strip()[:180]
    if len(query) < 3:
        return jsonify({"error": "Enter at least three characters to search for a location."}), 400
    try:
        results = geocode_locations(
            query,
            current_app.config["NOMINATIM_BASE_URL"],
            current_app.config["NOMINATIM_USER_AGENT"],
        )
    except MapServiceError as error:
        current_app.logger.warning("Nominatim lookup failed: %s", error)
        return jsonify({"error": "Location search is temporarily unavailable."}), 502
    return jsonify({"results": results})


@api.get("/route")
def road_route():
    coordinates = _read_coordinates(
        ("source_lat", "source_lon", "destination_lat", "destination_lon")
    )
    if coordinates is None:
        return jsonify({"error": "Provide valid source and destination coordinates."}), 400
    try:
        result = get_road_routes(
            *coordinates,
            current_app.config["OSRM_BASE_URL"],
            current_app.config["NOMINATIM_USER_AGENT"],
        )
    except MapServiceError as error:
        current_app.logger.warning("OSRM route request failed: %s", error)
        return jsonify({"error": "Road routing is temporarily unavailable."}), 502
    return jsonify(result)


@api.get("/nearby")
def nearby_places():
    category = request.args.get("category", "").strip().casefold()
    if category not in STANDARD_NEARBY_CATEGORIES:
        return jsonify({"error": "Choose a supported nearby category."}), 400
    coordinates = _read_coordinates(("lat", "lon"))
    if coordinates is None:
        return jsonify({"error": "Provide valid coordinates for the nearby search."}), 400
    try:
        radius = int(request.args.get("radius", "5000"))
    except ValueError:
        return jsonify({"error": "Nearby search radius must be a whole number."}), 400
    if not 250 <= radius <= 10000:
        return jsonify({"error": "Nearby search radius must be between 250 and 10000 metres."}), 400
    try:
        places = get_nearby_places(
            category,
            coordinates[0],
            coordinates[1],
            radius,
            current_app.config["OVERPASS_URL"],
            current_app.config["NOMINATIM_USER_AGENT"],
        )
    except MapServiceError as error:
        current_app.logger.warning("Nearby place search failed: %s", error)
        return jsonify({"error": "Nearby places are temporarily unavailable."}), 502
    return jsonify({"places": places})


@api.post("/safety/nearby")
def safety_nearby_places():
    if not isinstance(session.get("user_id"), int):
        return jsonify({"error": "Sign in to search for nearby safety services."}), 401
    if request.content_length is not None and request.content_length > 8192:
        return jsonify({"error": "Safety search requests must be 8 KB or smaller."}), 413

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "Send the nearby search as a JSON object."}), 400
    csrf_token = payload.get("csrf_token")
    if not isinstance(csrf_token, str) or not valid_csrf_token(csrf_token):
        return jsonify({"error": "Your session token expired. Reload the page and try again."}), 400

    category = payload.get("category")
    if not isinstance(category, str) or category not in SAFETY_NEARBY_CATEGORIES:
        return jsonify({"error": "Choose hospitals or police stations."}), 400
    try:
        coordinates = _read_point(payload.get("coordinates"))
        radius = payload.get("radius", 5000)
        if isinstance(radius, bool) or not isinstance(radius, int) or not 250 <= radius <= 10000:
            raise ValueError("Nearby search radius must be from 250 to 10000 metres.")
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    if coordinates is None:
        return jsonify({"error": "Provide valid coordinates for the nearby search."}), 400

    try:
        places = get_nearby_places(
            category,
            coordinates[0],
            coordinates[1],
            radius,
            current_app.config["OVERPASS_URL"],
            current_app.config["NOMINATIM_USER_AGENT"],
        )
    except MapServiceError as error:
        current_app.logger.warning("Safety nearby-place lookup failed: %s", error)
        return jsonify({"error": "Nearby safety services are temporarily unavailable."}), 502
    return jsonify({"places": places})


@api.get("/cultural-events")
def cultural_events():
    category = request.args.get("category", "").strip().casefold()
    if category and category not in CULTURAL_EVENT_CATEGORIES:
        return jsonify({"error": "Choose a supported cultural event category."}), 400

    latitude = request.args.get("lat")
    longitude = request.args.get("lon")
    coordinates = None
    if latitude is not None or longitude is not None:
        coordinates = _read_coordinates(("lat", "lon"))
        if coordinates is None:
            return jsonify({"error": "Provide valid coordinates for the event search."}), 400

    try:
        radius = int(request.args.get("radius", "5000"))
    except ValueError:
        return jsonify({"error": "Event search radius must be a whole number."}), 400
    if not 250 <= radius <= 10000:
        return jsonify({"error": "Event search radius must be between 250 and 10000 metres."}), 400

    try:
        events = get_cultural_events(
            current_app.config["CULTURAL_EVENTS_PATH"],
            category=category,
            latitude=coordinates[0] if coordinates else None,
            longitude=coordinates[1] if coordinates else None,
            radius=radius,
        )
    except CulturalEventDataError:
        current_app.logger.exception("Verified cultural event data could not be loaded.")
        return jsonify({"error": "Verified cultural event listings are temporarily unavailable."}), 500
    return jsonify({"events": events})


def _read_coordinates(names: tuple[str, ...]) -> tuple[float, ...] | None:
    try:
        coordinates = tuple(float(request.args[name]) for name in names)
    except (KeyError, TypeError, ValueError):
        return None
    for index, value in enumerate(coordinates):
        lower_bound, upper_bound = (-90, 90) if index % 2 == 0 else (-180, 180)
        if not lower_bound <= value <= upper_bound:
            return None
    return coordinates


def _read_point(value: object) -> tuple[float, float] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("Location coordinates must be an object.")
    latitude = value.get("latitude")
    longitude = value.get("longitude")
    if isinstance(latitude, bool) or isinstance(longitude, bool):
        raise ValueError("Location coordinates must be numeric.")
    try:
        latitude = float(latitude)
        longitude = float(longitude)
    except (TypeError, ValueError) as error:
        raise ValueError("Provide valid coordinates for both locations.") from error
    if (
        not math.isfinite(latitude)
        or not math.isfinite(longitude)
        or not -90 <= latitude <= 90
        or not -180 <= longitude <= 180
    ):
        raise ValueError("Location coordinates must be within valid map bounds.")
    return latitude, longitude


def _read_travellers(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 1000:
        raise ValueError("Number of travellers must be a whole number from 1 to 1000.")
    return value


def _read_manual_distance(value: object) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Travel distance must be a positive number of kilometres.")
    distance = float(value)
    if not math.isfinite(distance) or not 0 < distance <= 50000:
        raise ValueError("Travel distance must be greater than 0 and no more than 50,000 km.")
    return distance
