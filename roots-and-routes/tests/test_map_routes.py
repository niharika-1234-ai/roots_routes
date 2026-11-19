from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from app import create_app
from services.map_service import MapServiceError, get_nearby_places, get_road_routes


class MapApiTests(unittest.TestCase):
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

    def test_geocode_requires_a_query_and_returns_nominatim_results(self) -> None:
        invalid = self.client.get("/api/geocode?q=ab")
        self.assertEqual(invalid.status_code, 400)

        results = [
            {
                "label": "Ranchi, Jharkhand, India",
                "latitude": 23.3441,
                "longitude": 85.3096,
                "source_url": "https://www.openstreetmap.org/node/1",
            }
        ]
        with patch("routes.api.geocode_locations", return_value=results) as geocode:
            response = self.client.get("/api/geocode?q=Ranchi")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"results": results})
        geocode.assert_called_once_with(
            "Ranchi",
            self.app.config["NOMINATIM_BASE_URL"],
            self.app.config["NOMINATIM_USER_AGENT"],
        )

    def test_route_validates_coordinates_and_surfaces_provider_failures(self) -> None:
        invalid = self.client.get("/api/route?source_lat=95&source_lon=85")
        self.assertEqual(invalid.status_code, 400)

        route_response = {"code": "Ok", "routes": [{"distance": 24000, "duration": 1800}]}
        with patch("routes.api.get_road_routes", return_value=route_response) as route:
            response = self.client.get(
                "/api/route?source_lat=23.1&source_lon=85.2"
                "&destination_lat=24.1&destination_lon=86.2"
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), route_response)
        route.assert_called_once_with(
            23.1,
            85.2,
            24.1,
            86.2,
            self.app.config["OSRM_BASE_URL"],
            self.app.config["NOMINATIM_USER_AGENT"],
        )

        with patch(
            "routes.api.get_road_routes",
            side_effect=MapServiceError("provider unavailable"),
        ):
            failure = self.client.get(
                "/api/route?source_lat=23.1&source_lon=85.2"
                "&destination_lat=24.1&destination_lon=86.2"
            )
        self.assertEqual(failure.status_code, 502)
        self.assertIn("temporarily unavailable", failure.get_json()["error"])

    def test_nearby_categories_are_validated_and_provider_errors_are_reported(self) -> None:
        invalid_category = self.client.get(
            "/api/nearby?category=anything&lat=23&lon=85"
        )
        self.assertEqual(invalid_category.status_code, 400)
        invalid_radius = self.client.get(
            "/api/nearby?category=restaurants&lat=23&lon=85&radius=20000"
        )
        self.assertEqual(invalid_radius.status_code, 400)

        places = [{"name": "Local cafe", "category": "restaurants"}]
        with patch("routes.api.get_nearby_places", return_value=places) as nearby:
            response = self.client.get(
                "/api/nearby?category=restaurants&lat=23.4&lon=85.3"
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"places": places})
        nearby.assert_called_once_with(
            "restaurants",
            23.4,
            85.3,
            5000,
            self.app.config["OVERPASS_URL"],
            self.app.config["NOMINATIM_USER_AGENT"],
        )

        with patch(
            "routes.api.get_nearby_places",
            side_effect=MapServiceError("provider unavailable"),
        ):
            failure = self.client.get(
                "/api/nearby?category=events&lat=23.4&lon=85.3"
            )
        self.assertEqual(failure.status_code, 502)
        self.assertIn("temporarily unavailable", failure.get_json()["error"])

    def test_map_workspace_exposes_route_and_nearby_controls(self) -> None:
        self.client.get("/register")
        with self.client.session_transaction() as browser_session:
            csrf_token = browser_session["_csrf_token"]
        self.client.post(
            "/register",
            data={
                "csrf_token": csrf_token,
                "full_name": "Asha Munda",
                "email": "asha@example.com",
            },
        )
        response = self.client.get("/workspace/interactive-maps")
        self.assertEqual(response.status_code, 200)
        for control in (
            b'id="route-planner-form"',
            b'id="route-source"',
            b'id="route-destination"',
            b'id="use-current-location"',
            b'id="catalogue-destination"',
            b'id="route-results"',
            b'data-nearby-category="restaurants"',
            b'data-nearby-category="hotels"',
            b'data-nearby-category="events"',
            b'data-nearby-category="attractions"',
        ):
            self.assertIn(control, response.data)


class MapServiceTests(unittest.TestCase):
    def test_route_requests_osrm_road_geometry_steps_and_alternatives(self) -> None:
        response = {
            "code": "Ok",
            "routes": [
                {
                    "distance": 24000,
                    "duration": 1800,
                    "geometry": {"coordinates": [[85.2, 23.1], [86.2, 24.1]]},
                    "legs": [],
                }
            ],
        }
        with patch("services.map_service._request_json", return_value=response) as request:
            result = get_road_routes(23.1, 85.2, 24.1, 86.2, "https://router.example", "test")

        self.assertEqual(result, response)
        url = request.call_args.args[0]
        self.assertIn("/route/v1/driving/85.200000,23.100000;86.200000,24.100000", url)
        options = parse_qs(urlparse(url).query)
        self.assertEqual(options["steps"], ["true"])
        self.assertEqual(options["alternatives"], ["true"])
        self.assertEqual(options["geometries"], ["geojson"])

    def test_nearby_service_builds_category_query_and_returns_named_places(self) -> None:
        response = {
            "elements": [
                {
                    "type": "node",
                    "id": 123,
                    "lat": 23.4,
                    "lon": 85.3,
                    "tags": {"name": "Local cafe", "amenity": "cafe", "cuisine": "indian"},
                },
                {
                    "type": "node",
                    "id": 124,
                    "lat": 23.4,
                    "lon": 85.3,
                    "tags": {"amenity": "restaurant"},
                },
            ]
        }
        with patch("services.map_service._request_json", return_value=response) as request:
            places = get_nearby_places(
                "restaurants",
                23.4,
                85.3,
                5000,
                "https://overpass.example/interpreter",
                "test",
            )

        self.assertEqual(len(places), 1)
        self.assertEqual(places[0]["name"], "Local cafe")
        self.assertEqual(places[0]["source_url"], "https://www.openstreetmap.org/node/123")
        query_body = parse_qs(request.call_args.kwargs["body"].decode("utf-8"))["data"][0]
        self.assertIn('["amenity"="restaurant"]', query_body)
        self.assertIn("around:5000,23.400000,85.300000", query_body)


if __name__ == "__main__":
    unittest.main()
