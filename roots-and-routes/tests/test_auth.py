from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from html import escape

from app import create_app
from services.dashboard_service import NAV_ITEMS, rank_hidden_gems, summarize_destinations
from services.destination_service import get_destinations


class AuthenticationFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        database_path = Path(self.temp_directory.name) / "test.sqlite3"
        self.app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "test-session-secret",
                "DATABASE_PATH": str(database_path),
            }
        )
        self.client = self.app.test_client()

    def tearDown(self) -> None:
        self.temp_directory.cleanup()

    def csrf_token(self) -> str:
        with self.client.session_transaction() as browser_session:
            return browser_session["_csrf_token"]

    def test_registration_logout_login_and_dashboard_redirects(self) -> None:
        response = self.client.get("/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/login")

        response = self.client.get("/dashboard")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/login")

        response = self.client.get("/register")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Your Journey Begins Here.", response.data)
        registration = self.client.post(
            "/register",
            data={
                "csrf_token": self.csrf_token(),
                "full_name": "Asha Munda",
                "email": "ASHA@example.com",
            },
        )
        self.assertEqual(registration.status_code, 302)
        self.assertEqual(registration.headers["Location"], "/dashboard")
        self.assertEqual(self.client.get("/dashboard").status_code, 200)
        self.assertIn(b"Welcome back, Asha.", self.client.get("/dashboard").data)

        logout = self.client.post("/logout", data={"csrf_token": self.csrf_token()})
        self.assertEqual(logout.status_code, 302)
        self.assertEqual(logout.headers["Location"], "/login")
        self.assertEqual(self.client.get("/dashboard").headers["Location"], "/login")

        login_page = self.client.get("/login")
        self.assertEqual(login_page.status_code, 200)
        login = self.client.post(
            "/login",
            data={
                "csrf_token": self.csrf_token(),
                "full_name": "asha munda",
                "email": "asha@EXAMPLE.com",
            },
        )
        self.assertEqual(login.status_code, 302)
        self.assertEqual(login.headers["Location"], "/dashboard")
        self.assertEqual(self.client.get("/").headers["Location"], "/dashboard")

    def test_rejects_bad_identity_duplicate_email_and_missing_csrf(self) -> None:
        self.client.get("/register")
        invalid = self.client.post(
            "/register",
            data={
                "csrf_token": self.csrf_token(),
                "full_name": " ",
                "email": "not-an-email",
            },
        )
        self.assertEqual(invalid.status_code, 400)
        self.assertIn(b"Enter your full name.", invalid.data)

        self.client.get("/register")
        registration = self.client.post(
            "/register",
            data={
                "csrf_token": self.csrf_token(),
                "full_name": "Asha Munda",
                "email": "asha@example.com",
            },
        )
        self.assertEqual(registration.status_code, 302)
        self.client.get("/dashboard")
        self.client.post("/logout", data={"csrf_token": self.csrf_token()})

        self.client.get("/register")
        duplicate = self.client.post(
            "/register",
            data={
                "csrf_token": self.csrf_token(),
                "full_name": "Another Name",
                "email": "ASHA@example.com",
            },
        )
        self.assertEqual(duplicate.status_code, 409)
        self.assertIn(b"already exists", duplicate.data)

        missing_csrf = self.client.post(
            "/logout",
            data={},
        )
        self.assertEqual(missing_csrf.status_code, 400)

    def test_dashboard_and_each_sidebar_page_render_real_content(self) -> None:
        self.client.get("/register")
        self.client.post(
            "/register",
            data={
                "csrf_token": self.csrf_token(),
                "full_name": "Asha Munda",
                "email": "asha@example.com",
            },
        )

        dashboard = self.client.get("/dashboard")
        self.assertEqual(dashboard.status_code, 200)
        self.assertIn(b"Welcome back, Asha.", dashboard.data)
        self.assertIn(b"Recent itineraries", dashboard.data)
        self.assertIn(b"Sustainability overview", dashboard.data)
        self.assertEqual(dashboard.data.count(b'class="nav-group"'), 3)
        for item in NAV_ITEMS:
            if item["slug"] is not None:
                self.assertIn(
                    f'href="/workspace/{item["slug"]}"'.encode(),
                    dashboard.data,
                )
        self.assertNotIn(b'href="#"', dashboard.data)

        for item in NAV_ITEMS:
            if item["slug"] is None:
                continue
            with self.subTest(page=item["slug"]):
                response = self.client.get(f"/workspace/{item['slug']}")
                self.assertEqual(response.status_code, 200)
                self.assertIn(escape(item["label"]).encode(), response.data)
                self.assertIn(b'<details class="nav-group" open>', response.data)
                self.assertNotIn(b'href="#"', response.data)

        filtered = self.client.get("/workspace/explore-destinations?q=Hundru")
        self.assertEqual(filtered.status_code, 200)
        self.assertIn(b"Hundru Falls", filtered.data)
        self.assertNotIn(b"Betla National Park", filtered.data)
        api_search = self.client.get("/api/destinations?q=Ranchi")
        self.assertEqual(len(api_search.get_json()), 5)
        waterfall_filter = self.client.get("/api/destinations?category=Waterfall")
        self.assertEqual(len(waterfall_filter.get_json()), 3)
        self.assertEqual(self.client.get("/workspace/not-a-page").status_code, 404)

    def test_destination_catalogue_is_complete_sourced_and_unrated(self) -> None:
        destinations = get_destinations(self.app.config["DESTINATIONS_PATH"])
        self.assertEqual(
            {destination.name for destination in destinations},
            {
                "Hundru Falls",
                "Dassam Falls",
                "Jonha Falls",
                "Betla National Park",
                "Netarhat",
                "Patratu Valley",
                "Deoghar",
                "Parasnath Hills",
                "Tagore Hill",
                "McCluskieganj",
            },
        )
        self.assertTrue(all(destination.sustainability_score is None for destination in destinations))
        self.assertTrue(all(destination.image_source_url for destination in destinations))

        self.client.get("/register")
        self.client.post(
            "/register",
            data={
                "csrf_token": self.csrf_token(),
                "full_name": "Asha Munda",
                "email": "asha@example.com",
            },
        )
        response = self.client.get("/workspace/explore-destinations")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Not assessed", response.data)
        self.assertIn(b"CC BY 4.0", response.data)
        self.assertIn(b"Approximate settlement anchor for the valley area.", response.data)
        self.assertEqual(response.data.count(b'<img src="https://thumb.wikimedia.org/'), 10)
        self.assertIn(b"commons.wikimedia.org/wiki/File:", response.data)
        for label in (
            b"Natural value",
            b"Cultural value",
            b"Popularity",
            b"Accessibility",
            b"Sustainability",
            b"Coordinates",
        ):
            self.assertIn(label, response.data)

        filtered = self.client.get("/workspace/explore-destinations?category=Waterfall")
        self.assertEqual(filtered.status_code, 200)
        self.assertIn(b"Hundru Falls", filtered.data)
        self.assertIn(b"Dassam Falls", filtered.data)
        self.assertNotIn(b"Betla National Park", filtered.data)

    def test_hidden_gems_needs_complete_source_links_and_ranks_low_popularity(self) -> None:
        destinations = get_destinations(self.app.config["DESTINATIONS_PATH"])
        sources = {
            "natural_value_source": "https://example.org/natural",
            "cultural_value_source": "https://example.org/cultural",
            "popularity_source": "https://example.org/popularity",
            "accessibility_source": "https://example.org/accessibility",
            "sustainability_score_source": "https://example.org/sustainability",
        }
        stronger = replace(
            destinations[0],
            natural_value=80,
            cultural_value=80,
            popularity=20,
            accessibility=80,
            sustainability_score=80,
            **sources,
        )
        weaker = replace(
            destinations[1],
            natural_value=90,
            cultural_value=10,
            popularity=40,
            accessibility=90,
            sustainability_score=90,
            **sources,
        )
        over_threshold = replace(
            destinations[2],
            natural_value=100,
            cultural_value=100,
            popularity=41,
            accessibility=100,
            sustainability_score=100,
            **sources,
        )
        ranked = rank_hidden_gems([destinations[3], stronger, weaker, over_threshold])
        self.assertEqual([item["destination"].id for item in ranked], [stronger.id, weaker.id])
        self.assertEqual(ranked[0]["ranking_score"], 80)
        self.assertIsNone(summarize_destinations(destinations)["average_score"])

        self.client.get("/register")
        self.client.post(
            "/register",
            data={
                "csrf_token": self.csrf_token(),
                "full_name": "Asha Munda",
                "email": "asha@example.com",
            },
        )
        hidden_gems = self.client.get("/workspace/hidden-gems")
        self.assertEqual(hidden_gems.status_code, 200)
        self.assertIn(b"Beyond the Tourist Trail", hidden_gems.data)
        self.assertIn(b"No evidence-based candidates yet", hidden_gems.data)
        self.assertIn(b"Unranked catalogue places", hidden_gems.data)
        self.assertIn(b"Not ranked as a hidden gem", hidden_gems.data)
        self.assertIn(b"Demo Moonfern Falls", hidden_gems.data)
        self.assertIn(b"Fictional demo area", hidden_gems.data)
        self.assertIn(b"invented demo score", hidden_gems.data)

        searched_sample = self.client.get("/workspace/hidden-gems?q=Moonfern")
        self.assertIn(b"Demo Moonfern Falls", searched_sample.data)
        self.assertNotIn(b"Demo Cloudbreak Viewpoint", searched_sample.data)
        filtered_sample = self.client.get(
            "/workspace/hidden-gems?q=Demo&category=Waterfall"
        )
        self.assertIn(b"Demo Moonfern Falls", filtered_sample.data)
        self.assertNotIn(b"Demo Whispering Sal Grove", filtered_sample.data)


if __name__ == "__main__":
    unittest.main()
