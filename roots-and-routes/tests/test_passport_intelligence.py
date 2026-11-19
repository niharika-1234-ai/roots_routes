from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from app import create_app
from database import get_db
from services.cultural_explorer_service import get_cultural_destinations
from services.destination_service import get_destinations
from services.passport_service import (
    build_passport_destinations,
    issue_passport_qr_code,
    verify_passport_qr_code,
)


class PassportModuleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        self.app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "passport-test-secret",
                "DATABASE_PATH": str(Path(self.temp_directory.name) / "passport.sqlite3"),
                "PUBLIC_BASE_URL": "https://roots.example",
                "COMMUNITY_ADMIN_KEY": "k" * 40,
            }
        )
        self.client = self.app.test_client()
        self.register(self.client, "Asha Munda", "asha@example.com")

    def tearDown(self) -> None:
        self.temp_directory.cleanup()

    @staticmethod
    def csrf_token(client) -> str:
        with client.session_transaction() as browser_session:
            return browser_session["_csrf_token"]

    @staticmethod
    def register(client, name: str, email: str) -> None:
        client.get("/register")
        with client.session_transaction() as browser_session:
            token = browser_session["_csrf_token"]
        response = client.post(
            "/register",
            data={"csrf_token": token, "full_name": name, "email": email},
        )
        if response.status_code != 302:
            raise AssertionError(f"Registration failed: {response.status_code}")
        client.get("/workspace/travel-passport")

    def passport_destinations(self) -> list[dict]:
        catalogue = get_destinations(self.app.config["DESTINATIONS_PATH"])
        cultural = get_cultural_destinations(
            self.app.config["CULTURAL_DESTINATIONS_PATH"]
        )
        return build_passport_destinations(catalogue, cultural)

    def test_self_reported_visits_are_per_user_and_rendered_as_stamps(self) -> None:
        destination = next(
            item for item in self.passport_destinations() if item["id"] == "hundru-falls"
        )
        response = self.client.post(
            "/passport/visits",
            data={
                "csrf_token": self.csrf_token(self.client),
                "destination_id": destination["id"],
                "visited_on": datetime.now().date().isoformat(),
            },
        )
        self.assertEqual(response.status_code, 302)

        passport = self.client.get("/workspace/travel-passport")
        self.assertEqual(passport.status_code, 200)
        self.assertIn(b"Hundru Falls", passport.data)
        self.assertIn(b"Self-reported visit", passport.data)
        self.assertIn(b"Waterfall Explorer", passport.data)

        second_client = self.app.test_client()
        self.register(second_client, "Biru Munda", "biru@example.com")
        second_passport = second_client.get("/workspace/travel-passport")
        self.assertEqual(second_passport.status_code, 200)
        self.assertIn(b"0</strong>", second_passport.data)
        self.assertNotIn(b"Visited today", second_passport.data)

    def test_qr_checkin_upgrades_same_day_self_report_and_token_is_hashed(self) -> None:
        destination = next(
            item for item in self.passport_destinations() if item["id"] == "parasnath-hills"
        )
        today = datetime.now().date().isoformat()
        self.client.post(
            "/passport/visits",
            data={
                "csrf_token": self.csrf_token(self.client),
                "destination_id": destination["id"],
                "visited_on": today,
            },
        )
        with self.client.session_transaction() as browser_session:
            user_id = browser_session["user_id"]
        with self.app.app_context():
            issued = issue_passport_qr_code(
                get_db(),
                user_id,
                destination,
            )
            get_db().commit()
            stored_hash = get_db().execute(
                "SELECT token_hash FROM passport_qr_codes WHERE id = ?",
                (issued["id"],),
            ).fetchone()["token_hash"]
        self.assertNotEqual(stored_hash, issued["token"])

        with self.client.session_transaction() as browser_session:
            browser_session["pending_passport_scan"] = {"code_id": issued["id"]}
        confirmation = self.client.post(
            "/passport/confirm-qr",
            data={"csrf_token": self.csrf_token(self.client)},
        )
        self.assertEqual(confirmation.status_code, 302)

        passport = self.client.get("/workspace/travel-passport")
        self.assertIn(b"QR-verified visit", passport.data)
        self.assertIn(b">0</strong>", passport.data)
        self.assertIn(b">1</strong>", passport.data)

    def test_qr_validation_rejects_wrong_and_expired_tokens(self) -> None:
        destination = self.passport_destinations()[0]
        with self.client.session_transaction() as browser_session:
            user_id = browser_session["user_id"]
        with self.app.app_context():
            now = datetime.now(timezone.utc)
            expired = issue_passport_qr_code(
                get_db(),
                user_id,
                destination,
                now=now - timedelta(minutes=16),
            )
            current = issue_passport_qr_code(
                get_db(),
                user_id,
                destination,
                now=now,
            )
            get_db().commit()
            self.assertIsNone(
                verify_passport_qr_code(
                    get_db(),
                    current["id"],
                    "x" * len(current["token"]),
                    now=now,
                )
            )
            self.assertIsNone(
                verify_passport_qr_code(
                    get_db(),
                    expired["id"],
                    expired["token"],
                    now=now,
                )
            )
            self.assertIsNotNone(
                verify_passport_qr_code(
                    get_db(),
                    current["id"],
                    current["token"],
                    now=now,
                )
            )

    def test_admin_qr_issuer_requires_key_csrf_and_canonical_public_url(self) -> None:
        response = self.client.get("/passport/admin")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Unlock passport QR administration", response.data)
        csrf = self.csrf_token(self.client)
        rejected = self.client.post(
            "/passport/admin/unlock",
            data={"csrf_token": csrf, "admin_key": "wrong"},
        )
        self.assertEqual(rejected.status_code, 302)

        accepted = self.client.post(
            "/passport/admin/unlock",
            data={
                "csrf_token": self.csrf_token(self.client),
                "admin_key": "k" * 40,
            },
        )
        self.assertEqual(accepted.status_code, 302)
        generated = self.client.post(
            "/passport/admin/qr",
            data={
                "csrf_token": self.csrf_token(self.client),
                "destination_id": "hundru-falls",
            },
        )
        self.assertEqual(generated.status_code, 200)
        self.assertIn("no-store", generated.headers["Cache-Control"])
        self.assertIn(b"Download QR SVG", generated.data)
        self.assertIn(b"Valid until", generated.data)

    def test_public_qr_scan_survives_registration_and_requires_confirmation(self) -> None:
        destination = next(
            item for item in self.passport_destinations() if item["id"] == "deoghar"
        )
        with self.client.session_transaction() as browser_session:
            issuer_id = browser_session["user_id"]
        with self.app.app_context():
            issued = issue_passport_qr_code(get_db(), issuer_id, destination)
            get_db().commit()

        visitor = self.app.test_client()
        scanned = visitor.get(
            f"/passport/scan/{issued['id']}/{issued['token']}"
        )
        self.assertEqual(scanned.status_code, 302)
        self.assertEqual(scanned.headers["Location"], "/login")
        with visitor.session_transaction() as browser_session:
            self.assertEqual(
                browser_session["pending_passport_scan"],
                {"code_id": issued["id"]},
            )

        visitor.get("/register")
        with visitor.session_transaction() as browser_session:
            csrf = browser_session["_csrf_token"]
        registration = visitor.post(
            "/register",
            data={
                "csrf_token": csrf,
                "full_name": "Biru Munda",
                "email": "biru@example.com",
            },
        )
        self.assertEqual(registration.status_code, 302)
        passport = visitor.get("/workspace/travel-passport")
        self.assertIn(b"Confirm your visit to Deoghar", passport.data)

        confirmed = visitor.post(
            "/passport/confirm-qr",
            data={"csrf_token": self.csrf_token(visitor)},
        )
        self.assertEqual(confirmed.status_code, 302)
        self.assertIn(b"QR-verified visit", visitor.get("/workspace/travel-passport").data)


class DestinationIntelligenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        self.app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "intelligence-test-secret",
                "DATABASE_PATH": str(Path(self.temp_directory.name) / "intelligence.sqlite3"),
            }
        )
        self.client = self.app.test_client()
        PassportModuleTests.register(self.client, "Asha Munda", "asha@example.com")

    def tearDown(self) -> None:
        self.temp_directory.cleanup()

    def test_destination_intelligence_page_and_core_api_are_grounded(self) -> None:
        page = self.client.get("/workspace/smart-trip-intelligence")
        self.assertEqual(page.status_code, 200)
        for expected in (
            b"Nearby attractions",
            b"Road routes",
            b"Weather",
            b"Safety information",
            b"not browser location",
            b"Budget estimate",
        ):
            self.assertIn(expected, page.data)

        result = self.client.get(
            "/api/destination-intelligence?destination_id=tagore-hill"
        )
        self.assertEqual(result.status_code, 200)
        payload = result.get_json()
        self.assertEqual(payload["destination"]["id"], "tagore-hill")
        self.assertIn("not observed", payload["crowd"]["sample_notice"])
        self.assertEqual(payload["sustainability"]["status"], "not_assessed")
        self.assertEqual(payload["hidden_alternatives"], [])

        invalid = self.client.get(
            "/api/destination-intelligence?destination_id=not-a-destination"
        )
        self.assertEqual(invalid.status_code, 400)
        unauthenticated = self.app.test_client().get(
            "/api/destination-intelligence?destination_id=tagore-hill"
        )
        self.assertEqual(unauthenticated.status_code, 401)

    def test_route_carbon_requires_csrf_and_uses_a_sourced_road_distance(self) -> None:
        payload = {
            "csrf_token": "",
            "origin_id": "tagore-hill",
            "destination_id": "hundru-falls",
            "travellers": 2,
            "mode": "car",
        }
        invalid_csrf = self.client.post(
            "/api/intelligence/route-carbon",
            json={**payload, "csrf_token": "wrong"},
        )
        self.assertEqual(invalid_csrf.status_code, 400)

        with self.client.session_transaction() as browser_session:
            csrf = browser_session["_csrf_token"]
        with patch(
            "routes.api.get_road_routes",
            return_value={
                "code": "Ok",
                "routes": [{"distance": 60000, "duration": 3600}],
            },
        ):
            response = self.client.post(
                "/api/intelligence/route-carbon",
                json={**payload, "csrf_token": csrf},
            )
        self.assertEqual(response.status_code, 200)
        result = response.get_json()
        self.assertEqual(result["provider"], "OSRM")
        self.assertEqual(result["routes"][0]["distance_km"], 60.0)
        self.assertIn("factor_basis_note", result["carbon"])


if __name__ == "__main__":
    unittest.main()
