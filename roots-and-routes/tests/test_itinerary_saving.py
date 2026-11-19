from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from app import create_app
from services.budget_service import calculate_trip_budget


class SavedItineraryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "saved-itinerary-test-key",
                "DATABASE_PATH": str(
                    Path(self.temporary_directory.name) / "itineraries.sqlite3"
                ),
            }
        )
        self.client = self.app.test_client()
        self._register(self.client, "Asha Munda", "asha@example.com")

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    @staticmethod
    def _csrf(client) -> str:
        with client.session_transaction() as browser_session:
            return browser_session["_csrf_token"]

    @classmethod
    def _register(cls, client, name: str, email: str) -> None:
        client.get("/register")
        response = client.post(
            "/register",
            data={
                "csrf_token": cls._csrf(client),
                "full_name": name,
                "email": email,
            },
        )
        if response.status_code != 302:
            raise AssertionError(f"Registration failed: {response.status_code}")
        client.get("/workspace/ai-travel-planner")

    def _save_payload(self) -> dict:
        estimate = calculate_trip_budget(
            {
                "budget_inr": 30000,
                "days": 2,
                "travellers": 2,
                "travel_mode": "bus",
                "accommodation_preference": "budget",
                "food_preference": "local",
                "expense_overrides": {"food": 2500},
            }
        )
        return {
            "csrf_token": self._csrf(self.client),
            "title": "Falls weekend",
            "destination_ids": ["hundru-falls"],
            "itinerary": {
                "answer": "A sourced, catalogue-grounded draft.",
                "mode": "rules",
                "notice": "Verify conditions before travel.",
                "sources": [
                    {
                        "label": "Destination record",
                        "url": "https://example.org/hundru",
                    }
                ],
            },
            "budget": estimate,
        }

    def test_saving_retrieving_and_deleting_is_user_scoped(self) -> None:
        planner_page = self.client.get("/workspace/ai-travel-planner")
        self.assertIn(b"Save itinerary", planner_page.data)
        self.assertIn(b"data-save-endpoint", planner_page.data)

        saved = self.client.post("/api/itineraries", json=self._save_payload())
        self.assertEqual(saved.status_code, 201)
        saved_id = saved.get_json()["id"]

        response = self.client.get("/api/itineraries")
        self.assertEqual(response.status_code, 200)
        stored = response.get_json()["itineraries"]
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0]["id"], saved_id)
        self.assertEqual(stored[0]["destination_names"], ["Hundru Falls"])
        self.assertEqual(stored[0]["itinerary"]["budget"]["expenses"]["food"]["amount_inr"], 2500)

        itinerary_page = self.client.get("/workspace/my-itineraries")
        self.assertEqual(itinerary_page.status_code, 200)
        self.assertIn(b"Falls weekend", itinerary_page.data)
        self.assertIn(b"A sourced, catalogue-grounded draft.", itinerary_page.data)

        other_client = self.app.test_client()
        self._register(other_client, "Biru Munda", "biru@example.com")
        self.assertEqual(other_client.get("/api/itineraries").get_json()["itineraries"], [])
        forbidden_delete = other_client.post(
            f"/itineraries/{saved_id}/delete",
            data={"csrf_token": self._csrf(other_client)},
        )
        self.assertEqual(forbidden_delete.status_code, 302)
        self.assertEqual(len(self.client.get("/api/itineraries").get_json()["itineraries"]), 1)

        deleted = self.client.post(
            f"/itineraries/{saved_id}/delete",
            data={"csrf_token": self._csrf(self.client)},
        )
        self.assertEqual(deleted.status_code, 302)
        self.assertEqual(self.client.get("/api/itineraries").get_json()["itineraries"], [])

    def test_save_validates_csrf_destination_budget_and_sources(self) -> None:
        payload = self._save_payload()
        self.assertEqual(
            self.client.post("/api/itineraries", json={**payload, "csrf_token": "bad"}).status_code,
            400,
        )
        self.assertEqual(
            self.client.post(
                "/api/itineraries",
                json={**payload, "destination_ids": ["not-in-catalogue"]},
            ).status_code,
            400,
        )
        self.assertEqual(
            self.client.post(
                "/api/itineraries",
                json={
                    **payload,
                    "itinerary": {
                        **payload["itinerary"],
                        "sources": [{"label": "Unsafe", "url": "javascript:alert(1)"}],
                    },
                },
            ).status_code,
            400,
        )
        self.assertEqual(
            self.client.post(
                "/api/itineraries",
                json={**payload, "budget": {"inputs": {"days": 0}}},
            ).status_code,
            400,
        )
        anonymous = self.app.test_client()
        self.assertEqual(anonymous.get("/api/itineraries").status_code, 401)
        self.assertEqual(anonymous.post("/api/itineraries", json=payload).status_code, 401)

    def test_existing_saved_trips_table_is_migrated_without_data_loss(self) -> None:
        path = Path(self.temporary_directory.name) / "old.sqlite3"
        connection = sqlite3.connect(path)
        with connection:
            connection.executescript(
                """
                CREATE TABLE users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    full_name TEXT NOT NULL,
                    email TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE saved_trips (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    destination_ids TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                INSERT INTO saved_trips (title, destination_ids)
                VALUES ('Legacy trip', '["hundru-falls"]');
                """
            )
        connection.close()
        migrated_app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "saved-itinerary-migration-key",
                "DATABASE_PATH": str(path),
            }
        )
        with migrated_app.app_context():
            from database import get_db

            columns = {
                row["name"] for row in get_db().execute("PRAGMA table_info(saved_trips)")
            }
            legacy = get_db().execute(
                "SELECT title, destination_ids, user_id, itinerary_json FROM saved_trips"
            ).fetchone()
        self.assertIn("user_id", columns)
        self.assertIn("itinerary_json", columns)
        self.assertEqual(legacy["title"], "Legacy trip")
        self.assertEqual(json.loads(legacy["destination_ids"]), ["hundru-falls"])
        self.assertIsNone(legacy["user_id"])
        self.assertEqual(json.loads(legacy["itinerary_json"]), {})


if __name__ == "__main__":
    unittest.main()
