from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from app import create_app
from services.crowd_service import (
    SAMPLE_DATA_LABEL,
    CrowdDataError,
    build_crowd_dashboard,
)
from services.destination_service import get_destinations


class CrowdPredictionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp_directory.name)
        self.app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "test-session-secret",
                "DATABASE_PATH": str(self.directory / "test.sqlite3"),
                "TRAVEL_COMPANION_LLM_API_KEY": "",
            }
        )
        self.client = self.app.test_client()
        self.destinations = get_destinations(self.app.config["DESTINATIONS_PATH"])
        self.sample_path = Path(self.app.config["CROWD_HISTORY_PATH"])

    def tearDown(self) -> None:
        self.temp_directory.cleanup()

    def register_user(self) -> None:
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

    def test_sample_algorithm_uses_same_month_trend_and_labelled_levels(self) -> None:
        low = build_crowd_dashboard(
            self.sample_path,
            self.destinations,
            "mccluskieganj",
            6,
        )
        moderate = build_crowd_dashboard(
            self.sample_path,
            self.destinations,
            "hundru-falls",
            6,
        )
        high = build_crowd_dashboard(
            self.sample_path,
            self.destinations,
            "hundru-falls",
            11,
        )

        self.assertEqual((low["prediction_index"], low["level"]), (24, "Low"))
        self.assertEqual((moderate["prediction_index"], moderate["level"]), (44, "Moderate"))
        self.assertEqual((high["prediction_index"], high["level"]), (79, "High"))
        self.assertEqual(high["forecast_year"], 2026)
        self.assertEqual(high["data_label"], SAMPLE_DATA_LABEL)
        self.assertIn("not observed visitors", high["sample_notice"])
        self.assertEqual([item["year"] for item in high["yearly_averages"]], [2023, 2024, 2025])
        self.assertEqual(len(high["suggested_periods"]), 3)
        self.assertEqual(
            [item["index"] for item in high["suggested_periods"]],
            sorted(item["index"] for item in high["suggested_periods"]),
        )
        self.assertTrue(
            any(item["id"] == "mccluskieganj" for item in high["alternatives"])
        )
        self.assertEqual(len(high["chart_data"]["datasets"]), 4)

    def test_workspace_shows_sample_warning_chart_and_methodology(self) -> None:
        self.register_user()
        response = self.client.get(
            "/workspace/crowd-prediction?destination_id=hundru-falls&month=11"
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Illustrative sample model", response.data)
        self.assertIn(b"not live crowd data", response.data)
        self.assertIn(b'id="crowd-history-chart"', response.data)
        self.assertIn(b"Prediction methodology and limitations", response.data)
        self.assertIn(b"synthetic monthly indices for 2023", response.data)
        self.assertIn(b"cdn.jsdelivr.net/npm/chart.js", response.data)

    def test_invalid_destination_month_and_unlabelled_sample_are_rejected(self) -> None:
        self.register_user()
        self.assertEqual(
            self.client.get("/workspace/crowd-prediction?month=13").status_code,
            400,
        )
        self.assertEqual(
            self.client.get("/workspace/crowd-prediction?month=unknown").status_code,
            400,
        )
        self.assertEqual(
            self.client.get(
                "/workspace/crowd-prediction?destination_id=not-a-destination"
            ).status_code,
            400,
        )

        with tempfile.TemporaryDirectory() as temporary_directory:
            invalid_path = Path(temporary_directory) / "crowd.csv"
            text = self.sample_path.read_text(encoding="utf-8")
            invalid_path.write_text(
                text.replace(SAMPLE_DATA_LABEL, "observed", 1),
                encoding="utf-8",
            )
            with self.assertRaises(CrowdDataError):
                build_crowd_dashboard(
                    invalid_path,
                    self.destinations,
                    "hundru-falls",
                    11,
                )


if __name__ == "__main__":
    unittest.main()
