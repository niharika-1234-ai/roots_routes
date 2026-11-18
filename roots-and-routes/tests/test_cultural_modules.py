from __future__ import annotations

import csv
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from app import create_app
from services.event_service import (
    CULTURAL_EVENT_CATEGORIES,
    CulturalEventDataError,
    REQUIRED_COLUMNS,
    get_cultural_events,
)
from services.map_service import get_nearby_places


class CulturalModuleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        self.events_path = Path(self.temp_directory.name) / "cultural_events.csv"
        self.write_events([])
        self.app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "test-session-secret",
                "DATABASE_PATH": str(Path(self.temp_directory.name) / "test.sqlite3"),
                "CULTURAL_EVENTS_PATH": self.events_path,
            }
        )
        self.client = self.app.test_client()

    def tearDown(self) -> None:
        self.temp_directory.cleanup()

    def write_events(self, events: list[dict[str, str]]) -> None:
        with self.events_path.open("w", encoding="utf-8", newline="") as event_file:
            writer = csv.DictWriter(event_file, fieldnames=sorted(REQUIRED_COLUMNS))
            writer.writeheader()
            writer.writerows(events)

    @staticmethod
    def event_record(
        event_id: str = "sarhul-ranchi",
        start_date: date | None = None,
        category: str = "sarhul",
    ) -> dict[str, str]:
        event_date = start_date or date.today() + timedelta(days=14)
        return {
            "event_id": event_id,
            "name": "Community cultural gathering",
            "category": category,
            "start_date": event_date.isoformat(),
            "end_date": event_date.isoformat(),
            "venue": "Verified community venue",
            "district": "Ranchi",
            "latitude": "23.3441",
            "longitude": "85.3096",
            "description": "A scheduled cultural event with published details.",
            "source_type": "government",
            "source_name": "Jharkhand Tourism",
            "source_url": "https://tourism.jharkhand.gov.in/festivals",
            "verified_on": date.today().isoformat(),
        }

    def register_user(self) -> None:
        self.client.get("/register")
        with self.client.session_transaction() as browser_session:
            token = browser_session["_csrf_token"]
        self.client.post(
            "/register",
            data={
                "csrf_token": token,
                "full_name": "Asha Munda",
                "email": "asha@example.com",
            },
        )

    def test_map_pages_connect_the_three_modules_to_the_interactive_map(self) -> None:
        self.register_user()
        for slug, category in (
            ("restaurants", "restaurants"),
            ("hotels-stays", "hotels"),
            ("cultural-events", "cultural-events"),
        ):
            with self.subTest(slug=slug):
                response = self.client.get(f"/workspace/{slug}")
                self.assertEqual(response.status_code, 200)
                self.assertIn(b'id="destination-map"', response.data)
                self.assertIn(
                    f'data-module-category="{category}"'.encode(),
                    response.data,
                )
                self.assertIn(
                    f'data-nearby-category="{category}"'.encode(),
                    response.data,
                )
        events_page = self.client.get("/workspace/cultural-events")
        for category in CULTURAL_EVENT_CATEGORIES:
            self.assertIn(f'value="{category}"'.encode(), events_page.data)
        self.assertIn(b"Jharkhand Tourism festival information", events_page.data)

    def test_events_api_validates_filters_and_returns_only_curated_records(self) -> None:
        invalid_category = self.client.get("/api/cultural-events?category=unverified")
        self.assertEqual(invalid_category.status_code, 400)
        invalid_coordinates = self.client.get("/api/cultural-events?lat=91&lon=85")
        self.assertEqual(invalid_coordinates.status_code, 400)
        self.assertEqual(self.client.get("/api/cultural-events").get_json(), {"events": []})

        self.write_events([self.event_record()])
        response = self.client.get("/api/cultural-events?lat=23.3441&lon=85.3096")
        self.assertEqual(response.status_code, 200)
        event = response.get_json()["events"][0]
        self.assertEqual(event["name"], "Community cultural gathering")
        self.assertEqual(event["category_label"], "Sarhul")
        self.assertEqual(event["venue"], "Verified community venue")
        self.assertEqual(event["source_url"], "https://tourism.jharkhand.gov.in/festivals")
        self.assertEqual(event["distance_km"], 0)

    def test_event_service_filters_expired_and_distant_records(self) -> None:
        today = date(2026, 1, 1)
        nearby = self.event_record(start_date=today + timedelta(days=10))
        nearby["verified_on"] = today.isoformat()
        nearby["latitude"] = "23.3451"
        expired = self.event_record(
            event_id="past-event",
            start_date=today - timedelta(days=10),
            category="karma",
        )
        expired["verified_on"] = today.isoformat()
        distant = self.event_record(
            event_id="distant-event",
            start_date=today + timedelta(days=20),
            category="sohrai",
        )
        distant["verified_on"] = today.isoformat()
        distant["latitude"] = "24.5"
        self.write_events([nearby, expired, distant])

        events = get_cultural_events(
            self.events_path,
            latitude=23.3441,
            longitude=85.3096,
            radius=5000,
            today=today,
        )
        self.assertEqual([event["event_id"] for event in events], ["sarhul-ranchi"])
        self.assertGreater(events[0]["distance_km"], 0)

    def test_incomplete_or_unsecured_event_sources_are_rejected(self) -> None:
        incomplete = self.event_record()
        incomplete["venue"] = ""
        self.write_events([incomplete])
        with self.assertRaises(CulturalEventDataError):
            get_cultural_events(self.events_path)

        unsecured = self.event_record()
        unsecured["source_url"] = "http://example.org/event"
        self.write_events([unsecured])
        with self.assertRaises(CulturalEventDataError):
            get_cultural_events(self.events_path)


class NearbyPlaceEnrichmentTests(unittest.TestCase):
    def test_restaurant_tags_and_distance_are_returned_without_inferred_values(self) -> None:
        payload = {
            "elements": [
                {
                    "type": "node",
                    "id": 321,
                    "lat": 22.91,
                    "lon": 84.91,
                    "tags": {
                        "name": "Mapped Kitchen",
                        "amenity": "restaurant",
                        "cuisine": "indian;regional",
                        "rating": "4.5",
                        "price": "₹200–400",
                        "website": "https://example.org/restaurant",
                        "booking:website": "https://example.org/book",
                        "wikimedia_commons": "File:Restaurant photo.jpg",
                    },
                }
            ]
        }
        with patch("services.map_service._request_json", return_value=payload):
            places = get_nearby_places(
                "restaurants",
                22.9,
                84.9,
                5000,
                "https://overpass.example/interpreter",
                "test",
            )

        place = places[0]
        self.assertEqual(place["cuisine"], "indian;regional")
        self.assertEqual(place["rating"], "4.5")
        self.assertEqual(place["price"], "₹200–400")
        self.assertEqual(place["price_label"], "Listed price")
        self.assertGreater(place["distance_km"], 0)
        self.assertEqual(place["booking_url"], "https://example.org/book")
        self.assertIn("Special:FilePath/Restaurant%20photo.jpg", place["image_url"])
        self.assertEqual(
            place["image_source_url"],
            "https://commons.wikimedia.org/wiki/File:Restaurant%20photo.jpg",
        )

    def test_stay_types_and_budget_tags_are_explicit(self) -> None:
        payload = {
            "elements": [
                {
                    "type": "node",
                    "id": 401,
                    "lat": 23.401,
                    "lon": 85.301,
                    "tags": {"name": "Hill Hostel", "tourism": "hostel"},
                },
                {
                    "type": "node",
                    "id": 402,
                    "lat": 23.402,
                    "lon": 85.302,
                    "tags": {"name": "Local Homestay", "homestay": "yes"},
                },
                {
                    "type": "node",
                    "id": 403,
                    "lat": 23.403,
                    "lon": 85.303,
                    "tags": {
                        "name": "Budget Tagged Hotel",
                        "tourism": "hotel",
                        "budget": "yes",
                    },
                },
            ]
        }
        with patch("services.map_service._request_json", return_value=payload):
            places = get_nearby_places(
                "hotels",
                23.4,
                85.3,
                5000,
                "https://overpass.example/interpreter",
                "test",
            )

        by_name = {place["name"]: place for place in places}
        self.assertEqual(by_name["Hill Hostel"]["place_type"], "Hostel")
        self.assertFalse(by_name["Hill Hostel"]["budget_tagged"])
        self.assertEqual(by_name["Local Homestay"]["place_type"], "Homestay")
        self.assertFalse(by_name["Local Homestay"]["budget_tagged"])
        self.assertEqual(by_name["Budget Tagged Hotel"]["place_type"], "Hotel")
        self.assertTrue(by_name["Budget Tagged Hotel"]["budget_tagged"])
        self.assertTrue(all(not place["price"] and not place["rating"] for place in places))


if __name__ == "__main__":
    unittest.main()
