from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from urllib.error import URLError
from unittest.mock import patch

from app import create_app
from services.destination_service import get_destinations
from services.event_service import REQUIRED_COLUMNS
from services.map_service import MapServiceError
from services.travel_companion_service import answer_travel_question


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


class TravelCompanionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp_directory.name)
        self.events_path = self.directory / "cultural_events.csv"
        self.events_path.write_text(
            ",".join(sorted(REQUIRED_COLUMNS)) + "\n",
            encoding="utf-8",
        )
        self.app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "test-session-secret",
                "DATABASE_PATH": str(self.directory / "test.sqlite3"),
                "CULTURAL_EVENTS_PATH": self.events_path,
                "TRAVEL_COMPANION_LLM_API_KEY": "",
            }
        )
        self.client = self.app.test_client()

    def tearDown(self) -> None:
        self.temp_directory.cleanup()

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
        self.client.get("/workspace/ai-travel-companion")
        with self.client.session_transaction() as browser_session:
            return browser_session["_csrf_token"]

    def post_chat(self, token: str, message: str):
        return self.client.post(
            "/api/companion/chat",
            json={"message": message, "csrf_token": token},
        )

    def test_chat_api_requires_authentication_csrf_and_bounded_input(self) -> None:
        unauthorized = self.client.post(
            "/api/companion/chat",
            json={"message": "Hello", "csrf_token": "missing"},
        )
        self.assertEqual(unauthorized.status_code, 401)

        token = self.register_user()
        invalid_csrf = self.post_chat("invalid", "Hello")
        self.assertEqual(invalid_csrf.status_code, 400)
        too_long = self.post_chat(token, "x" * 1201)
        self.assertEqual(too_long.status_code, 400)
        oversized_body = self.client.post(
            "/api/companion/chat",
            json={"message": "Hello", "csrf_token": token, "padding": "x" * 9000},
        )
        self.assertEqual(oversized_body.status_code, 413)

    def test_companion_workspace_renders_chat_and_session_context(self) -> None:
        self.register_user()
        response = self.client.get("/workspace/ai-travel-companion")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'id="companion-form"', response.data)
        self.assertIn(b'id="companion-messages"', response.data)
        self.assertIn(b"Your trip context", response.data)
        self.assertIn(b"Local mode keeps messages on this server.", response.data)

    def test_waterfall_answers_are_sourced_and_context_is_preserved(self) -> None:
        token = self.register_user()
        response = self.post_chat(token, "Find waterfalls near Ranchi.")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["mode"], "rules")
        self.assertIn("Hundru Falls", payload["answer"])
        self.assertIn("Dassam Falls", payload["answer"])
        self.assertIn("Jonha Falls", payload["answer"])
        self.assertIn("does not establish road distance", payload["answer"])
        self.assertEqual(
            payload["context"]["destination_names"],
            ["Hundru Falls", "Dassam Falls", "Jonha Falls"],
        )
        self.assertEqual(len(payload["sources"]), 3)

        mapped_stay = {
            "name": "Mapped Guest House",
            "place_type": "Guest house",
            "distance_km": 4.2,
            "cuisine": "",
            "rating": "",
            "price": "",
            "booking_url": "",
            "source_url": "https://www.openstreetmap.org/node/123",
        }
        with patch(
            "services.travel_companion_service.get_nearby_places",
            return_value=[mapped_stay],
        ) as nearby_lookup:
            follow_up = self.post_chat(token, "Find hotels near the first one.")

        self.assertEqual(follow_up.status_code, 200)
        follow_up_payload = follow_up.get_json()
        self.assertIn("Mapped Guest House", follow_up_payload["answer"])
        self.assertIn("Hundru Falls", follow_up_payload["answer"])
        nearby_lookup.assert_called_once()
        self.assertEqual(follow_up_payload["context"]["destination_names"][0], "Hundru Falls")

    def test_budget_answer_does_not_claim_cost_fit_and_remembers_constraints(self) -> None:
        token = self.register_user()
        response = self.post_chat(
            token,
            "Suggest a three-day Jharkhand trip within ₹5000.",
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["context"]["duration_days"], 3)
        self.assertEqual(payload["context"]["budget_inr"], 5000)
        self.assertIn("Day 1:", payload["answer"])
        self.assertIn("₹5,000", payload["answer"])
        self.assertIn("can't confirm the trip fits", payload["answer"])

        page = self.client.get("/workspace/ai-travel-companion")
        self.assertIn(b"3 days", page.data)
        self.assertIn("₹5,000".encode("utf-8"), page.data)
        cleared = self.post_chat(token, "Clear trip context")
        self.assertEqual(cleared.get_json()["context"]["duration_days"], None)
        self.assertEqual(cleared.get_json()["context"]["budget_inr"], None)

    def test_no_crowd_or_event_claim_without_catalogue_evidence(self) -> None:
        token = self.register_user()
        crowd = self.post_chat(token, "Suggest less crowded destinations.")
        self.assertIn("no source-backed popularity", crowd.get_json()["answer"])
        events = self.post_chat(token, "Recommend local cultural experiences.")
        self.assertIn("don't have any upcoming cultural event records", events.get_json()["answer"])
        self.assertIn("Jharkhand Tourism festival information", events.get_json()["sources"][0]["label"])

    def test_llm_receives_grounded_facts_not_raw_message_or_saved_context(self) -> None:
        destinations = get_destinations(self.app.config["DESTINATIONS_PATH"])
        captured_requests = []
        provider_response = _FakeResponse(
            {"choices": [{"message": {"content": "Hundru Falls is listed in Ranchi district."}}]}
        )

        def fake_urlopen(request, timeout):
            captured_requests.append(request)
            self.assertEqual(timeout, 18)
            return provider_response

        with patch(
            "services.travel_companion_service.urlopen",
            side_effect=fake_urlopen,
        ):
            result = answer_travel_question(
                "Tell me about Hundru Falls",
                destinations,
                {"budget_inr": 5000, "duration_days": 3},
                events_path=str(self.events_path),
                overpass_url="https://overpass.example/api",
                user_agent="test-agent",
                llm_api_key="test-key",
                llm_endpoint="https://llm.example/v1/chat/completions",
                llm_model="test-model",
            )

        self.assertEqual(result["mode"], "ai")
        request_payload = json.loads(captured_requests[0].data.decode("utf-8"))
        prompt = request_payload["messages"][1]["content"]
        self.assertNotIn("current_question", prompt)
        self.assertNotIn("budget_inr", prompt)
        self.assertNotIn("5000", prompt)

    def test_llm_failure_uses_local_grounded_answer(self) -> None:
        destinations = get_destinations(self.app.config["DESTINATIONS_PATH"])
        with patch(
            "services.travel_companion_service.urlopen",
            side_effect=URLError("unavailable"),
        ):
            result = answer_travel_question(
                "Tell me about Hundru Falls",
                destinations,
                None,
                events_path=str(self.events_path),
                overpass_url="https://overpass.example/api",
                user_agent="test-agent",
                llm_api_key="test-key",
                llm_endpoint="https://llm.example/v1/chat/completions",
                llm_model="test-model",
            )

        self.assertEqual(result["mode"], "rules")
        self.assertIn("Hundru Falls is listed", result["answer"])
        self.assertIn("AI provider is unavailable", result["notice"])

    def test_map_provider_failure_is_reported_without_inventing_stays(self) -> None:
        destinations = get_destinations(self.app.config["DESTINATIONS_PATH"])
        with patch(
            "services.travel_companion_service.get_nearby_places",
            side_effect=MapServiceError("provider unavailable"),
        ):
            result = answer_travel_question(
                "Find hotels near Hundru Falls",
                destinations,
                None,
                events_path=str(self.events_path),
                overpass_url="https://overpass.example/api",
                user_agent="test-agent",
            )

        self.assertIn("temporarily unavailable", result["answer"])
        self.assertEqual(result["mode"], "rules")
        self.assertEqual(result["sources"][0]["label"], "Hundru Falls")


if __name__ == "__main__":
    unittest.main()
