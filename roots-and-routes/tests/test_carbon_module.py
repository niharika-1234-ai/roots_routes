from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import create_app
from services.carbon_service import (
    CarbonFactorDataError,
    calculate_carbon_footprint,
    get_transport_factors,
)
from services.map_service import MapServiceError


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FACTOR_FILE = PROJECT_ROOT / "data" / "transport_emission_factors.csv"


class CarbonServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.factors = get_transport_factors(FACTOR_FILE)

    def test_sourced_factor_records_have_valid_modes_units_and_provenance(self) -> None:
        by_mode = {factor["mode_id"]: factor for factor in self.factors}
        self.assertEqual(set(by_mode), {"car", "bus", "train", "bicycle", "walking"})
        self.assertEqual(by_mode["car"]["kg_co2e_per_unit"], 0.16591)
        self.assertEqual(by_mode["car"]["unit"], "vehicle-km")
        self.assertEqual(by_mode["bus"]["kg_co2e_per_unit"], 0.10151)
        self.assertEqual(by_mode["train"]["kg_co2e_per_unit"], 0.03092)
        self.assertTrue(by_mode["train"]["source_url"].startswith("https://"))
        self.assertEqual(by_mode["bicycle"]["kg_co2e_per_unit"], 0)
        self.assertIn("not a lifecycle factor", by_mode["walking"]["source_note"])

    def test_calculations_respect_vehicle_and_passenger_kilometre_factors(self) -> None:
        car = calculate_carbon_footprint(
            self.factors, 20, 4, "car", "Ranchi", "Hundru Falls", "osrm", "OSRM road route."
        )
        bus = calculate_carbon_footprint(
            self.factors, 20, 4, "bus", "Ranchi", "Hundru Falls", "osrm", "OSRM road route."
        )

        self.assertEqual(car["total_kg_co2e"], 3.3182)
        self.assertAlmostEqual(car["per_person_kg_co2e"], 0.8296, places=3)
        self.assertEqual(bus["total_kg_co2e"], 8.1208)
        self.assertEqual(bus["per_person_kg_co2e"], 2.0302)
        self.assertEqual(len(car["comparisons"]), 5)

    def test_invalid_or_incomplete_factor_dataset_is_not_silently_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            broken_file = Path(temporary_directory) / "factors.csv"
            broken_file.write_text("mode_id,kg_co2e_per_unit\ncar,1\n", encoding="utf-8")
            with self.assertRaises(CarbonFactorDataError):
                get_transport_factors(broken_file)


class CarbonApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "test-session-secret",
                "DATABASE_PATH": str(Path(self.temporary_directory.name) / "test.sqlite3"),
            }
        )
        self.client = self.app.test_client()
        self.csrf_token = self._register_and_get_csrf()

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def _register_and_get_csrf(self) -> str:
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
        self.client.get("/workspace/carbon-footprint")
        with self.client.session_transaction() as browser_session:
            return browser_session["_csrf_token"]

    def _payload(self, **overrides):
        payload = {
            "csrf_token": self.csrf_token,
            "source": "Ranchi",
            "destination": "Hundru Falls",
            "mode": "car",
            "travellers": 4,
            "manual_distance_km": None,
            "source_coordinates": {"latitude": 23.3441, "longitude": 85.3096},
            "destination_coordinates": {"latitude": 23.45, "longitude": 85.6},
        }
        payload.update(overrides)
        return payload

    def test_osrm_road_distance_and_selected_mode_are_used(self) -> None:
        response_data = {"code": "Ok", "routes": [{"distance": 20000, "duration": 1200}]}
        with patch("routes.api.get_road_routes", return_value=response_data) as route:
            response = self.client.post(
                "/api/carbon-estimate",
                json=self._payload(mode="bus"),
            )

        self.assertEqual(response.status_code, 200)
        result = response.get_json()
        self.assertEqual(result["distance_km"], 20)
        self.assertEqual(result["distance_source"], "osrm")
        self.assertEqual(result["total_kg_co2e"], 8.1208)
        self.assertEqual(result["per_person_kg_co2e"], 2.0302)
        self.assertIn("bus and rail route lengths may differ", result["distance_note"])
        route.assert_called_once_with(
            23.3441,
            85.3096,
            23.45,
            85.6,
            self.app.config["OSRM_BASE_URL"],
            self.app.config["NOMINATIM_USER_AGENT"],
        )

    def test_manual_distance_is_used_when_osrm_is_unavailable(self) -> None:
        with patch(
            "routes.api.get_road_routes",
            side_effect=MapServiceError("provider unavailable"),
        ):
            response = self.client.post(
                "/api/carbon-estimate",
                json=self._payload(mode="bus", manual_distance_km=15, travellers=2),
            )

        self.assertEqual(response.status_code, 200)
        result = response.get_json()
        self.assertEqual(result["distance_source"], "manual")
        self.assertEqual(result["distance_km"], 15)
        self.assertEqual(result["total_kg_co2e"], 3.0453)
        self.assertIn("user-entered", result["distance_note"])

    def test_authentication_csrf_and_invalid_input_are_enforced(self) -> None:
        anonymous_client = self.app.test_client()
        unauthenticated = anonymous_client.post(
            "/api/carbon-estimate",
            json=self._payload(csrf_token=self.csrf_token),
        )
        self.assertEqual(unauthenticated.status_code, 401)

        bad_csrf = self.client.post(
            "/api/carbon-estimate",
            json=self._payload(csrf_token="invalid"),
        )
        self.assertEqual(bad_csrf.status_code, 400)
        invalid_distance = self.client.post(
            "/api/carbon-estimate",
            json=self._payload(manual_distance_km=0),
        )
        self.assertEqual(invalid_distance.status_code, 400)
        self.assertIn("distance", invalid_distance.get_json()["error"].lower())

    def test_carbon_workspace_exposes_sources_inputs_chart_and_report(self) -> None:
        response = self.client.get("/workspace/carbon-footprint")
        self.assertEqual(response.status_code, 200)
        for expected in (
            b'id="carbon-form"',
            b'id="carbon-source"',
            b'id="carbon-destination"',
            b'id="carbon-distance"',
            b'id="carbon-travellers"',
            b'id="carbon-comparison-chart"',
            b'id="carbon-report"',
            b"not India-specific",
            b"Factor workbook",
        ):
            self.assertIn(expected, response.data)


if __name__ == "__main__":
    unittest.main()
