from __future__ import annotations

import re
from datetime import date
from typing import Any
from urllib.parse import urlsplit

from database import get_db
from services.auth_service import EMAIL_PATTERN


COMMUNITY_CATEGORIES = {
    "guide": "Tour guides",
    "artisan": "Handicraft artisans",
    "food_experience": "Traditional food experiences",
    "tribal_art_workshop": "Tribal art workshops",
    "village_tourism": "Village tourism",
    "cultural_activity": "Cultural activities",
}

_PHONE_PATTERN = re.compile(r"^\+?[0-9][0-9\s().-]{5,24}$")
class CommunityValidationError(ValueError):
    """Raised when a provider or enquiry submission is invalid."""


def get_public_providers(category: str = "", query: str = "") -> list[dict[str, Any]]:
    if category and category not in COMMUNITY_CATEGORIES:
        raise CommunityValidationError("Choose a valid community category.")

    search = _like_pattern(query.strip())
    rows = get_db().execute(
        """
        SELECT
            id, name, category, experience, location, description,
            image_url, image_source_url, image_attribution,
            listing_source_url, verified_on,
            CASE WHEN contact_verified = 1 THEN contact_phone ELSE '' END AS contact_phone,
            CASE WHEN contact_verified = 1 THEN contact_email ELSE '' END AS contact_email,
            CASE WHEN contact_verified = 1 THEN contact_source_url ELSE '' END AS contact_source_url,
            CASE WHEN contact_verified = 1 THEN contact_verified_on ELSE '' END AS contact_verified_on,
            contact_verified
        FROM community_providers
        WHERE is_published = 1
          AND (? = '' OR category = ?)
          AND (
              ? = ''
              OR lower(name) LIKE ? ESCAPE '!'
              OR lower(location) LIKE ? ESCAPE '!'
              OR lower(description) LIKE ? ESCAPE '!'
              OR lower(experience) LIKE ? ESCAPE '!'
          )
        ORDER BY name COLLATE NOCASE, id
        """,
        (category, category, search, search, search, search, search),
    ).fetchall()
    providers = []
    for row in rows:
        provider = dict(row)
        provider["category_label"] = COMMUNITY_CATEGORIES[provider["category"]]
        provider["contact_verified"] = bool(provider["contact_verified"])
        provider["contact_phone_href"] = (
            f"tel:{re.sub(r'[^+0-9]', '', provider['contact_phone'])}"
            if provider["contact_phone"]
            else ""
        )
        providers.append(provider)
    return providers


def get_admin_providers() -> list[dict[str, Any]]:
    rows = get_db().execute(
        "SELECT * FROM community_providers ORDER BY is_published DESC, updated_at DESC, id DESC"
    ).fetchall()
    providers = []
    for row in rows:
        provider = dict(row)
        provider["category_label"] = COMMUNITY_CATEGORIES[provider["category"]]
        provider["contact_verified"] = bool(provider["contact_verified"])
        provider["is_published"] = bool(provider["is_published"])
        providers.append(provider)
    return providers


def get_admin_provider(provider_id: int) -> dict[str, Any] | None:
    row = get_db().execute(
        "SELECT * FROM community_providers WHERE id = ?",
        (provider_id,),
    ).fetchone()
    return dict(row) if row is not None else None


def get_admin_enquiries() -> list[dict[str, Any]]:
    rows = get_db().execute(
        """
        SELECT
            enquiries.id, enquiries.provider_id, enquiries.message,
            enquiries.status, enquiries.created_at, enquiries.resolved_at,
            providers.name AS provider_name,
            users.full_name AS sender_name, users.email AS sender_email
        FROM community_enquiries AS enquiries
        JOIN community_providers AS providers ON providers.id = enquiries.provider_id
        JOIN users ON users.id = enquiries.user_id
        ORDER BY CASE enquiries.status WHEN 'new' THEN 0 ELSE 1 END,
                 enquiries.created_at DESC, enquiries.id DESC
        LIMIT 100
        """
    ).fetchall()
    return [dict(row) for row in rows]


def save_provider(
    form_data: Any,
    provider_id: int | None,
    admin_user_id: int,
) -> int:
    values = _validate_provider_form(form_data)
    connection = get_db()
    if provider_id is None:
        with connection:
            cursor = connection.execute(
                """
                INSERT INTO community_providers (
                    name, category, experience, location, description,
                    image_url, image_source_url, image_attribution,
                    listing_source_url, verified_on,
                    contact_phone, contact_email, contact_verified,
                    contact_source_url, contact_verified_on, is_published,
                    created_by_user_id, updated_by_user_id
                ) VALUES (
                    :name, :category, :experience, :location, :description,
                    :image_url, :image_source_url, :image_attribution,
                    :listing_source_url, :verified_on,
                    :contact_phone, :contact_email, :contact_verified,
                    :contact_source_url, :contact_verified_on, :is_published,
                    :admin_user_id, :admin_user_id
                )
                """,
                {**values, "admin_user_id": admin_user_id},
            )
        return int(cursor.lastrowid)

    with connection:
        cursor = connection.execute(
            """
            UPDATE community_providers
            SET name = :name,
                category = :category,
                experience = :experience,
                location = :location,
                description = :description,
                image_url = :image_url,
                image_source_url = :image_source_url,
                image_attribution = :image_attribution,
                listing_source_url = :listing_source_url,
                verified_on = :verified_on,
                contact_phone = :contact_phone,
                contact_email = :contact_email,
                contact_verified = :contact_verified,
                contact_source_url = :contact_source_url,
                contact_verified_on = :contact_verified_on,
                is_published = :is_published,
                updated_by_user_id = :admin_user_id,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = :provider_id
            """,
            {**values, "admin_user_id": admin_user_id, "provider_id": provider_id},
        )
    if cursor.rowcount == 0:
        raise LookupError("That community listing no longer exists.")
    return provider_id


def archive_provider(provider_id: int, admin_user_id: int) -> bool:
    connection = get_db()
    with connection:
        cursor = connection.execute(
            """
            UPDATE community_providers
            SET is_published = 0,
                updated_by_user_id = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (admin_user_id, provider_id),
        )
    return cursor.rowcount > 0


def submit_enquiry(provider_id: int, user_id: int, message: str) -> bool:
    normalized_message = message.strip()
    if not 10 <= len(normalized_message) <= 2000:
        raise CommunityValidationError("Enquiries must be between 10 and 2,000 characters.")
    connection = get_db()
    with connection:
        cursor = connection.execute(
            """
            INSERT INTO community_enquiries (provider_id, user_id, message)
            SELECT id, ?, ? FROM community_providers
            WHERE id = ? AND is_published = 1
            """,
            (user_id, normalized_message, provider_id),
        )
    return cursor.rowcount > 0


def resolve_enquiry(enquiry_id: int) -> bool:
    connection = get_db()
    with connection:
        cursor = connection.execute(
            """
            UPDATE community_enquiries
            SET status = 'resolved', resolved_at = CURRENT_TIMESTAMP
            WHERE id = ? AND status = 'new'
            """,
            (enquiry_id,),
        )
    return cursor.rowcount > 0


def _validate_provider_form(form_data: Any) -> dict[str, Any]:
    errors = []
    values: dict[str, Any] = {}
    limits = {
        "name": (120, "Provider name"),
        "experience": (180, "Experience"),
        "location": (180, "Location"),
        "description": (2000, "Description"),
    }
    for field, (maximum, label) in limits.items():
        value = _form_value(form_data, field)
        if not value:
            errors.append(f"{label} is required.")
        elif len(value) > maximum:
            errors.append(f"{label} must be {maximum} characters or fewer.")
        values[field] = value

    category = _form_value(form_data, "category")
    if category not in COMMUNITY_CATEGORIES:
        errors.append("Choose a valid provider category.")
    values["category"] = category

    listing_source_url = _form_value(form_data, "listing_source_url")
    if listing_source_url and not _is_https_url(listing_source_url):
        errors.append("Listing source must be a valid HTTPS URL.")
    verified_on = _read_verification_date(
        _form_value(form_data, "verified_on"),
        "Listing review date",
        bool(_is_checked(form_data, "is_published")),
        errors,
    )
    if _is_checked(form_data, "is_published") and not listing_source_url:
        errors.append("A source link is required before publishing a listing.")
    values["listing_source_url"] = listing_source_url
    values["verified_on"] = verified_on
    values["is_published"] = int(_is_checked(form_data, "is_published"))

    image_url = _form_value(form_data, "image_url")
    image_source_url = _form_value(form_data, "image_source_url")
    image_attribution = _form_value(form_data, "image_attribution")
    if image_url and not _is_https_url(image_url):
        errors.append("Profile image URL must be a valid HTTPS URL.")
    if image_url and not image_source_url:
        errors.append("Provide an image source URL for every profile image.")
    if image_source_url and not _is_https_url(image_source_url):
        errors.append("Image source must be a valid HTTPS URL.")
    if image_url and not image_attribution:
        errors.append("Provide image attribution for every profile image.")
    if not image_url and (image_source_url or image_attribution):
        errors.append("Image source and attribution require an image URL.")
    if len(image_attribution) > 160:
        errors.append("Image attribution must be 160 characters or fewer.")
    values.update(
        image_url=image_url,
        image_source_url=image_source_url,
        image_attribution=image_attribution,
    )

    contact_phone = _form_value(form_data, "contact_phone")
    contact_email = _form_value(form_data, "contact_email").lower()
    contact_verified = _is_checked(form_data, "contact_verified")
    contact_source_url = _form_value(form_data, "contact_source_url")
    contact_verified_on = _read_verification_date(
        _form_value(form_data, "contact_verified_on"),
        "Contact verification date",
        contact_verified,
        errors,
    )
    if contact_phone and (
        len(contact_phone) > 30 or not _PHONE_PATTERN.fullmatch(contact_phone)
    ):
        errors.append("Enter a valid contact phone number.")
    if contact_email and (
        len(contact_email) > 254 or not EMAIL_PATTERN.fullmatch(contact_email)
    ):
        errors.append("Enter a valid contact email address.")
    if contact_verified:
        if not contact_phone and not contact_email:
            errors.append("Enter a phone number or email before verifying contact details.")
        if not contact_source_url or not _is_https_url(contact_source_url):
            errors.append("A valid HTTPS source is required to verify contact details.")
    elif any(
        (contact_phone, contact_email, contact_source_url, contact_verified_on)
    ):
        errors.append("Only enter contact details after verifying them.")
    values.update(
        contact_phone=contact_phone if contact_verified else "",
        contact_email=contact_email if contact_verified else "",
        contact_verified=int(contact_verified),
        contact_source_url=contact_source_url if contact_verified else "",
        contact_verified_on=contact_verified_on if contact_verified else "",
    )

    if errors:
        raise CommunityValidationError(" ".join(errors))
    return values


def _form_value(form_data: Any, field: str) -> str:
    value = form_data.get(field, "")
    if not isinstance(value, str):
        return ""
    return value.strip() if field == "description" else " ".join(value.split())


def _is_checked(form_data: Any, field: str) -> bool:
    return form_data.get(field) in {"on", "1", "true"}


def _read_verification_date(
    value: str,
    label: str,
    required: bool,
    errors: list[str],
) -> str:
    if not value:
        if required:
            errors.append(f"{label} is required.")
        return ""
    try:
        parsed_date = date.fromisoformat(value)
    except ValueError:
        errors.append(f"{label} must be a valid date.")
        return ""
    if parsed_date > date.today():
        errors.append(f"{label} cannot be in the future.")
        return ""
    return parsed_date.isoformat()


def _is_https_url(value: str) -> bool:
    if len(value) > 2048:
        return False
    try:
        parsed = urlsplit(value)
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and bool(parsed.hostname)
        and parsed.username is None
        and parsed.password is None
    )


def _like_pattern(query: str) -> str:
    escaped = query.casefold().replace("!", "!!").replace("%", "!%").replace("_", "!_")
    return f"%{escaped}%" if escaped else ""
