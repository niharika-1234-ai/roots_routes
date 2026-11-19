from __future__ import annotations

import json
import sqlite3
from typing import Any
from urllib.parse import urlsplit

from services.budget_service import BudgetValidationError, calculate_trip_budget


class ItineraryValidationError(ValueError):
    """Raised when an itinerary save request is invalid."""


class ItineraryStorageError(RuntimeError):
    """Raised when a saved itinerary cannot be read from storage."""


def save_itinerary(
    connection: sqlite3.Connection,
    user_id: int,
    title: object,
    destination_ids: object,
    itinerary: object,
    budget: object,
    known_destinations: dict[str, str],
) -> int:
    normalized_title = _read_text(title, "Enter an itinerary name.", 80)
    if not isinstance(destination_ids, list) or len(destination_ids) > 5:
        raise ItineraryValidationError("Choose up to five catalogue destinations.")
    if (
        any(not isinstance(item, str) or item not in known_destinations for item in destination_ids)
        or len(set(destination_ids)) != len(destination_ids)
    ):
        raise ItineraryValidationError("Choose different destinations from the catalogue.")
    if not isinstance(itinerary, dict):
        raise ItineraryValidationError("Generate an itinerary before saving it.")

    answer = _read_text(itinerary.get("answer"), "The itinerary draft is missing its outline.", 8000)
    mode = itinerary.get("mode")
    if not isinstance(mode, str) or mode not in {"rules", "ai"}:
        raise ItineraryValidationError("The itinerary draft has an unsupported generation mode.")
    notice = itinerary.get("notice", "")
    if not isinstance(notice, str) or len(notice) > 1000:
        raise ItineraryValidationError("The itinerary notice is invalid.")
    sources = _read_sources(itinerary.get("sources", []))
    estimate = _recalculate_budget(budget)
    saved_document = {
        "answer": answer,
        "mode": mode,
        "notice": notice,
        "sources": sources,
        "budget": estimate,
    }

    cursor = connection.execute(
        """
        INSERT INTO saved_trips (user_id, title, destination_ids, itinerary_json)
        VALUES (?, ?, ?, ?)
        """,
        (
            user_id,
            normalized_title,
            json.dumps(destination_ids, ensure_ascii=False),
            json.dumps(saved_document, ensure_ascii=False, separators=(",", ":")),
        ),
    )
    return int(cursor.lastrowid)


def get_saved_itineraries(
    connection: sqlite3.Connection,
    user_id: int,
    known_destinations: dict[str, str],
) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT id, title, destination_ids, itinerary_json, created_at
        FROM saved_trips
        WHERE user_id = ?
        ORDER BY created_at DESC, id DESC
        """,
        (user_id,),
    ).fetchall()
    itineraries = []
    for row in rows:
        try:
            destination_ids = json.loads(row["destination_ids"])
            document = json.loads(row["itinerary_json"])
        except (json.JSONDecodeError, TypeError) as error:
            raise ItineraryStorageError(
                f"Saved itinerary {row['id']} contains invalid JSON."
            ) from error
        if (
            not isinstance(destination_ids, list)
            or any(not isinstance(item, str) for item in destination_ids)
            or not isinstance(document, dict)
        ):
            raise ItineraryStorageError(f"Saved itinerary {row['id']} has invalid contents.")
        itineraries.append(
            {
                "id": row["id"],
                "title": row["title"],
                "created_at": row["created_at"],
                "destination_ids": destination_ids,
                "destination_names": [
                    known_destinations[destination_id]
                    for destination_id in destination_ids
                    if destination_id in known_destinations
                ],
                "itinerary": document,
            }
        )
    return itineraries


def delete_saved_itinerary(
    connection: sqlite3.Connection,
    user_id: int,
    itinerary_id: int,
) -> bool:
    cursor = connection.execute(
        "DELETE FROM saved_trips WHERE id = ? AND user_id = ?",
        (itinerary_id, user_id),
    )
    return cursor.rowcount == 1


def _read_text(value: object, error_message: str, maximum_length: int) -> str:
    if not isinstance(value, str):
        raise ItineraryValidationError(error_message)
    result = value.strip()
    if not result or len(result) > maximum_length:
        raise ItineraryValidationError(error_message)
    return result


def _read_sources(value: object) -> list[dict[str, str]]:
    if not isinstance(value, list) or len(value) > 20:
        raise ItineraryValidationError("The itinerary sources are invalid.")
    sources = []
    for source in value:
        if not isinstance(source, dict):
            raise ItineraryValidationError("The itinerary sources are invalid.")
        label = _read_text(source.get("label"), "A source label is invalid.", 120)
        url = _read_text(source.get("url"), "A source URL is invalid.", 2048)
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or not parsed.netloc
            or parsed.username
            or parsed.password
        ):
            raise ItineraryValidationError("Itinerary sources must use secure HTTPS links.")
        sources.append({"label": label, "url": url})
    return sources


def _recalculate_budget(value: object) -> dict[str, Any]:
    if not isinstance(value, dict) or not isinstance(value.get("inputs"), dict):
        raise ItineraryValidationError("The itinerary budget data is invalid.")
    inputs = value["inputs"]
    budget_payload = {
        **inputs,
        "expense_overrides": value.get("expense_overrides", {}),
    }
    try:
        return calculate_trip_budget(budget_payload)
    except BudgetValidationError as error:
        raise ItineraryValidationError("The itinerary budget data is invalid.") from error
