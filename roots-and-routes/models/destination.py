from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class Destination:
    id: str
    name: str
    district: str
    category: str
    description: str
    latitude: float
    longitude: float
    natural_value: int | None
    cultural_value: int | None
    popularity: int | None
    accessibility: int | None
    sustainability_score: int | None
    natural_value_source: str
    cultural_value_source: str
    popularity_source: str
    accessibility_source: str
    sustainability_score_source: str
    coordinates_note: str
    source_url: str
    image_url: str
    image_source_url: str
    image_attribution: str
    image_license: str
    image_license_url: str

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> "Destination":
        latitude = float(record["latitude"])
        longitude = float(record["longitude"])
        if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
            raise ValueError("Coordinates must be within valid map bounds.")
        scores = {
            field: _optional_score(record.get(field), field)
            for field in (
                "natural_value",
                "cultural_value",
                "popularity",
                "accessibility",
                "sustainability_score",
            )
        }
        destination = cls(
            id=str(record["id"]).strip(),
            name=str(record["name"]).strip(),
            district=str(record["district"]).strip(),
            category=str(record["category"]).strip(),
            description=str(record["description"]).strip(),
            latitude=latitude,
            longitude=longitude,
            **scores,
            natural_value_source=str(record.get("natural_value_source", "")).strip(),
            cultural_value_source=str(record.get("cultural_value_source", "")).strip(),
            popularity_source=str(record.get("popularity_source", "")).strip(),
            accessibility_source=str(record.get("accessibility_source", "")).strip(),
            sustainability_score_source=str(
                record.get("sustainability_score_source", "")
            ).strip(),
            coordinates_note=str(record.get("coordinates_note", "")).strip(),
            source_url=str(record["source_url"]).strip(),
            image_url=str(record["image_url"]).strip(),
            image_source_url=str(record["image_source_url"]).strip(),
            image_attribution=str(record["image_attribution"]).strip(),
            image_license=str(record["image_license"]).strip(),
            image_license_url=str(record.get("image_license_url", "")).strip(),
        )
        if not all(
            (
                destination.id,
                destination.name,
                destination.district,
                destination.category,
                destination.description,
                destination.source_url,
                destination.image_url,
                destination.image_source_url,
                destination.image_attribution,
                destination.image_license,
            )
        ):
            raise ValueError("Destination names, sources, and image credits are required.")
        return destination

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _optional_score(value: Any, field: str) -> int | None:
    if value is None or str(value).strip() == "":
        return None
    numeric_score = float(value)
    if not numeric_score.is_integer():
        raise ValueError(f"{field} must be a whole number.")
    score = int(numeric_score)
    if not 0 <= score <= 100:
        raise ValueError(f"{field} must be between 0 and 100.")
    return score
