from __future__ import annotations

from pathlib import Path

import pandas as pd

from models.destination import Destination

REQUIRED_COLUMNS = {
    "id",
    "name",
    "district",
    "category",
    "description",
    "latitude",
    "longitude",
    "natural_value",
    "cultural_value",
    "popularity",
    "accessibility",
    "sustainability_score",
    "natural_value_source",
    "cultural_value_source",
    "popularity_source",
    "accessibility_source",
    "sustainability_score_source",
    "coordinates_note",
    "source_url",
    "image_url",
    "image_source_url",
    "image_attribution",
    "image_license",
    "image_license_url",
}


class DestinationDataError(Exception):
    """Raised when the destination catalogue cannot be read or validated."""


def get_destinations(csv_path: str | Path) -> list[Destination]:
    try:
        frame = pd.read_csv(csv_path).fillna("")
    except (OSError, pd.errors.EmptyDataError, pd.errors.ParserError) as error:
        raise DestinationDataError("The destination CSV could not be read.") from error

    missing_columns = REQUIRED_COLUMNS - set(frame.columns)
    if missing_columns:
        raise DestinationDataError(
            f"The destination CSV is missing columns: {', '.join(sorted(missing_columns))}."
        )

    destinations = []
    for row_number, record in enumerate(frame.to_dict(orient="records"), start=2):
        try:
            destinations.append(Destination.from_record(record))
        except (TypeError, ValueError) as error:
            raise DestinationDataError(
                f"The destination CSV contains invalid values on row {row_number}."
            ) from error
    return destinations
