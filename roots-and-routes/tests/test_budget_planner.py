from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import create_app
from services.budget_service import (
    BudgetValidationError,
    calculate_trip_budget,
)
from services.destination_service import get_destinations
from services.travel_companion_service import answer_travel_question


class _FakeProviderResponse:
    def __enter__(self) -> "_FakeProviderResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return b'{"choices":[{"message":{"content":"A grounded itinerary draft."}}]}'


class BudgetServiceTests(unittest.TestCase):
    def test_calculates_sample_costs_and_per_person_estimate(self) -> None:
        result = calculate_trip_budget(
            {
                "budget_inr": 100000,
                "days": 3,
                "travellers": 2,
                "travel_mode": "bus",
                "accommodation_preference": "standard",
                "food_preference": "local",
            }
        )

        self.assertEqual(
            {
                category: item["amount_inr"]
                for category, item in result["expenses"].items()
            },
            {
                "accommodation": 3600,
                "food": 3900,
                "activities": 3000,
                "other": 2100,
            },
        )
        self.assertEqual(result["total_estimate_inr"], 12600)
        self.assertEqual(result["per_person_inr"], 6300)
        self.assertEqual(result["remaining_budget_inr"], 87400)
        self.assertFalse(result["over_budget"])
        self.assertIn("illustrative sample assumptions", result["sample_notice"])

    def test_private_car_capacity_and_manual_expense_overrides_are_applied(self) -> None:
        sample_estimate = calculate_trip_budget(
            {
                "budget_inr": 100000,
                "days": 1,
                "travellers": 5,
                "travel_mode": "private_car",
                "accommodation_preference": "budget",
                "food_preference": "budget",
            }
        )
        self.assertEqual(sample_estimate["expenses"]["accommodation"]["amount_inr"], 0)

        result = calculate_trip_budget(
            {
                "budget_inr": 1000,
                "days": 1,
                "travellers": 5,
                "travel_mode": "private_car",
                "accommodation_preference": "budget",
                "food_preference": "budget",
                "expense_overrides": {
                    "accommodation": 10001,
                    "food": 0,
                    "activities": 0,
                    "other": 0,
                },
            }
        )

        self.assertEqual(result["expenses"]["accommodation"]["amount_inr"], 10001)
        self.assertTrue(result["expenses"]["accommodation"]["is_user_override"])
        self.assertEqual(result["total_estimate_inr"], 10001)
        self.assertEqual(result["remaining_budget_inr"], -9001)
        self.assertTrue(result["over_budget"])

    def test_rejects_out_of_range_or_fractional_inputs(self) -> None:
        payload = {
            "budget_inr": 10000,
            "days": 2,
            "travellers": 2,
            "travel_mode": "bus",
            "accommodation_preference": "budget",
            "food_preference": "budget",
        }
        for field, value in (
            ("days", 0),
            ("travellers", 1.5),
            ("travel_mode", ["train"]),
            ("travel_mode", "helicopter"),
        ):
            with self.subTest(field=field):
                with self.assertRaises(BudgetValidationError):
                    calculate_trip_budget({**payload, field: value})

    def test_planner_ai_receives_validated_trip_constraints_not_raw_prompt(self) -> None:
        destinations = get_destinations(
            str(Path(__file__).resolve().parents[1] / "data" / "destinations.csv")
        )
        constraints = {
            "days": 3,
            "travellers": 2,
            "budget_inr": 30000,
            "travel_mode": "Train",
            "estimated_costs_inr": {"food": 2500},
            "estimates_are_illustrative": True,
        }
        captured_requests = []

        def fake_urlopen(request, timeout):
            captured_requests.append(request)
            return _FakeProviderResponse()

        with patch(
            "services.travel_companion_service.urlopen",
            side_effect=fake_urlopen,
        ):
            result = answer_travel_question(
                "Create a 3-day Jharkhand itinerary within ₹30000 for 2 travellers.",
                destinations,
                None,
                events_path="unused.csv",
                overpass_url="https://overpass.example/api",
                user_agent="test-agent",
                llm_api_key="test-key",
                llm_endpoint="https://provider.example/v1/chat/completions",
                llm_model="test-model",
                allow_trip_ai=True,
                user_trip_constraints=constraints,
            )

        provider_payload = json.loads(captured_requests[0].data.decode("utf-8"))
        prompt = json.loads(provider_payload["messages"][1]["content"])
        self.assertEqual(result["mode"], "ai")
        self.assertEqual(prompt["user_trip_constraints"], constraints)
        self.assertNotIn("current_question", prompt)


class BudgetPlannerApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "test-session-secret",
                "DATABASE_PATH": str(Path(self.temporary_directory.name) / "test.sqlite3"),
                "TRAVEL_COMPANION_LLM_API_KEY": "",
            }
        )
        self.client = self.app.test_client()

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def register_user(self) -> str:
        self.client.get("/register")
        with self.client.session_transaction() as browser_session:
            token = browser_session["_csrf_token"]
        response = self.client.post(
            "/register",
            data={
                "csrf_token": token,
                "full_name": "Asha Munda",
                "email": "asha@example.com",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.client.get("/workspace/smart-budget")
        with self.client.session_transaction() as browser_session:
            return browser_session["_csrf_token"]

    @staticmethod
    def trip_payload() -> dict:
        return {
            "budget_inr": 30000,
            "days": 3,
            "travellers": 2,
            "travel_mode": "train",
            "accommodation_preference": "standard",
            "food_preference": "local",
            "expense_overrides": {"activities": 0},
        }

    def test_budget_api_requires_authentication_and_csrf(self) -> None:
        unauthorized = self.client.post("/api/budget-estimate", json=self.trip_payload())
        self.assertEqual(unauthorized.status_code, 401)

        token = self.register_user()
        invalid_csrf = self.client.post(
            "/api/budget-estimate",
            json={**self.trip_payload(), "csrf_token": "invalid"},
        )
        self.assertEqual(invalid_csrf.status_code, 400)

        response = self.client.post(
            "/api/budget-estimate",
            json={**self.trip_payload(), "csrf_token": token},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["expenses"]["activities"]["amount_inr"], 0)

    def test_calculator_and_planner_pages_render_with_budget_handoff_fields(self) -> None:
        self.register_user()
        calculator = self.client.get("/workspace/smart-budget")
        self.assertEqual(calculator.status_code, 200)
        self.assertIn(b'id="budget-form"', calculator.data)
        self.assertIn(b"Illustrative sample rates", calculator.data)
        self.assertIn(b'id="budget-chart"', calculator.data)

        planner = self.client.get("/workspace/ai-travel-planner")
        self.assertEqual(planner.status_code, 200)
        self.assertIn(b'id="planner-form"', planner.data)
        self.assertIn(b'value="30000"', planner.data)
        self.assertIn(b'value="3"', planner.data)

    def test_planner_generates_grounded_days_without_claiming_budget_fit(self) -> None:
        token = self.register_user()
        destination = get_destinations(self.app.config["DESTINATIONS_PATH"])[0]
        payload = {
            **self.trip_payload(),
            "csrf_token": token,
            "destination_ids": [destination.id],
        }

        response = self.client.post("/api/planner/generate", json=payload)

        self.assertEqual(response.status_code, 200)
        result = response.get_json()
        self.assertEqual(result["itinerary"]["mode"], "rules")
        self.assertIn(f"Day 1: {destination.name}", result["itinerary"]["answer"])
        self.assertIn("Day 3: Flexible day", result["itinerary"]["answer"])
        self.assertIn("can't confirm the trip fits", result["itinerary"]["answer"])
        self.assertTrue(result["budget"]["expenses"]["activities"]["is_user_override"])

    def test_planner_rejects_unknown_destination_ids(self) -> None:
        token = self.register_user()
        response = self.client.post(
            "/api/planner/generate",
            json={
                **self.trip_payload(),
                "csrf_token": token,
                "destination_ids": ["not-a-catalogue-place"],
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("catalogue", response.get_json()["error"])
