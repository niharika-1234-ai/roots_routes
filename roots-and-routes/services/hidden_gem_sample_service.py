from __future__ import annotations

import json
from pathlib import Path
from typing import Any


_SCORE_FIELDS = (
    "natural_value",
    "cultural_value",
    "popularity",
    "accessibility",
    "sustainability_score",
)


class HiddenGemSampleDataError(Exception):
    """Raised when fictional hidden-gem examples are missing or invalid."""


def get_hidden_gem_samples(
    path: str | Path,
    query: str = "",
    category: str = "",
) -> list[dict[str, Any]]:
    try:
        with Path(path).open(encoding="utf-8") as sample_file:
            data = json.load(sample_file)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise HiddenGemSampleDataError(
            "The hidden-gem sample catalogue could not be read."
        ) from error

    if not isinstance(data, dict) or not isinstance(data.get("samples"), list):
        raise HiddenGemSampleDataError(
            "The hidden-gem sample catalogue must contain a samples list."
        )

    normalized_query = query.strip().casefold()
    normalized_category = category.strip().casefold()
    seen_ids: set[str] = set()
    results = []
    for sample in data["samples"]:
        if not isinstance(sample, dict):
            raise HiddenGemSampleDataError("Each hidden-gem sample must be an object.")
        if not all(
            isinstance(sample.get(field), str) and sample[field].strip()
            for field in ("id", "name", "district", "category", "description")
        ):
            raise HiddenGemSampleDataError(
                "Each hidden-gem sample must include its identity and description."
            )
        sample_id = sample["id"].strip()
        if sample_id in seen_ids:
            raise HiddenGemSampleDataError("Hidden-gem sample IDs must be unique.")
        seen_ids.add(sample_id)
        if any(
            isinstance(sample.get(field), bool)
            or not isinstance(sample.get(field), int)
            or not 0 <= sample[field] <= 100
            for field in _SCORE_FIELDS
        ):
            raise HiddenGemSampleDataError(
                f"Hidden-gem sample {sample_id} has an invalid illustrative rating."
            )

        searchable = " ".join(
            str(sample[field])
            for field in ("name", "district", "category", "description")
        ).casefold()
        if normalized_query and normalized_query not in searchable:
            continue
        if normalized_category and sample["category"].casefold() != normalized_category:
            continue

        results.append(
            {
                **sample,
                "ranking_score": round(
                    (
                        sample["natural_value"]
                        + sample["cultural_value"]
                        + (100 - sample["popularity"])
                        + sample["accessibility"]
                        + sample["sustainability_score"]
                    )
                    / 5
                ),
            }
        )

    return sorted(results, key=lambda item: (-item["ranking_score"], item["name"]))
