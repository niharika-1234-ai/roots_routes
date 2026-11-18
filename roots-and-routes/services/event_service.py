from __future__ import annotations

import csv
import math
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

from services.map_service import distance_km


CULTURAL_EVENT_CATEGORIES = {
    "sarhul": "Sarhul",
    "karma": "Karma festival",
    "sohrai": "Sohrai exhibitions",
    "tribal-dance": "Tribal dance performances",
    "local-fairs": "Local fairs",
    "handicrafts": "Handicraft exhibitions",
}
RELIABLE_SOURCE_TYPES = {"government", "organizer", "venue"}

REQUIRED_COLUMNS = {
    "event_id",
    "name",
    "category",
    "start_date",
    "end_date",
    "venue",
    "district",
    "latitude",
    "longitude",
    "description",
    "source_type",
    "source_name",
    "source_url",
    "verified_on",
}


class CulturalEventDataError(Exception):
    """Raised when a scheduled cultural event record is invalid."""


def get_cultural_events(
    csv_path: str | Path,
    category: str = "",
    latitude: float | None = None,
    longitude: float | None = None,
    radius: int = 5000,
    today: date | None = None,
) -> list[dict[str, object]]:
    if category and category not in CULTURAL_EVENT_CATEGORIES:
        raise ValueError("Unsupported cultural event category.")
    if (latitude is None) != (longitude is None):
        raise ValueError("Both coordinates are required for nearby events.")
    if not 250 <= radius <= 10000:
        raise ValueError("Event search radius must be between 250 and 10000 metres.")
    if latitude is not None and longitude is not None and (
        not math.isfinite(latitude)
        or not math.isfinite(longitude)
        or not -90 <= latitude <= 90
        or not -180 <= longitude <= 180
    ):
        raise ValueError("Event search coordinates are invalid.")

    current_date = today or date.today()
    try:
        with Path(csv_path).open(encoding="utf-8-sig", newline="") as event_file:
            reader = csv.DictReader(event_file)
            missing_columns = REQUIRED_COLUMNS - set(reader.fieldnames or ())
            if missing_columns:
                raise CulturalEventDataError(
                    "The cultural event catalogue is missing required columns."
                )
            events = [
                _read_event(row, row_number, current_date)
                for row_number, row in enumerate(reader, start=2)
            ]
    except (OSError, UnicodeError, csv.Error) as error:
        raise CulturalEventDataError("The cultural event catalogue could not be read.") from error

    results = []
    seen_ids: set[str] = set()
    for event in events:
        if event["event_id"] in seen_ids:
            raise CulturalEventDataError("The cultural event catalogue contains duplicate IDs.")
        seen_ids.add(str(event["event_id"]))
        if event["end_date"] < current_date.isoformat():
            continue
        if category and event["category"] != category:
            continue
        if latitude is not None and longitude is not None:
            distance = distance_km(
                latitude,
                longitude,
                float(event["latitude"]),
                float(event["longitude"]),
            )
            if distance * 1000 > radius:
                continue
            event["distance_km"] = round(distance, 2)
        results.append(event)

    return sorted(results, key=lambda event: (event["start_date"], event["name"]))


def _read_event(
    row: dict[str, str | None],
    row_number: int,
    current_date: date,
) -> dict[str, object]:
    record = {key: (row.get(key) or "").strip() for key in REQUIRED_COLUMNS}
    if any(not value for value in record.values()):
        raise CulturalEventDataError(
            f"The cultural event catalogue has an incomplete record on row {row_number}."
        )
    if record["category"] not in CULTURAL_EVENT_CATEGORIES:
        raise CulturalEventDataError(
            f"The cultural event catalogue has an unsupported category on row {row_number}."
        )

    try:
        start_date = date.fromisoformat(record["start_date"])
        end_date = date.fromisoformat(record["end_date"])
        verified_on = date.fromisoformat(record["verified_on"])
        latitude = float(record["latitude"])
        longitude = float(record["longitude"])
    except ValueError as error:
        raise CulturalEventDataError(
            f"The cultural event catalogue has invalid dates or coordinates on row {row_number}."
        ) from error

    if (
        end_date < start_date
        or verified_on > current_date
        or not math.isfinite(latitude)
        or not math.isfinite(longitude)
        or not -90 <= latitude <= 90
        or not -180 <= longitude <= 180
    ):
        raise CulturalEventDataError(
            f"The cultural event catalogue has invalid dates or coordinates on row {row_number}."
        )

    try:
        source_parts = urlsplit(record["source_url"])
    except ValueError as error:
        raise CulturalEventDataError(
            f"The cultural event catalogue has an invalid source URL on row {row_number}."
        ) from error
    if (
        source_parts.scheme != "https"
        or not source_parts.hostname
        or record["source_type"] not in RELIABLE_SOURCE_TYPES
        or (
            record["source_type"] == "government"
            and not source_parts.hostname.casefold().endswith((".gov.in", ".gov"))
        )
    ):
        raise CulturalEventDataError(
            f"The cultural event catalogue has an invalid source URL on row {row_number}."
        )

    record.update(
        {
            "latitude": latitude,
            "longitude": longitude,
            "category_label": CULTURAL_EVENT_CATEGORIES[str(record["category"])],
        }
    )
    return record
