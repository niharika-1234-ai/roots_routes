from __future__ import annotations

import math
from typing import Any


TRAVEL_MODES = {
    "bus": {
        "label": "Intercity bus",
        "sample_rate_inr": 1600,
        "basis": "per traveller, estimated return fare",
        "per_vehicle": False,
    },
    "train": {
        "label": "Train",
        "sample_rate_inr": 2200,
        "basis": "per traveller, estimated return fare",
        "per_vehicle": False,
    },
    "private_car": {
        "label": "Private car",
        "sample_rate_inr": 4800,
        "basis": "per car, estimated return fuel and local travel; up to 4 travellers",
        "per_vehicle": True,
    },
}

ACCOMMODATION_PREFERENCES = {
    "budget": {
        "label": "Budget stay",
        "sample_rate_inr": 900,
        "basis": "per room, per night",
    },
    "standard": {
        "label": "Standard stay",
        "sample_rate_inr": 1800,
        "basis": "per room, per night",
    },
    "comfort": {
        "label": "Comfort stay",
        "sample_rate_inr": 3200,
        "basis": "per room, per night",
    },
}

FOOD_PREFERENCES = {
    "budget": {
        "label": "Budget meals",
        "sample_rate_inr": 450,
        "basis": "per traveller, per day",
    },
    "local": {
        "label": "Local food mix",
        "sample_rate_inr": 650,
        "basis": "per traveller, per day",
    },
    "comfort": {
        "label": "Comfort meals",
        "sample_rate_inr": 1100,
        "basis": "per traveller, per day",
    },
}

ACTIVITY_SAMPLE_RATE_INR = 500
OTHER_SAMPLE_RATE_INR = 350
MAX_BUDGET_INR = 10_000_000
MAX_EXPENSE_INR = 100_000_000
MAX_TRAVELLERS = 1000
EXPENSE_CATEGORIES = (
    "accommodation",
    "food",
    "activities",
    "other",
)


class BudgetValidationError(ValueError):
    """Raised when budget calculator inputs are invalid."""


def get_budget_options() -> dict[str, Any]:
    return {
        "travel_modes": {},
        "accommodation_preferences": ACCOMMODATION_PREFERENCES,
        "food_preferences": FOOD_PREFERENCES,
        "activity_sample_rate_inr": ACTIVITY_SAMPLE_RATE_INR,
        "activity_basis": "per traveller, per day",
        "other_sample_rate_inr": OTHER_SAMPLE_RATE_INR,
        "other_basis": "per traveller, per day",
        "expense_categories": [
            {"id": "accommodation", "label": "Accommodation"},
            {"id": "food", "label": "Food"},
            {"id": "activities", "label": "Activities"},
            {"id": "other", "label": "Other expenses"},
        ],
    }


def calculate_trip_budget(payload: object) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise BudgetValidationError("Send the budget details as a JSON object.")

    budget = _integer(payload.get("budget_inr"), "Total budget", 1, MAX_BUDGET_INR)
    days = _integer(payload.get("days"), "Number of days", 1, 30)
    travellers = _integer(payload.get("travellers"), "Number of travellers", 1, MAX_TRAVELLERS)
    travel_mode = payload.get("travel_mode")
    accommodation = payload.get("accommodation_preference")
    food = payload.get("food_preference")
    if not isinstance(travel_mode, str) or travel_mode not in TRAVEL_MODES:
        raise BudgetValidationError("Choose a supported travel mode.")
    if (
        not isinstance(accommodation, str)
        or accommodation not in ACCOMMODATION_PREFERENCES
    ):
        raise BudgetValidationError("Choose a supported accommodation preference.")
    if not isinstance(food, str) or food not in FOOD_PREFERENCES:
        raise BudgetValidationError("Choose a supported food preference.")

    overrides = _read_expense_overrides(payload.get("expense_overrides", {}))
    rooms = math.ceil(travellers / 2)
    nights = max(days - 1, 0)
    estimated_amounts = {
        "accommodation": (
            ACCOMMODATION_PREFERENCES[accommodation]["sample_rate_inr"]
            * rooms
            * nights
        ),
        "food": FOOD_PREFERENCES[food]["sample_rate_inr"] * travellers * days,
        "activities": ACTIVITY_SAMPLE_RATE_INR * travellers * days,
        "other": OTHER_SAMPLE_RATE_INR * travellers * days,
    }
    expenses = {
        category: {
            "amount_inr": overrides.get(category, amount),
            "is_user_override": category in overrides,
        }
        for category, amount in estimated_amounts.items()
    }
    total_estimate = sum(item["amount_inr"] for item in expenses.values())
    return {
        "inputs": {
            "budget_inr": budget,
            "days": days,
            "travellers": travellers,
            "travel_mode": travel_mode,
            "accommodation_preference": accommodation,
            "food_preference": food,
        },
        "expenses": expenses,
        "expense_overrides": overrides,
        "total_estimate_inr": total_estimate,
        "per_person_inr": round(total_estimate / travellers, 2),
        "remaining_budget_inr": budget - total_estimate,
        "over_budget": total_estimate > budget,
        "sample_notice": (
            "All non-overridden amounts use illustrative sample assumptions, not live "
            "quotes or verified prices. Edit each category to match your own research."
        ),
    }


def _integer(value: object, label: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise BudgetValidationError(
            f"{label} must be a whole number from {minimum:,} to {maximum:,}."
        )
    return value


def _read_expense_overrides(value: object) -> dict[str, int]:
    if not isinstance(value, dict):
        raise BudgetValidationError("Editable expense amounts must be an object.")
    if set(value) - set(EXPENSE_CATEGORIES):
        raise BudgetValidationError("Choose a valid expense category.")

    overrides = {}
    for category, amount in value.items():
        overrides[category] = _integer(
            amount,
            f"{category.replace('_', ' ').capitalize()} estimate",
            0,
            MAX_EXPENSE_INR,
        )
    return overrides
