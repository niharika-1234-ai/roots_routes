from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path
from typing import Any

from models.destination import Destination

CROWD_MONTHS = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)
_MONTH_KEYS = tuple(month[:3].casefold() for month in CROWD_MONTHS)
_REQUIRED_COLUMNS = {
    "destination_id",
    "year",
    *_MONTH_KEYS,
    "data_label",
}
SAMPLE_DATA_LABEL = "synthetic_sample"
SAMPLE_DATA_NOTICE = (
    "Illustrative synthetic sample only — these indices are not observed visitors, "
    "live counts, or verified crowd predictions."
)
_LEVELS = (
    (35, "Low"),
    (65, "Moderate"),
    (100, "High"),
)
_CHART_COLORS = ("#4c865a", "#d19a42", "#6285a2", "#a7789b")


class CrowdDataError(Exception):
    """Raised when the illustrative crowd sample cannot be loaded or validated."""


def build_crowd_dashboard(
    csv_path: str | Path,
    destinations: list[Destination],
    selected_destination_id: str,
    selected_month: int,
) -> dict[str, Any]:
    if not 1 <= selected_month <= len(CROWD_MONTHS):
        raise ValueError("Choose a valid calendar month.")

    destinations_by_id = {destination.id: destination for destination in destinations}
    selected_destination = destinations_by_id.get(selected_destination_id)
    if selected_destination is None:
        raise ValueError("Choose a destination from the catalogue.")

    history = _load_sample(csv_path, set(destinations_by_id))
    selected_history = history.get(selected_destination_id)
    if not selected_history:
        raise CrowdDataError(
            f"No labelled sample history exists for {selected_destination.name}."
        )

    years = sorted(selected_history)
    forecast_year = years[-1] + 1
    predicted_index = _forecast_index(selected_history, selected_month)
    level = _crowd_level(predicted_index)

    chart_datasets = []
    yearly_averages = []
    for index, year in enumerate(years):
        values = selected_history[year]
        yearly_averages.append(
            {"year": year, "index": round(sum(values) / len(values), 1)}
        )
        chart_datasets.append(
            {
                "label": f"Sample {year}",
                "data": values,
                "borderColor": _CHART_COLORS[index % len(_CHART_COLORS)],
                "backgroundColor": _CHART_COLORS[index % len(_CHART_COLORS)],
                "borderWidth": 2,
                "pointRadius": 2,
                "pointHoverRadius": 5,
                "tension": 0.32,
                "fill": False,
            }
        )
    estimate_values: list[int | None] = [None] * len(CROWD_MONTHS)
    estimate_values[selected_month - 1] = predicted_index
    chart_datasets.append(
        {
            "label": f"Sample-based estimate {forecast_year}",
            "data": estimate_values,
            "borderColor": "#263f30",
            "backgroundColor": "#263f30",
            "pointRadius": 7,
            "pointHoverRadius": 9,
            "showLine": False,
        }
    )

    monthly_predictions = [
        {
            "month": month_number,
            "month_name": CROWD_MONTHS[month_number - 1],
            "index": _forecast_index(selected_history, month_number),
        }
        for month_number in range(1, len(CROWD_MONTHS) + 1)
    ]
    suggested_periods = sorted(
        monthly_predictions,
        key=lambda item: (item["index"], item["month"]),
    )[:3]
    alternatives = []
    for destination in destinations:
        if destination.id == selected_destination_id or destination.id not in history:
            continue
        alternative_index = _forecast_index(history[destination.id], selected_month)
        if alternative_index < predicted_index:
            alternatives.append(
                {
                    "id": destination.id,
                    "name": destination.name,
                    "district": destination.district,
                    "source_url": destination.source_url,
                    "index": alternative_index,
                    "level": _crowd_level(alternative_index),
                }
            )
    alternatives.sort(key=lambda item: (item["index"], item["name"]))

    return {
        "destination": {
            "id": selected_destination.id,
            "name": selected_destination.name,
            "district": selected_destination.district,
            "category": selected_destination.category,
            "source_url": selected_destination.source_url,
        },
        "month": selected_month,
        "month_name": CROWD_MONTHS[selected_month - 1],
        "forecast_year": forecast_year,
        "prediction_index": predicted_index,
        "level": level,
        "historical_years": years,
        "yearly_averages": yearly_averages,
        "chart_data": {
            "labels": list(CROWD_MONTHS),
            "datasets": chart_datasets,
        },
        "suggested_periods": suggested_periods,
        "alternatives": alternatives[:4],
        "sample_notice": SAMPLE_DATA_NOTICE,
        "data_label": SAMPLE_DATA_LABEL,
    }


def _load_sample(
    csv_path: str | Path,
    known_destination_ids: set[str],
) -> dict[str, dict[int, list[int]]]:
    history: dict[str, dict[int, list[int]]] = defaultdict(dict)
    try:
        with Path(csv_path).open(encoding="utf-8-sig", newline="") as sample_file:
            reader = csv.DictReader(sample_file)
            if _REQUIRED_COLUMNS - set(reader.fieldnames or ()):
                raise CrowdDataError("The crowd sample file is missing required columns.")
            for row_number, row in enumerate(reader, start=2):
                destination_id = (row.get("destination_id") or "").strip()
                try:
                    year = int(row.get("year", ""))
                    values = [int(row.get(key, "")) for key in _MONTH_KEYS]
                except (TypeError, ValueError) as error:
                    raise CrowdDataError(
                        f"The crowd sample has invalid year or index values on row {row_number}."
                    ) from error
                if (
                    destination_id not in known_destination_ids
                    or year < 2000
                    or (row.get("data_label") or "").strip() != SAMPLE_DATA_LABEL
                    or any(not 0 <= value <= 100 for value in values)
                ):
                    raise CrowdDataError(
                        f"The crowd sample has an invalid or unlabelled record on row {row_number}."
                    )
                if year in history[destination_id]:
                    raise CrowdDataError(
                        f"The crowd sample contains duplicate destination/year data on row {row_number}."
                    )
                history[destination_id][year] = values
    except CrowdDataError:
        raise
    except (OSError, UnicodeError, csv.Error) as error:
        raise CrowdDataError("The crowd sample file could not be read.") from error

    if not history:
        raise CrowdDataError("The crowd sample file contains no historical sample records.")
    if any(len(yearly_values) < 2 for yearly_values in history.values()):
        raise CrowdDataError("Each destination requires at least two labelled sample years.")
    return dict(history)


def _forecast_index(history: dict[int, list[int]], month: int) -> int:
    years = sorted(history)
    if len(years) < 2:
        raise CrowdDataError("At least two sample years are required for a projection.")
    month_index = month - 1
    first_year, last_year = years[0], years[-1]
    first_value = history[first_year][month_index]
    last_value = history[last_year][month_index]
    annual_change = (last_value - first_value) / (last_year - first_year)
    projected = round(last_value + annual_change)
    return max(0, min(100, projected))


def _crowd_level(index: int) -> str:
    for threshold, level in _LEVELS:
        if index <= threshold:
            return level
    return "High"
