from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlsplit


class CulturalExplorerDataError(ValueError):
    """Raised when curated cultural guide content is incomplete or unsafe."""


_SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def get_cultural_destinations(path: str | Path) -> list[dict]:
    try:
        with Path(path).open(encoding="utf-8") as content_file:
            data = json.load(content_file)
    except (OSError, json.JSONDecodeError) as error:
        raise CulturalExplorerDataError("Cultural guide data could not be read.") from error

    if not isinstance(data, dict) or not isinstance(data.get("destinations"), list):
        raise CulturalExplorerDataError("Cultural guide data must contain a destinations list.")

    destinations = data["destinations"]
    seen_slugs = set()
    required_sections = (
        "historical_background",
        "tribal_traditions",
        "local_art",
        "festivals",
    )
    for destination in destinations:
        if not isinstance(destination, dict):
            raise CulturalExplorerDataError("Each cultural destination must be an object.")
        slug = destination.get("slug")
        if not isinstance(slug, str) or not _SLUG_PATTERN.fullmatch(slug) or slug in seen_slugs:
            raise CulturalExplorerDataError("Cultural destination slugs must be unique and URL-safe.")
        seen_slugs.add(slug)
        if not all(
            isinstance(destination.get(field), str) and destination[field].strip()
            for field in ("name", "district", "introduction")
        ):
            raise CulturalExplorerDataError(f"Cultural destination {slug} is missing its identity.")
        for section in required_sections:
            _validate_source_record(destination.get(section), f"{slug}.{section}")
        if not isinstance(destination.get("sources"), list) or not destination["sources"]:
            raise CulturalExplorerDataError(f"Cultural destination {slug} must cite its sources.")
        for source in destination["sources"]:
            _validate_source_record(source, f"{slug}.sources")
        photos = destination.get("cultural_photos")
        if not isinstance(photos, list):
            raise CulturalExplorerDataError(f"Cultural destination {slug} must list its photos.")
        for photo in photos:
            _validate_photo(photo, slug)
        audio = destination.get("audio_description")
        if audio is not None:
            _validate_audio_description(audio, slug)
        extensions = destination.get("experience_extensions")
        if not isinstance(extensions, dict) or not isinstance(extensions.get("ar"), list):
            raise CulturalExplorerDataError(
                f"Cultural destination {slug} must keep an AR extension list."
            )
    return destinations


def get_cultural_destination(path: str | Path, slug: str) -> dict | None:
    return next(
        (destination for destination in get_cultural_destinations(path) if destination["slug"] == slug),
        None,
    )


def cultural_destination_url(slug: str, public_base_url: str) -> str:
    if not _SLUG_PATTERN.fullmatch(slug):
        raise ValueError("A valid cultural destination slug is required.")
    return canonical_public_url(f"/culture/{slug}", public_base_url)


def canonical_public_url(path: str, public_base_url: str) -> str:
    parsed = urlsplit(public_base_url)
    hostname = parsed.hostname
    port = parsed.port
    if (
        not parsed.netloc
        or not hostname
        or (port is not None and not 1 <= port <= 65535)
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in ("", "/")
        or parsed.scheme not in {"https", "http"}
        or (parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"})
    ):
        raise ValueError("PUBLIC_BASE_URL must be an HTTPS origin (HTTP is allowed for localhost only).")
    if (
        not isinstance(path, str)
        or not path.startswith("/")
        or path.startswith("//")
        or urlsplit(path).netloc
        or urlsplit(path).scheme
    ):
        raise ValueError("A local absolute path is required for public links.")
    return f"{public_base_url.rstrip('/')}{path}"


def _validate_audio_description(audio: object, slug: str) -> None:
    if not isinstance(audio, dict) or not _is_https_url(audio.get("audio_url")):
        raise CulturalExplorerDataError(
            f"Cultural destination {slug} has an invalid audio description URL."
        )
    if not _is_https_url(audio.get("source_url")) or not isinstance(
        audio.get("source_name"), str
    ):
        raise CulturalExplorerDataError(
            f"Cultural destination {slug} audio description must cite its source."
        )
    transcript = audio.get("transcript")
    if transcript is not None and not isinstance(transcript, str):
        raise CulturalExplorerDataError(
            f"Cultural destination {slug} audio transcript must be text."
        )


def _validate_source_record(record: object, field_name: str) -> None:
    if not isinstance(record, dict) or not isinstance(record.get("text", record.get("name")), str):
        raise CulturalExplorerDataError(f"Cultural guide content is missing {field_name}.")
    if record.get("available") is False:
        if record.get("source_url") is not None or record.get("source_name") is not None:
            raise CulturalExplorerDataError(
                f"Unavailable cultural guide content for {field_name} cannot cite a source."
            )
        return
    url = record.get("source_url", record.get("url"))
    if not _is_https_url(url):
        raise CulturalExplorerDataError(f"Cultural guide source for {field_name} must use HTTPS.")


def _validate_photo(photo: object, slug: str) -> None:
    if not isinstance(photo, dict) or not all(
        isinstance(photo.get(field), str) and photo[field].strip()
        for field in ("url", "source_url", "alt_text", "attribution", "license")
    ):
        raise CulturalExplorerDataError(f"Cultural destination {slug} has incomplete photo attribution.")
    if not _is_https_url(photo["url"]) or not _is_https_url(photo["source_url"]):
        raise CulturalExplorerDataError(f"Cultural destination {slug} photos must use HTTPS.")
    if photo.get("license_url") is not None and not _is_https_url(photo["license_url"]):
        raise CulturalExplorerDataError(f"Cultural destination {slug} photo license must use HTTPS.")


def _is_https_url(value: object) -> bool:
    if not isinstance(value, str):
        return False
    parsed = urlsplit(value)
    return parsed.scheme == "https" and bool(parsed.netloc) and not parsed.username and not parsed.password
