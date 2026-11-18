from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from models.destination import Destination
from services.event_service import get_cultural_events
from services.map_service import MapServiceError, get_nearby_places

logger = logging.getLogger(__name__)

MAX_MESSAGE_LENGTH = 1200
MAX_CONTEXT_DESTINATIONS = 5
MAX_CONTEXT_INTERESTS = 5
EVENTS_SOURCE_URL = "https://tourism.jharkhand.gov.in/festivals"
_INTEREST_PATTERNS = {
    "waterfalls": ("waterfall", "falls"),
    "culture": ("culture", "cultural", "festival", "tribal"),
    "accommodation": ("hotel", "stay", "homestay", "resort", "accommodation"),
    "food": ("restaurant", "food", "cuisine", "eat"),
    "quiet_places": ("crowd", "crowded", "quiet", "hidden gem", "less busy"),
}
_DAY_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}


class LLMServiceError(Exception):
    """Raised when an optional OpenAI-compatible provider cannot answer safely."""


def empty_itinerary_context() -> dict[str, Any]:
    return {
        "duration_days": None,
        "budget_inr": None,
        "destination_ids": [],
        "destination_names": [],
        "interests": [],
    }


def answer_travel_question(
    message: str,
    destinations: list[Destination],
    current_context: object,
    *,
    events_path: str | Path,
    overpass_url: str,
    user_agent: str,
    llm_api_key: str = "",
    llm_endpoint: str = "",
    llm_model: str = "",
) -> dict[str, Any]:
    if any(
        phrase in message.casefold()
        for phrase in ("clear trip context", "clear my itinerary", "reset itinerary")
    ):
        return {
            "answer": "Your trip context has been cleared for this session.",
            "context": empty_itinerary_context(),
            "sources": [],
            "mode": "rules",
            "notice": "",
        }

    context = _update_context(message, current_context, destinations)
    intent = _classify_intent(message)
    answer, sources, evidence, can_use_llm, notice = _rule_based_answer(
        message,
        intent,
        destinations,
        context,
        events_path,
        overpass_url,
        user_agent,
    )
    mode = "rules"
    if llm_api_key and can_use_llm:
        try:
            answer = _request_llm_answer(
                intent,
                answer,
                evidence,
                llm_api_key,
                llm_endpoint,
                llm_model,
            )
            mode = "ai"
        except LLMServiceError as error:
            logger.warning("Travel companion LLM request failed: %s", error)
            notice = "The AI provider is unavailable; this answer uses the local sourced-data response."
    elif llm_api_key and not can_use_llm:
        notice = "The local sourced-data response is used because this request lacks enough verified evidence for AI generation."

    return {
        "answer": answer,
        "context": context,
        "sources": sources,
        "mode": mode,
        "notice": notice,
    }


def _update_context(
    message: str,
    current_context: object,
    destinations: list[Destination],
) -> dict[str, Any]:
    normalized_message = message.casefold()
    if any(
        phrase in normalized_message
        for phrase in ("clear trip context", "clear my itinerary", "reset itinerary")
    ):
        return empty_itinerary_context()

    context = _normalize_context(current_context, destinations)
    day_match = re.search(
        r"\b(\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten)"
        r"\s*[- ]?days?\b",
        normalized_message,
    )
    if day_match:
        raw_days = day_match.group(1)
        days = int(raw_days) if raw_days.isdigit() else _DAY_WORDS[raw_days]
        if 1 <= days <= 30:
            context["duration_days"] = days

    budget_match = re.search(
        r"(?:₹|rs\.?\s*|inr\s*)([\d,]+)|\b([\d,]+)\s*(?:inr|rupees?)\b",
        normalized_message,
    )
    if budget_match:
        raw_budget = (budget_match.group(1) or budget_match.group(2)).replace(",", "")
        if len(raw_budget) <= 8:
            budget = int(raw_budget)
            if 1 <= budget <= 10_000_000:
                context["budget_inr"] = budget

    by_id = {destination.id: destination for destination in destinations}
    matched = [
        destination
        for destination in destinations
        if destination.name.casefold() in normalized_message
    ]
    if not matched and context["destination_ids"]:
        if "first one" in normalized_message or "first destination" in normalized_message:
            first = by_id.get(context["destination_ids"][0])
            if first:
                matched = [first]
        elif any(
            phrase in normalized_message
            for phrase in ("there", "that place", "those places", "nearby", "the same place")
        ):
            matched = [
                by_id[destination_id]
                for destination_id in context["destination_ids"]
                if destination_id in by_id
            ]

    if not matched and "waterfall" in normalized_message:
        mentioned_districts = {
            destination.district.casefold()
            for destination in destinations
            if destination.district.casefold() in normalized_message
        }
        if mentioned_districts:
            matched = [
                destination
                for destination in destinations
                if destination.district.casefold() in mentioned_districts
                and "waterfall" in destination.category.casefold()
            ]

    existing_ids = context["destination_ids"]
    new_ids = [destination.id for destination in matched]
    context["destination_ids"] = list(
        dict.fromkeys(new_ids + existing_ids)
    )[:MAX_CONTEXT_DESTINATIONS]
    context["destination_names"] = [
        by_id[destination_id].name
        for destination_id in context["destination_ids"]
        if destination_id in by_id
    ]

    interests = context["interests"]
    for interest, patterns in _INTEREST_PATTERNS.items():
        if any(pattern in normalized_message for pattern in patterns) and interest not in interests:
            interests.append(interest)
    context["interests"] = interests[:MAX_CONTEXT_INTERESTS]
    return context


def _normalize_context(
    value: object,
    destinations: list[Destination],
) -> dict[str, Any]:
    context = empty_itinerary_context()
    if not isinstance(value, dict):
        return context

    duration = value.get("duration_days")
    if isinstance(duration, int) and not isinstance(duration, bool) and 1 <= duration <= 30:
        context["duration_days"] = duration

    budget = value.get("budget_inr")
    if isinstance(budget, int) and not isinstance(budget, bool) and 1 <= budget <= 10_000_000:
        context["budget_inr"] = budget

    known_ids = {destination.id for destination in destinations}
    raw_ids = value.get("destination_ids")
    if isinstance(raw_ids, list):
        context["destination_ids"] = list(
            dict.fromkeys(
                item for item in raw_ids
                if isinstance(item, str) and item in known_ids
            )
        )[:MAX_CONTEXT_DESTINATIONS]

    raw_interests = value.get("interests")
    if isinstance(raw_interests, list):
        context["interests"] = list(
            dict.fromkeys(
                item for item in raw_interests
                if isinstance(item, str) and item in _INTEREST_PATTERNS
            )
        )[:MAX_CONTEXT_INTERESTS]

    by_id = {destination.id: destination for destination in destinations}
    context["destination_names"] = [
        by_id[destination_id].name
        for destination_id in context["destination_ids"]
        if destination_id in by_id
    ]
    return context


def _classify_intent(message: str) -> str:
    lowered = message.casefold()
    asks_for_trip = any(word in lowered for word in ("trip", "itinerary", "travel plan"))
    has_trip_constraint = re.search(
        r"\b(\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten)"
        r"\s*[- ]?days?\b|(?:₹|rs\.?\s*|inr\s*)[\d,]+",
        lowered,
    )
    if asks_for_trip and has_trip_constraint:
        return "trip"
    if any(word in lowered for word in ("hotel", "homestay", "resort", "accommodation", "stay")):
        return "hotels"
    if any(word in lowered for word in ("restaurant", "cuisine", "food", "eat")):
        return "restaurants"
    if any(word in lowered for word in ("crowd", "crowded", "quiet", "hidden gem", "less busy")):
        return "crowds"
    if any(word in lowered for word in ("cultural", "culture", "festival", "tribal dance", "sarhul", "karma", "sohrai", "handicraft")):
        return "culture"
    if "waterfall" in lowered or "falls" in lowered:
        return "waterfalls"
    if any(word in lowered for word in ("trip", "itinerary", "travel plan")):
        return "trip"
    return "destination"


def _rule_based_answer(
    message: str,
    intent: str,
    destinations: list[Destination],
    context: dict[str, Any],
    events_path: str,
    overpass_url: str,
    user_agent: str,
) -> tuple[str, list[dict[str, str]], dict[str, Any], bool, str]:
    lowered = message.casefold()
    selected = [
        destination
        for destination in destinations
        if destination.id in context["destination_ids"]
    ]
    sources: list[dict[str, str]] = []
    evidence: dict[str, Any] = {"intent": intent, "destinations": []}
    notice = ""

    if intent == "waterfalls":
        named_waterfalls = [
            destination
            for destination in destinations
            if "waterfall" in destination.category.casefold()
            and destination.name.casefold() in lowered
        ]
        if named_waterfalls and not any(
            word in lowered for word in ("near", "nearby", "around", "which", "list")
        ):
            evidence["destinations"] = [
                _destination_evidence(item) for item in named_waterfalls
            ]
            return (
                "\n".join(
                    f"{item.name} is listed in {item.district} district as {item.category}. "
                    f"{item.description}"
                    for item in named_waterfalls
                ),
                _destination_sources(named_waterfalls),
                evidence,
                True,
                notice,
            )
        waterfalls = [
            destination for destination in destinations
            if "waterfall" in destination.category.casefold()
        ]
        districts = [
            district for district in dict.fromkeys(
                destination.district for destination in destinations
            )
            if district.casefold() in lowered
        ]
        if districts:
            waterfalls = [
                destination for destination in waterfalls
                if destination.district.casefold() in {item.casefold() for item in districts}
            ]
        if waterfalls:
            location_note = (
                f" in {', '.join(districts)} district"
                if districts
                else ""
            )
            names = ", ".join(destination.name for destination in waterfalls)
            answer = (
                f"The destination catalogue lists these waterfalls{location_note}: {names}. "
                "A district match does not establish road distance or travel time."
            )
            sources = _destination_sources(waterfalls)
            evidence["destinations"] = [_destination_evidence(item) for item in waterfalls]
            return answer, sources, evidence, True, notice
        return (
            "I couldn't find a matching waterfall in the current destination catalogue. "
            "Try a district or browse Explore Destinations.",
            sources,
            evidence,
            False,
            notice,
        )

    if intent in {"hotels", "restaurants"}:
        destination = _nearby_target(message, selected, destinations)
        if destination is None:
            return (
                "Which Jharkhand destination should I search near? I can check mapped "
                "OpenStreetMap listings once you choose a place.",
                sources,
                evidence,
                False,
                notice,
            )
        category = intent
        evidence["destinations"] = [_destination_evidence(destination)]
        sources = _destination_sources([destination])
        try:
            places = get_nearby_places(
                category,
                destination.latitude,
                destination.longitude,
                5000,
                overpass_url,
                user_agent,
            )
        except MapServiceError as error:
            logger.warning("Travel companion nearby search failed: %s", error)
            module_name = "hotel and stay" if category == "hotels" else "restaurant"
            return (
                f"The OpenStreetMap {module_name} search is temporarily unavailable near "
                f"{destination.name}. Please try again or open the {module_name.title()} module.",
                sources,
                evidence,
                False,
                "The OpenStreetMap provider did not return a usable response.",
            )
        if not places:
            return (
                f"OpenStreetMap returned no named {category} listings within 5 km of "
                f"{destination.name}. This does not confirm that no businesses exist. "
                "Distances, when available, are straight-line estimates.",
                sources,
                evidence,
                False,
                notice,
            )
        lines = []
        for place in places[:6]:
            details = [str(place.get("place_type") or "").strip()]
            if place.get("cuisine"):
                details.append(f"cuisine: {place['cuisine']}")
            if place.get("distance_km") is not None:
                details.append(f"{place['distance_km']} km straight-line")
            if place.get("rating"):
                details.append(f"mapped rating: {place['rating']}")
            if place.get("price"):
                details.append(f"mapped price: {place['price']}")
            lines.append(f"- {place['name']} ({'; '.join(item for item in details if item)})")
            source_url = place.get("source_url")
            if isinstance(source_url, str) and source_url.startswith("https://"):
                sources.append({"label": str(place["name"]), "url": source_url})
            booking_url = place.get("booking_url")
            if isinstance(booking_url, str) and booking_url.startswith("https://"):
                sources.append({"label": f"{place['name']} booking link", "url": booking_url})
        evidence["nearby_places"] = [
            {
                key: place.get(key)
                for key in (
                    "name", "place_type", "distance_km", "cuisine",
                    "rating", "price", "source_url", "booking_url",
                )
            }
            for place in places[:6]
        ]
        category_label = "restaurants" if category == "restaurants" else "stays"
        answer = (
            f"Mapped {category_label} within 5 km of {destination.name} "
            "(distance is straight-line; prices and ratings appear only when mapped):\n"
            + "\n".join(lines)
        )
        requested_place_in_message = destination.name.casefold() in lowered
        return (
            answer,
            _unique_sources(sources),
            evidence,
            requested_place_in_message,
            notice,
        )

    if intent == "culture":
        events = get_cultural_events(events_path)
        if events:
            lines = []
            for event in events[:6]:
                line = (
                    f"- {event['name']}: {event['start_date']} to {event['end_date']} "
                    f"at {event['venue']} ({event['district']})"
                )
                lines.append(line)
                sources.append(
                    {"label": str(event["source_name"]), "url": str(event["source_url"])}
                )
            evidence["events"] = events[:6]
            return (
                "These upcoming cultural events have verified dates, venues, and sources:\n"
                + "\n".join(lines),
                _unique_sources(sources),
                evidence,
                True,
                notice,
            )
        return (
            "I don't have any upcoming cultural event records with verified dates and venues "
            "in the current catalogue. The Jharkhand Tourism festival page gives cultural "
            "context, not a current event schedule.",
            [{"label": "Jharkhand Tourism festival information", "url": EVENTS_SOURCE_URL}],
            evidence,
            False,
            notice,
        )

    if intent == "crowds":
        assessed = [
            destination for destination in destinations
            if destination.popularity is not None and destination.popularity_source
        ]
        if assessed:
            assessed.sort(key=lambda item: item.popularity)
            evidence["destinations"] = [_destination_evidence(item) for item in assessed[:6]]
            return (
                "Destinations with sourced popularity scores, lowest score first: "
                + ", ".join(
                    f"{item.name} ({item.popularity}/100)"
                    for item in assessed[:6]
                )
                + ". A popularity score is not a live crowd count.",
                _destination_sources(assessed[:6]),
                evidence,
                True,
                notice,
            )
        return (
            "I can't identify less-crowded destinations from this catalogue: it has no "
            "source-backed popularity or visitor-count data. Hidden Gems only ranks places "
            "when all five measures have evidence.",
            sources,
            evidence,
            False,
            notice,
        )

    if intent == "trip":
        days = context["duration_days"]
        budget = context["budget_inr"]
        if not days:
            budget_note = (
                f" I recorded a budget of ₹{budget:,}, but current travel, accommodation, "
                "meal, and entry prices are not available to verify it."
                if budget
                else ""
            )
            return (
                "How many days should I plan for? I don't have sourced current transport, "
                "accommodation, meal, or entry prices, so I can't verify a trip budget."
                + budget_note,
                sources,
                evidence,
                False,
                notice,
            )
        candidates = selected or [
            destination
            for destination in destinations
            if not any(
                word in lowered
                for word in ("culture", "cultural", "hotel", "restaurant")
            )
        ]
        candidates = candidates[:days]
        evidence["destinations"] = [_destination_evidence(item) for item in candidates]
        sources = _destination_sources(candidates)
        if candidates:
            outline = "\n".join(
                f"Day {index}: {destination.name} — {destination.district} district."
                for index, destination in enumerate(candidates, start=1)
            )
            plan_note = (
                f"This is a destinations-only draft for {days} days, not a route-optimized plan."
            )
        else:
            outline = ""
            plan_note = "I don't have enough matching destination records for a day-by-day outline."
        budget_note = (
            f" I recorded your ₹{budget:,} budget, but can't confirm the trip fits: verified "
            "transport, accommodation, meal, and entry prices are not in the catalogue."
            if budget
            else " Current transport, accommodation, meal, and entry prices are not in the "
            "catalogue, so I can't estimate or verify the total cost."
        )
        answer = " ".join(part for part in (plan_note, outline, budget_note) if part)
        return answer, sources, evidence, False, notice

    named = [
        destination
        for destination in destinations
        if destination.name.casefold() in lowered
    ]
    if named:
        evidence["destinations"] = [_destination_evidence(item) for item in named[:5]]
        sources = _destination_sources(named[:5])
        lines = [
            f"{item.name} is listed in {item.district} district as {item.category}. "
            f"{item.description}"
            for item in named[:5]
        ]
        return "\n".join(lines), sources, evidence, True, notice

    if selected:
        evidence["destinations"] = [_destination_evidence(item) for item in selected]
        return (
            "Your current trip context includes "
            + ", ".join(item.name for item in selected)
            + ". Ask about a mapped stay or restaurant, a sourced destination fact, or a "
            "verified event. I can't verify prices or live crowd levels from the current data.",
            _destination_sources(selected),
            evidence,
            False,
            notice,
        )

    return (
        "I can look up facts from the Jharkhand destination catalogue, nearby OpenStreetMap "
        "restaurants and stays, and event listings with verified schedules. Try asking about "
        "waterfalls near Ranchi or hotels near a listed destination. Current trip prices and "
        "live crowd levels aren't available unless a source is provided.",
        sources,
        evidence,
        False,
        notice,
    )


def _nearby_target(
    message: str,
    selected: list[Destination],
    destinations: list[Destination],
) -> Destination | None:
    lowered = message.casefold()
    named = [
        destination for destination in destinations
        if destination.name.casefold() in lowered
    ]
    if named:
        return named[0]
    if selected:
        if "first one" in lowered or "first destination" in lowered:
            return selected[0]
        return selected[0]
    return None


def _destination_evidence(destination: Destination) -> dict[str, Any]:
    return {
        "name": destination.name,
        "district": destination.district,
        "category": destination.category,
        "description": destination.description,
        "latitude": destination.latitude,
        "longitude": destination.longitude,
        "popularity": destination.popularity,
        "popularity_source": destination.popularity_source,
        "source_url": destination.source_url,
    }


def _destination_sources(destinations: list[Destination]) -> list[dict[str, str]]:
    return _unique_sources(
        [
            {"label": destination.name, "url": destination.source_url}
            for destination in destinations
            if destination.source_url.startswith("https://")
        ]
    )


def _unique_sources(sources: list[dict[str, str]]) -> list[dict[str, str]]:
    unique: dict[str, dict[str, str]] = {}
    for source in sources:
        if source.get("url", "").startswith("https://"):
            unique.setdefault(source["url"], source)
    return list(unique.values())[:10]


def _request_llm_answer(
    intent: str,
    grounded_draft: str,
    evidence: dict[str, Any],
    api_key: str,
    endpoint: str,
    model: str,
) -> str:
    try:
        parsed_url = urlsplit(endpoint)
        hostname = parsed_url.hostname
    except ValueError as error:
        raise LLMServiceError("The configured provider URL is invalid.") from error
    local_http = hostname in {"localhost", "127.0.0.1", "::1"}
    if (
        parsed_url.scheme not in {"https", "http"}
        or not hostname
        or (parsed_url.scheme == "http" and not local_http)
    ):
        raise LLMServiceError("The configured provider URL must use HTTPS.")

    prompt_data = {
        "request_category": intent,
        "grounded_draft": grounded_draft,
        "verified_evidence": evidence,
    }
    request_body = json.dumps(
        {
            "model": model,
            "temperature": 0,
            "max_tokens": 500,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are the ROOTS & ROUTES Jharkhand travel companion. Improve the "
                        "grounded draft using only the supplied verified evidence. "
                        "Never invent prices, ratings, event dates, crowd levels, travel times, "
                        "availability, or destination facts. Preserve every limitation and "
                        "uncertainty in the draft. If evidence is missing, say so plainly. "
                        "Do not claim a trip fits a budget unless the evidence proves it. "
                        "Do not add facts that are absent from the draft."
                    ),
                },
                {"role": "user", "content": json.dumps(prompt_data, ensure_ascii=False)},
            ],
        }
    ).encode("utf-8")
    request = Request(
        endpoint,
        data=request_body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=18) as response:
            payload = json.loads(response.read())
    except HTTPError as error:
        raise LLMServiceError(f"The configured provider returned HTTP {error.code}.") from error
    except (URLError, TimeoutError, OSError) as error:
        raise LLMServiceError("The configured provider could not be reached.") from error
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise LLMServiceError("The configured provider returned invalid JSON.") from error

    try:
        answer = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as error:
        raise LLMServiceError("The configured provider returned an unsupported response.") from error
    if not isinstance(answer, str) or not answer.strip():
        raise LLMServiceError("The configured provider returned an empty answer.")
    return answer.strip()[:4000]
