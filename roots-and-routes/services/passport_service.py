from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import sqlite3
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

from models.destination import Destination

QR_CODE_LIFETIME = timedelta(minutes=15)
NATURE_CATEGORIES = frozenset(
    {"waterfall", "national park", "mountain", "valley", "hill", "forest"}
)
_QR_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
_MIN_VISIT_DATE = date(1900, 1, 1)


class PassportValidationError(ValueError):
    """Raised when a travel passport action contains invalid data."""


def build_passport_destinations(
    destinations: list[Destination],
    cultural_destinations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    entries = [
        {
            "id": destination.id,
            "name": destination.name,
            "district": destination.district,
            "category": destination.category,
            "description": destination.description,
            "source_url": destination.source_url,
            "sustainability_score": destination.sustainability_score,
            "sustainability_score_source": destination.sustainability_score_source,
        }
        for destination in destinations
    ]
    for destination in cultural_destinations:
        entries.append(
            {
                "id": f"culture-{destination['slug']}",
                "name": destination["name"],
                "district": destination["district"],
                "category": "Culture",
                "description": destination["introduction"],
                "source_url": destination["sources"][0]["url"],
                "sustainability_score": None,
                "sustainability_score_source": "",
            }
        )
    ids = [entry["id"] for entry in entries]
    if len(ids) != len(set(ids)):
        raise PassportValidationError("Passport destinations must have unique identifiers.")
    return sorted(entries, key=lambda entry: (entry["name"].casefold(), entry["id"]))


def get_passport(
    connection: sqlite3.Connection,
    user_id: int,
    destinations: list[dict[str, Any]],
    hidden_gem_ids: set[str],
) -> dict[str, Any]:
    visits = [
        dict(row)
        for row in connection.execute(
            """
            SELECT id, destination_id, destination_name, district, category, visited_on,
                   verification_method, created_at
            FROM passport_visits
            WHERE user_id = ?
            ORDER BY visited_on DESC, id DESC
            """,
            (user_id,),
        ).fetchall()
    ]
    visits_by_destination: dict[str, list[dict[str, Any]]] = {}
    for visit in visits:
        visits_by_destination.setdefault(visit["destination_id"], []).append(visit)

    visited_ids = set(visits_by_destination)
    completion_destinations = []
    for destination in destinations:
        destination_visits = visits_by_destination.get(destination["id"], [])
        completion_destinations.append(
            {
                **destination,
                "visit_count": len(destination_visits),
                "visited": bool(destination_visits),
                "last_visited_on": (
                    destination_visits[0]["visited_on"] if destination_visits else None
                ),
                "verification_methods": sorted(
                    {visit["verification_method"] for visit in destination_visits}
                ),
            }
        )

    achievements = _achievements(
        visited_ids,
        destinations,
        hidden_gem_ids,
    )
    unique_count = len(visited_ids)
    completed_count = len(visited_ids & {item["id"] for item in destinations})
    total_destinations = len(destinations)
    verified_count = sum(
        visit["verification_method"] == "verified_qr" for visit in visits
    )
    return {
        "visits": visits,
        "destinations": completion_destinations,
        "achievements": achievements,
        "statistics": {
            "total_visits": len(visits),
            "unique_destinations": unique_count,
            "verified_qr_visits": verified_count,
            "self_reported_visits": len(visits) - verified_count,
            "completed_destinations": completed_count,
            "total_destinations": total_destinations,
            "completion_percent": (
                round(completed_count / total_destinations * 100, 1)
                if total_destinations
                else 0
            ),
        },
    }


def record_passport_visit(
    connection: sqlite3.Connection,
    user_id: int,
    destination: dict[str, Any],
    visited_on: str,
    verification_method: str,
    qr_code_id: str | None = None,
) -> str:
    visit_date = _validated_visit_date(visited_on)
    if verification_method not in {"self_reported", "verified_qr"}:
        raise PassportValidationError("Choose a supported visit verification method.")
    if (verification_method == "verified_qr") != bool(qr_code_id):
        raise PassportValidationError("The QR verification details are invalid.")

    existing = connection.execute(
        """
        SELECT id, verification_method
        FROM passport_visits
        WHERE user_id = ? AND destination_id = ? AND visited_on = ?
        """,
        (user_id, destination["id"], visit_date.isoformat()),
    ).fetchone()
    if existing is not None:
        if (
            verification_method == "verified_qr"
            and existing["verification_method"] == "self_reported"
        ):
            connection.execute(
                """
                UPDATE passport_visits
                SET verification_method = 'verified_qr', qr_code_id = ?
                WHERE id = ?
                """,
                (qr_code_id, existing["id"]),
            )
            return "upgraded"
        return "already_recorded"

    connection.execute(
        """
        INSERT INTO passport_visits (
            user_id, destination_id, destination_name, district, category, visited_on,
            verification_method, qr_code_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            destination["id"],
            destination["name"],
            destination["district"],
            destination["category"],
            visit_date.isoformat(),
            verification_method,
            qr_code_id,
        ),
    )
    return "created"


def issue_passport_qr_code(
    connection: sqlite3.Connection,
    user_id: int,
    destination: dict[str, Any],
    now: datetime | None = None,
) -> dict[str, str]:
    issued_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    expires_at = issued_at + QR_CODE_LIFETIME
    code_id = uuid.uuid4().hex
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    connection.execute(
        """
        INSERT INTO passport_qr_codes (
            id, destination_id, destination_name, token_hash, issued_by_user_id,
            issued_at, expires_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            code_id,
            destination["id"],
            destination["name"],
            token_hash,
            user_id,
            issued_at.isoformat(),
            expires_at.isoformat(),
        ),
    )
    return {
        "id": code_id,
        "token": token,
        "expires_at": expires_at.isoformat(),
    }


def verify_passport_qr_code(
    connection: sqlite3.Connection,
    code_id: object,
    token: object,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    if (
        not isinstance(code_id, str)
        or not _QR_ID_PATTERN.fullmatch(code_id)
        or not isinstance(token, str)
        or not 32 <= len(token) <= 128
    ):
        return None
    row = _active_passport_qr_row(connection, code_id, now)
    if row is None:
        return None
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    if not hmac.compare_digest(token_hash, row["token_hash"]):
        return None
    return _passport_qr_claim(row)


def get_active_passport_qr_code(
    connection: sqlite3.Connection,
    code_id: object,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    if not isinstance(code_id, str) or not _QR_ID_PATTERN.fullmatch(code_id):
        return None
    row = _active_passport_qr_row(connection, code_id, now)
    return _passport_qr_claim(row) if row is not None else None


def _active_passport_qr_row(
    connection: sqlite3.Connection,
    code_id: str,
    now: datetime | None,
) -> sqlite3.Row | None:
    row = connection.execute(
        """
        SELECT id, destination_id, destination_name, token_hash, expires_at, revoked_at
        FROM passport_qr_codes
        WHERE id = ?
        """,
        (code_id,),
    ).fetchone()
    if row is None or row["revoked_at"] is not None:
        return None
    try:
        expires_at = datetime.fromisoformat(row["expires_at"])
    except ValueError:
        return None
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= (now or datetime.now(timezone.utc)):
        return None
    return row


def _passport_qr_claim(row: sqlite3.Row) -> dict[str, Any]:
    expires_at = datetime.fromisoformat(row["expires_at"])
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return {
        "id": row["id"],
        "destination_id": row["destination_id"],
        "destination_name": row["destination_name"],
        "expires_at": expires_at.isoformat(),
    }


def _validated_visit_date(value: object) -> date:
    if not isinstance(value, str):
        raise PassportValidationError("Enter a valid visit date.")
    try:
        visit_date = date.fromisoformat(value)
    except ValueError as error:
        raise PassportValidationError("Enter a valid visit date.") from error
    if visit_date.isoformat() != value or not _MIN_VISIT_DATE <= visit_date <= date.today():
        raise PassportValidationError("Visit dates must be between 1900 and today.")
    return visit_date


def _achievements(
    visited_ids: set[str],
    destinations: list[dict[str, Any]],
    hidden_gem_ids: set[str],
) -> list[dict[str, Any]]:
    by_id = {destination["id"]: destination for destination in destinations}
    waterfall_ids = {
        destination["id"]
        for destination in destinations
        if destination["category"].casefold() == "waterfall"
    }
    nature_ids = {
        destination["id"]
        for destination in destinations
        if destination["category"].casefold() in NATURE_CATEGORIES
    }
    culture_ids = {
        destination["id"]
        for destination in destinations
        if destination["category"].casefold() in {"culture", "cultural guide"}
    }
    eco_ids = {
        destination["id"]
        for destination in destinations
        if isinstance(destination.get("sustainability_score"), int)
        and destination["sustainability_score"] >= 70
        and destination.get("sustainability_score_source")
    }
    definitions = (
        (
            "waterfall-explorer",
            "Waterfall Explorer",
            "Visit three different waterfall destinations.",
            waterfall_ids,
            3,
            "",
        ),
        (
            "nature-lover",
            "Nature Lover",
            "Visit three different nature destinations.",
            nature_ids,
            3,
            "",
        ),
        (
            "culture-enthusiast",
            "Culture Enthusiast",
            "Visit one destination with a curated cultural guide.",
            culture_ids,
            1,
            "",
        ),
        (
            "hidden-gem-discoverer",
            "Hidden Gem Discoverer",
            "Visit an evidence-ranked hidden destination.",
            hidden_gem_ids,
            1,
            (
                "No destinations currently meet the source-backed hidden-gem criteria."
                if not hidden_gem_ids
                else ""
            ),
        ),
        (
            "eco-traveller",
            "Eco Traveller",
            "Visit three destinations with sourced sustainability scores of 70 or higher.",
            eco_ids,
            3,
            (
                "No destinations currently have a sourced sustainability score of 70 or higher."
                if not eco_ids
                else ""
            ),
        ),
    )
    achievements = []
    for achievement_id, name, description, eligible_ids, required, unavailable_note in definitions:
        progress = len(visited_ids & eligible_ids)
        achievements.append(
            {
                "id": achievement_id,
                "name": name,
                "description": description,
                "progress": min(progress, required),
                "required": required,
                "unlocked": progress >= required,
                "unavailable_note": unavailable_note,
                "qualifying_visited_names": [
                    by_id[destination_id]["name"]
                    for destination_id in sorted(visited_ids & eligible_ids)
                    if destination_id in by_id
                ],
            }
        )
    return achievements