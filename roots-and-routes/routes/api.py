import math
import sqlite3
from datetime import date

from flask import Blueprint, current_app, jsonify, request, session

from database import get_db
from services.dashboard_service import filter_destinations, rank_hidden_gems
from services.destination_service import get_destinations
from services.carbon_service import (
    CarbonFactorDataError,
    calculate_carbon_footprint,
    get_transport_factors,
)
from services.budget_service import (
    ACCOMMODATION_PREFERENCES,
    FOOD_PREFERENCES,
    TRAVEL_MODES,
    BudgetValidationError,
    calculate_trip_budget,
)
from services.event_service import (
    CULTURAL_EVENT_CATEGORIES,
    CulturalEventDataError,
    get_cultural_events,
)
from services.itinerary_service import (
    ItineraryStorageError,
    ItineraryValidationError,
    get_saved_itineraries,
    save_itinerary,
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
from services.crowd_service import CrowdDataError, build_crowd_dashboard
from services.weather_service import WeatherServiceError, get_destination_weather

api = Blueprint("api", __name__, url_prefix="/api")
SAFETY_NEARBY_CATEGORIES = frozenset({"hospitals", "police"})
STANDARD_NEARBY_CATEGORIES = NEARBY_CATEGORIES - SAFETY_NEARBY_CATEGORIES


@api.get("/health")
def health():
    return jsonify({"status": "ok"})


@api.get("/weather")
def destination_weather():
    if not isinstance(session.get("user_id"), int):
        return jsonify({"error": "Sign in to view destination weather."}), 401

    destination_id = request.args.get("destination_id", "").strip()
    if not destination_id or len(destination_id) > 80:
        return jsonify({"error": "Choose a destination from the catalogue."}), 400

    destinations = get_destinations(current_app.config["DESTINATIONS_PATH"])
    destination = next(
        (item for item in destinations if item.id == destination_id),
        None,
    )
    if destination is None:
        return jsonify({"error": "Choose a destination from the catalogue."}), 400
    if not current_app.config["OPENWEATHER_API_KEY"]:
        return jsonify(
            {
                "error": (
                    "Live weather is not configured. Add OPENWEATHER_API_KEY on the "
                    "server to retrieve current conditions and forecasts."
                )
            }
        ), 503

    try:
        weather = get_destination_weather(
            destination,
            current_app.config["OPENWEATHER_API_KEY"],
        )
    except WeatherServiceError as error:
        current_app.logger.warning("Live weather lookup failed: %s", error)
        return jsonify(
            {
                "error": (
                    "Live weather is temporarily unavailable. No current conditions "
                    "or forecast are being shown."
                )
            }
        ), 502
    return jsonify(weather)


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


@api.post("/budget-estimate")
def budget_estimate():
    if not isinstance(session.get("user_id"), int):
        return jsonify({"error": "Sign in to calculate a trip budget."}), 401
    if request.content_length is not None and request.content_length > 8192:
        return jsonify({"error": "Budget requests must be 8 KB or smaller."}), 413

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "Send the trip details as a JSON object."}), 400
    if not valid_csrf_token(payload.get("csrf_token")):
        return jsonify({"error": "Your session token expired. Reload the page and try again."}), 400

    try:
        estimate = calculate_trip_budget(payload)
    except BudgetValidationError as error:
        return jsonify({"error": str(error)}), 400
    return jsonify(estimate)


@api.post("/planner/generate")
def planner_generate():
    if not isinstance(session.get("user_id"), int):
        return jsonify({"error": "Sign in to generate an itinerary."}), 401
    if request.content_length is not None and request.content_length > 8192:
        return jsonify({"error": "Itinerary requests must be 8 KB or smaller."}), 413

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "Send the itinerary details as a JSON object."}), 400
    if not valid_csrf_token(payload.get("csrf_token")):
        return jsonify({"error": "Your session token expired. Reload the page and try again."}), 400

    try:
        estimate = calculate_trip_budget(payload)
    except BudgetValidationError as error:
        return jsonify({"error": str(error)}), 400

    raw_destination_ids = payload.get("destination_ids", [])
    if (
        not isinstance(raw_destination_ids, list)
        or len(raw_destination_ids) > 5
        or any(not isinstance(item, str) for item in raw_destination_ids)
        or len(set(raw_destination_ids)) != len(raw_destination_ids)
    ):
        return jsonify({"error": "Choose up to five different destinations."}), 400

    destinations = get_destinations(current_app.config["DESTINATIONS_PATH"])
    destination_by_id = {destination.id: destination for destination in destinations}
    if any(destination_id not in destination_by_id for destination_id in raw_destination_ids):
        return jsonify({"error": "Choose destinations from the Jharkhand catalogue."}), 400
    selected_destinations = [
        destination_by_id[destination_id] for destination_id in raw_destination_ids
    ]

    inputs = estimate["inputs"]
    category_totals = ", ".join(
        f"{category.replace('_', ' ')}: ₹{item['amount_inr']:,} "
        f"({'user-edited' if item['is_user_override'] else 'illustrative sample'})"
        for category, item in estimate["expenses"].items()
    )
    selected_names = ", ".join(
        destination.name for destination in selected_destinations
    ) or "suggest source-backed destinations from the catalogue"
    message = (
        f"Create a {inputs['days']}-day Jharkhand itinerary within "
        f"₹{inputs['budget_inr']:,} for {inputs['travellers']} travellers. "
        f"Focus destinations: {selected_names}. "
        f"Travel mode: {TRAVEL_MODES[inputs['travel_mode']]['label']}; "
        f"accommodation preference: "
        f"{ACCOMMODATION_PREFERENCES[inputs['accommodation_preference']]['label']}; "
        f"food preference: {FOOD_PREFERENCES[inputs['food_preference']]['label']}. "
        f"The editable budget calculator estimates these category totals: {category_totals}; "
        "non-edited rates are illustrative sample assumptions, not verified prices or quotes. "
        "Create a destinations-only draft using the catalogue. Do not claim the trip fits the "
        "budget, and do not invent activities, routes, travel times, access, or costs."
    )
    try:
        itinerary = answer_travel_question(
            message,
            destinations,
            None,
            events_path=current_app.config["CULTURAL_EVENTS_PATH"],
            overpass_url=current_app.config["OVERPASS_URL"],
            user_agent=current_app.config["NOMINATIM_USER_AGENT"],
            llm_api_key=current_app.config["TRAVEL_COMPANION_LLM_API_KEY"],
            llm_endpoint=current_app.config["TRAVEL_COMPANION_LLM_ENDPOINT"],
            llm_model=current_app.config["TRAVEL_COMPANION_LLM_MODEL"],
            allow_trip_ai=True,
            user_trip_constraints={
                "days": inputs["days"],
                "travellers": inputs["travellers"],
                "budget_inr": inputs["budget_inr"],
                "travel_mode": TRAVEL_MODES[inputs["travel_mode"]]["label"],
                "accommodation_preference": ACCOMMODATION_PREFERENCES[
                    inputs["accommodation_preference"]
                ]["label"],
                "food_preference": FOOD_PREFERENCES[inputs["food_preference"]]["label"],
                "estimated_costs_inr": {
                    category: expense["amount_inr"]
                    for category, expense in estimate["expenses"].items()
                },
                "estimates_are_illustrative": True,
            },
        )
    except CulturalEventDataError:
        current_app.logger.exception("Verified cultural event data could not be loaded for itinerary generation.")
        return jsonify({"error": "Verified travel data is temporarily unavailable."}), 500

    session["travel_companion_context"] = itinerary["context"]
    session.modified = True
    return jsonify({"budget": estimate, "itinerary": itinerary})


@api.get("/itineraries")
def saved_itineraries():
    user_id = session.get("user_id")
    if not isinstance(user_id, int):
        return jsonify({"error": "Sign in to view your saved itineraries."}), 401
    destinations = get_destinations(current_app.config["DESTINATIONS_PATH"])
    try:
        itineraries = get_saved_itineraries(
            get_db(),
            user_id,
            {destination.id: destination.name for destination in destinations},
        )
    except (sqlite3.Error, ItineraryStorageError):
        current_app.logger.exception("Saved itineraries could not be loaded for user %s.", user_id)
        return jsonify({"error": "Saved itineraries are temporarily unavailable."}), 500
    return jsonify({"itineraries": itineraries})


@api.post("/itineraries")
def save_saved_itinerary():
    user_id = session.get("user_id")
    if not isinstance(user_id, int):
        return jsonify({"error": "Sign in to save an itinerary."}), 401
    if request.content_length is not None and request.content_length > 16384:
        return jsonify({"error": "Saved itinerary requests must be 16 KB or smaller."}), 413
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "Send the itinerary details as a JSON object."}), 400
    if not valid_csrf_token(payload.get("csrf_token")):
        return jsonify({"error": "Your session token expired. Reload the page and try again."}), 400

    destinations = get_destinations(current_app.config["DESTINATIONS_PATH"])
    try:
        itinerary_id = save_itinerary(
            get_db(),
            user_id,
            payload.get("title"),
            payload.get("destination_ids"),
            payload.get("itinerary"),
            payload.get("budget"),
            {destination.id: destination.name for destination in destinations},
        )
        get_db().commit()
    except ItineraryValidationError as error:
        get_db().rollback()
        return jsonify({"error": str(error)}), 400
    except sqlite3.Error:
        get_db().rollback()
        current_app.logger.exception("Could not save itinerary for user %s.", user_id)
        return jsonify({"error": "The itinerary could not be saved right now."}), 500
    return jsonify({"id": itinerary_id, "status": "saved"}), 201


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


@api.get("/destination-intelligence")
def destination_intelligence():
    if not isinstance(session.get("user_id"), int):
        return jsonify({"error": "Sign in to view destination intelligence."}), 401
    destination_id = request.args.get("destination_id", "").strip()
    if not destination_id or len(destination_id) > 80:
        return jsonify({"error": "Choose a destination from the catalogue."}), 400
    destinations = get_destinations(current_app.config["DESTINATIONS_PATH"])
    destination = next((item for item in destinations if item.id == destination_id), None)
    if destination is None:
        return jsonify({"error": "Choose a destination from the catalogue."}), 400

    month = date.today().month
    try:
        crowd = build_crowd_dashboard(
            current_app.config["CROWD_HISTORY_PATH"],
            destinations,
            destination.id,
            month,
        )
    except (CrowdDataError, ValueError):
        current_app.logger.exception(
            "Crowd estimates are unavailable for destination %s.",
            destination.id,
        )
        return jsonify({"error": "The labelled crowd sample is temporarily unavailable."}), 500

    hidden_alternatives = [
        {
            "id": item["destination"].id,
            "name": item["destination"].name,
            "district": item["destination"].district,
            "category": item["destination"].category,
            "ranking_score": item["ranking_score"],
            "source_url": item["destination"].source_url,
        }
        for item in rank_hidden_gems(destinations)
        if item["destination"].id != destination.id
    ][:5]
    score_is_sourced = (
        destination.sustainability_score is not None
        and bool(destination.sustainability_score_source)
    )
    return jsonify(
        {
            "destination": {
                "id": destination.id,
                "name": destination.name,
                "district": destination.district,
                "category": destination.category,
                "description": destination.description,
                "latitude": destination.latitude,
                "longitude": destination.longitude,
                "source_url": destination.source_url,
                "coordinates_note": destination.coordinates_note,
            },
            "crowd": crowd,
            "sustainability": {
                "score": destination.sustainability_score if score_is_sourced else None,
                "source_url": destination.sustainability_score_source if score_is_sourced else "",
                "status": "sourced" if score_is_sourced else "not_assessed",
                "note": (
                    "A sourced catalogue score is available."
                    if score_is_sourced
                    else "No source-backed sustainability score is available for this destination."
                ),
            },
            "hidden_alternatives": hidden_alternatives,
            "hidden_alternatives_note": (
                "No destination currently meets all five source-backed hidden-gem criteria."
                if not hidden_alternatives
                else "Alternatives meet the catalogue's source-backed hidden-gem criteria."
            ),
        }
    )


@api.post("/intelligence/route-carbon")
def intelligence_route_carbon():
    if not isinstance(session.get("user_id"), int):
        return jsonify({"error": "Sign in to calculate a destination route."}), 401
    if request.content_length is not None and request.content_length > 8192:
        return jsonify({"error": "Route requests must be 8 KB or smaller."}), 413
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "Send the route details as a JSON object."}), 400
    if not valid_csrf_token(payload.get("csrf_token")):
        return jsonify({"error": "Your session token expired. Reload the page and try again."}), 400

    origin_id = payload.get("origin_id")
    destination_id = payload.get("destination_id")
    mode = payload.get("mode")
    if (
        not isinstance(origin_id, str)
        or not isinstance(destination_id, str)
        or origin_id == destination_id
        or not isinstance(mode, str)
    ):
        return jsonify({"error": "Choose different starting and destination catalogue places."}), 400
    try:
        travellers = _read_travellers(payload.get("travellers"))
    except ValueError as error:
        return jsonify({"error": str(error)}), 400

    destinations = get_destinations(current_app.config["DESTINATIONS_PATH"])
    destination_by_id = {item.id: item for item in destinations}
    origin = destination_by_id.get(origin_id)
    destination = destination_by_id.get(destination_id)
    if origin is None or destination is None:
        return jsonify({"error": "Choose route places from the destination catalogue."}), 400

    try:
        route_result = get_road_routes(
            origin.latitude,
            origin.longitude,
            destination.latitude,
            destination.longitude,
            current_app.config["OSRM_BASE_URL"],
            current_app.config["NOMINATIM_USER_AGENT"],
        )
    except MapServiceError as error:
        current_app.logger.warning("Destination intelligence OSRM lookup failed: %s", error)
        return jsonify({"error": "Road routing is temporarily unavailable."}), 502
    routes = route_result.get("routes")
    if route_result.get("code") != "Ok" or not isinstance(routes, list) or not routes:
        return jsonify({"error": "OSRM could not find a road route for these places."}), 502

    route_summaries = []
    selected_distance_km = None
    for index, route in enumerate(routes[:3]):
        if not isinstance(route, dict):
            continue
        try:
            distance_km_value = float(route["distance"]) / 1000
            duration_minutes = float(route["duration"]) / 60
        except (KeyError, TypeError, ValueError):
            continue
        if (
            not math.isfinite(distance_km_value)
            or not math.isfinite(duration_minutes)
            or not 0 < distance_km_value <= 50000
            or duration_minutes < 0
        ):
            continue
        if selected_distance_km is None:
            selected_distance_km = distance_km_value
        route_summaries.append(
            {
                "label": "Recommended road route" if index == 0 else f"Alternative {index}",
                "distance_km": round(distance_km_value, 2),
                "duration_minutes": round(duration_minutes),
            }
        )
    if selected_distance_km is None:
        return jsonify({"error": "OSRM returned no usable road distance."}), 502

    try:
        factors = get_transport_factors(
            current_app.config["TRANSPORT_EMISSION_FACTORS_PATH"]
        )
        carbon = calculate_carbon_footprint(
            factors,
            selected_distance_km,
            travellers,
            mode,
            origin.name,
            destination.name,
            "osrm",
            (
                "OSRM driving-road distance for one trip, used as the common distance "
                "basis for transport-mode comparison. Actual bus and rail routes may differ."
            ),
        )
    except CarbonFactorDataError:
        current_app.logger.exception("Transport emissions factors are unavailable or invalid.")
        return jsonify({"error": "Transport emissions factors are temporarily unavailable."}), 500
    except ValueError as error:
        return jsonify({"error": str(error)}), 400

    return jsonify(
        {
            "origin": {"id": origin.id, "name": origin.name, "district": origin.district},
            "destination": {
                "id": destination.id,
                "name": destination.name,
                "district": destination.district,
            },
            "routes": route_summaries,
            "provider": "OSRM",
            "route_note": (
                "Driving-route estimates may differ from actual bus or rail journeys and "
                "do not include live traffic or confirm road access."
            ),
            "carbon": carbon,
        }
    )


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
    for event in events:
        if event.get("source_name") == "Roots & Routes prototype dataset":
            event["is_synthetic"] = True
            event["verification_note"] = "Synthetic demo record; not an officially confirmed 2027 schedule."
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
