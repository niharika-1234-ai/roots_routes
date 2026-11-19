from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs

from app import create_app
from services.map_service import MapServiceError, get_nearby_places
from services.safety_service import EMERGENCY_CONTACTS


class TouristSafetyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        self.app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "test-session-secret",
                "DATABASE_PATH": str(Path(self.temp_directory.name) / "test.sqlite3"),
            }
        )
        self.client = self.app.test_client()

    def tearDown(self) -> None:
        self.temp_directory.cleanup()

    def register_user(self) -> str:
        self.client.get("/register")
        with self.client.session_transaction() as browser_session:
            csrf_token = browser_session["_csrf_token"]
        response = self.client.post(
            "/register",
            data={
                "csrf_token": csrf_token,
                "full_name": "Asha Munda",
                "email": "asha@example.com",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.client.get("/workspace/tourist-safety")
        with self.client.session_transaction() as browser_session:
            return browser_session["_csrf_token"]

    def safety_payload(self, csrf_token: str, **updates: object) -> dict:
        payload = {
            "csrf_token": csrf_token,
            "category": "hospitals",
            "coordinates": {"latitude": 23.3441, "longitude": 85.3096},
            "radius": 5000,
        }
        payload.update(updates)
        return payload

    def test_safety_workspace_uses_official_contacts_and_optional_location_controls(self) -> None:
        self.register_user()

        response = self.client.get("/workspace/tourist-safety")

        self.assertEqual(response.status_code, 200)
        for expected in (
            b"Call 112",
            b"Emergency Response Support System",
            b"jhpolice.gov.in/contact-us",
            b"7542029602",
            b"id=\"safety-use-location\"",
            b"id=\"safety-clear-location\"",
            b"id=\"safety-include-location\"",
            b"id=\"safety-checkin-form\"",
            b"id=\"safety-prepare-sos\"",
            b"Prepare SOS message",
            b"Prepare an email or SMS draft for a trip check-in or an SOS",
            b"does not send, store, or confirm delivery of messages.",
            b'data-nearby-category="hospitals"',
            b'data-nearby-category="police"',
            b'id="use-current-location"',
            b'id="route-destination"',
            b"static/js/safety.js",
        ):
            self.assertIn(expected, response.data)

        emergency_number = next(item for item in EMERGENCY_CONTACTS if item["number"] == "112")
        self.assertTrue(emergency_number["source_url"].startswith("https://jhpolice.gov.in/"))

    def test_nearby_safety_api_requires_authentication_csrf_and_valid_input(self) -> None:
        anonymous = self.client.post("/api/safety/nearby", json={})
        self.assertEqual(anonymous.status_code, 401)
        private_category_get = self.client.get(
            "/api/nearby?category=hospitals&lat=23.3441&lon=85.3096"
        )
        self.assertEqual(private_category_get.status_code, 400)

        csrf_token = self.register_user()
        missing_csrf = self.client.post(
            "/api/safety/nearby",
            json=self.safety_payload(""),
        )
        self.assertEqual(missing_csrf.status_code, 400)

        invalid_category = self.client.post(
            "/api/safety/nearby",
            json=self.safety_payload(csrf_token, category="restaurants"),
        )
        self.assertEqual(invalid_category.status_code, 400)

        invalid_coordinates = self.client.post(
            "/api/safety/nearby",
            json=self.safety_payload(
                csrf_token,
                coordinates={"latitude": 91, "longitude": 85},
            ),
        )
        self.assertEqual(invalid_coordinates.status_code, 400)

        invalid_radius = self.client.post(
            "/api/safety/nearby",
            json=self.safety_payload(csrf_token, radius=True),
        )
        self.assertEqual(invalid_radius.status_code, 400)

    def test_nearby_safety_api_returns_mapped_records_and_handles_provider_failure(self) -> None:
        csrf_token = self.register_user()
        places = [{"name": "Mapped hospital", "category": "hospitals"}]
        with patch("routes.api.get_nearby_places", return_value=places) as nearby:
            response = self.client.post(
                "/api/safety/nearby",
                json=self.safety_payload(csrf_token),
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"places": places})
        nearby.assert_called_once_with(
            "hospitals",
            23.3441,
            85.3096,
            5000,
            self.app.config["OVERPASS_URL"],
            self.app.config["NOMINATIM_USER_AGENT"],
        )

        with patch(
            "routes.api.get_nearby_places",
            side_effect=MapServiceError("provider unavailable"),
        ):
            failure = self.client.post(
                "/api/safety/nearby",
                json=self.safety_payload(csrf_token, category="police"),
            )
        self.assertEqual(failure.status_code, 502)
        self.assertEqual(
            failure.get_json(),
            {"error": "Nearby safety services are temporarily unavailable."},
        )


class SafetyNearbyServiceTests(unittest.TestCase):
    def test_hospital_and_police_queries_only_return_named_osm_places(self) -> None:
        for category, amenity, place_type in (
            ("hospitals", "hospital", "Hospital"),
            ("police", "police", "Police station"),
        ):
            with self.subTest(category=category):
                payload = {
                    "elements": [
                        {
                            "type": "node",
                            "id": 789,
                            "lat": 23.35,
                            "lon": 85.31,
                            "tags": {"name": "Mapped service", "amenity": amenity},
                        },
                        {
                            "type": "node",
                            "id": 790,
                            "lat": 23.36,
                            "lon": 85.32,
                            "tags": {"amenity": amenity},
                        },
                    ]
                }
                with patch("services.map_service._request_json", return_value=payload) as request:
                    places = get_nearby_places(
                        category,
                        23.3441,
                        85.3096,
                        5000,
                        "https://overpass.example/interpreter",
                        "test",
                    )

                self.assertEqual(len(places), 1)
                self.assertEqual(places[0]["place_type"], place_type)
                self.assertEqual(
                    places[0]["source_url"],
                    "https://www.openstreetmap.org/node/789",
                )
                query = parse_qs(
                    request.call_args.kwargs["body"].decode("utf-8")
                )["data"][0]
                self.assertIn(f'["amenity"="{amenity}"]', query)

    def test_safety_service_searches_do_not_cache_coordinates_or_results(self) -> None:
        payload = {
            "elements": [
                {
                    "type": "node",
                    "id": 791,
                    "lat": 23.45,
                    "lon": 85.32,
                    "tags": {"name": "Mapped hospital", "amenity": "hospital"},
                }
            ]
        }
        with patch("services.map_service._request_json", return_value=payload) as request:
            for _ in range(2):
                get_nearby_places(
                    "hospitals",
                    23.4471,
                    85.3278,
                    5000,
                    "https://overpass.example/interpreter",
                    "test",
                )

        self.assertEqual(request.call_count, 2)


if __name__ == "__main__":
    unittest.main()
