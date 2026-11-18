from __future__ import annotations

import csv
import math
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


MODE_ORDER = ("car", "bus", "train", "bicycle", "walking")
MODE_LABELS = {
    "car": "Car",
    "bus": "Bus",
    "train": "Train",
    "bicycle": "Bicycle",
    "walking": "Walking",
}
_MODE_UNITS = {
    "car": ("vehicle-km", "vehicle"),
    "bus": ("passenger-km", "passenger"),
    "train": ("passenger-km", "passenger"),
    "bicycle": ("person-km", "person"),
    "walking": ("person-km", "person"),
}
_REQUIRED_COLUMNS = {
    "mode_id",
    "mode_label",
    "kg_co2e_per_unit",
    "unit",
    "basis",
    "source_name",
    "source_url",
    "document_url",
    "factor_year",
    "source_note",
}


class CarbonFactorDataError(Exception):
    """Raised when a configured transport emissions factor is invalid."""


def get_transport_factors(csv_path: str | Path) -> list[dict[str, Any]]:
    factors: dict[str, dict[str, Any]] = {}
    try:
        with Path(csv_path).open(encoding="utf-8-sig", newline="") as factor_file:
            reader = csv.DictReader(factor_file)
            if _REQUIRED_COLUMNS - set(reader.fieldnames or ()):
                raise CarbonFactorDataError(
                    "The transport emissions factor file is missing required columns."
                )
            for row_number, row in enumerate(reader, start=2):
                if row is None or None in row:
                    raise CarbonFactorDataError(
                        f"The factor file has an invalid record on row {row_number}."
                    )
                if any(row.get(column) is None for column in _REQUIRED_COLUMNS):
                    raise CarbonFactorDataError(
                        f"The factor file has an incomplete record on row {row_number}."
                    )
                mode_id = (row.get("mode_id") or "").strip().casefold()
                try:
                    factor = float(row.get("kg_co2e_per_unit", ""))
                except (TypeError, ValueError) as error:
                    raise CarbonFactorDataError(
                        f"The factor file has an invalid value on row {row_number}."
                    ) from error
                mode = _MODE_UNITS.get(mode_id)
                source_url = (row.get("source_url") or "").strip()
                document_url = (row.get("document_url") or "").strip()
                source_name = (row.get("source_name") or "").strip()
                source_note = (row.get("source_note") or "").strip()
                if (
                    mode is None
                    or mode_id in factors
                    or not math.isfinite(factor)
                    or factor < 0
                    or (row.get("unit") or "").strip() != mode[0]
                    or (row.get("basis") or "").strip() != mode[1]
                    or (row.get("mode_label") or "").strip() != MODE_LABELS[mode_id]
                    or not source_name
                    or not source_note
                    or (factor > 0 and not source_url)
                    or not _is_https_url(source_url, allow_blank=True)
                    or not _is_https_url(document_url, allow_blank=True)
                ):
                    raise CarbonFactorDataError(
                        f"The factor file has an invalid or undocumented record on row {row_number}."
                    )
                factors[mode_id] = {
                    "mode_id": mode_id,
                    "mode_label": MODE_LABELS[mode_id],
                    "kg_co2e_per_unit": factor,
                    "unit": mode[0],
                    "basis": mode[1],
                    "source_name": source_name,
                    "source_url": source_url,
                    "document_url": document_url,
                    "factor_year": (row.get("factor_year") or "").strip(),
                    "source_note": source_note,
                }
    except CarbonFactorDataError:
        raise
    except (OSError, UnicodeError, csv.Error) as error:
        raise CarbonFactorDataError("The transport emissions factor file could not be read.") from error

    missing_modes = set(MODE_ORDER) - set(factors)
    if missing_modes:
        raise CarbonFactorDataError(
            f"The factor file is missing modes: {', '.join(sorted(missing_modes))}."
        )
    return [factors[mode] for mode in MODE_ORDER]


def calculate_carbon_footprint(
    factors: list[dict[str, Any]],
    distance_km: float,
    travellers: int,
    selected_mode: str,
    source: str,
    destination: str,
    distance_source: str,
    distance_note: str,
) -> dict[str, Any]:
    if not math.isfinite(distance_km) or distance_km < 0:
        raise ValueError("Travel distance must be a non-negative finite value.")
    if not isinstance(travellers, int) or isinstance(travellers, bool) or travellers < 1:
        raise ValueError("Number of travellers must be a positive whole number.")
    factors_by_mode = {factor["mode_id"]: factor for factor in factors}
    if selected_mode not in factors_by_mode:
        raise ValueError("Choose a supported transport mode.")

    comparisons = []
    for mode_id in MODE_ORDER:
        factor = factors_by_mode[mode_id]
        total, per_person = _estimate_for_mode(factor, distance_km, travellers)
        comparisons.append(
            {
                "mode_id": mode_id,
                "mode_label": factor["mode_label"],
                "kg_co2e_per_unit": factor["kg_co2e_per_unit"],
                "unit": factor["unit"],
                "basis": factor["basis"],
                "total_kg_co2e": round(total, 4),
                "per_person_kg_co2e": round(per_person, 4),
                "is_selected": mode_id == selected_mode,
                "source_name": factor["source_name"],
                "source_url": factor["source_url"],
                "document_url": factor["document_url"],
                "factor_year": factor["factor_year"],
                "source_note": factor["source_note"],
            }
        )

    selected = next(item for item in comparisons if item["is_selected"])
    lower_modes = [
        item
        for item in comparisons
        if item["mode_id"] != selected_mode
        and item["per_person_kg_co2e"] < selected["per_person_kg_co2e"]
    ]
    lower_modes.sort(key=lambda item: (item["per_person_kg_co2e"], MODE_ORDER.index(item["mode_id"])))

    suggestions = []
    if lower_modes:
        suggestions.append(
            "For this distance and traveller count, lower per-person operational estimates "
            "in this factor set are available with: "
            + ", ".join(item["mode_label"] for item in lower_modes)
            + ". Check that a suitable service or safe route is actually available."
        )
    if selected_mode == "car" and travellers > 1:
        suggestions.append(
            "The car factor is per vehicle-kilometre: sharing one car does not change its "
            "modelled total, but it lowers the per-person share."
        )
    if selected_mode not in {"bicycle", "walking"}:
        suggestions.append(
            "For a practical, safe short trip, consider walking or cycling; this calculator "
            "counts only direct operational emissions for those modes."
        )
    if not suggestions:
        suggestions.append(
            "This mode has the lowest per-person operational estimate in the configured "
            "comparison for these inputs."
        )

    return {
        "source": source,
        "destination": destination,
        "distance_km": round(distance_km, 2),
        "distance_source": distance_source,
        "distance_note": distance_note,
        "mode": selected,
        "travellers": travellers,
        "total_kg_co2e": selected["total_kg_co2e"],
        "per_person_kg_co2e": selected["per_person_kg_co2e"],
        "comparisons": comparisons,
        "suggestions": suggestions,
        "factor_basis_note": (
            "Results are operational CO2e estimates. Car is calculated per vehicle-km; "
            "bus and rail use passenger-km; bicycle and walking use a zero direct-emissions "
            "boundary assumption. Upstream fuel, vehicle manufacture, infrastructure, and "
            "other lifecycle emissions are excluded."
        ),
    }


def _estimate_for_mode(
    factor: dict[str, Any],
    distance_km: float,
    travellers: int,
) -> tuple[float, float]:
    emissions_per_unit = factor["kg_co2e_per_unit"]
    if factor["basis"] == "vehicle":
        total = distance_km * emissions_per_unit
    else:
        total = distance_km * emissions_per_unit * travellers
    return total, total / travellers


def _is_https_url(url: str, *, allow_blank: bool) -> bool:
    if not url:
        return allow_blank
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    return parts.scheme == "https" and bool(parts.hostname)
