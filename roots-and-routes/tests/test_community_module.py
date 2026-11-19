from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

from app import create_app


ADMIN_KEY = "community-admin-test-key-with-more-than-32-characters"


class CommunityModuleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "test-session-secret",
                "DATABASE_PATH": str(Path(self.temporary_directory.name) / "test.sqlite3"),
                "COMMUNITY_ADMIN_KEY": ADMIN_KEY,
            }
        )
        self.client = self.app.test_client()
        self._register()

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def _register(self) -> None:
        self.client.get("/register")
        self.client.post(
            "/register",
            data={
                "csrf_token": self._csrf_token(),
                "full_name": "Asha Munda",
                "email": "asha@example.com",
            },
        )
        self.client.get("/workspace/community-connect")

    def _csrf_token(self) -> str:
        with self.client.session_transaction() as browser_session:
            return browser_session["_csrf_token"]

    def _unlock_admin(self, key: str = ADMIN_KEY) -> None:
        self.client.get("/community/admin")
        self.client.post(
            "/community/admin/unlock",
            data={"csrf_token": self._csrf_token(), "admin_key": key},
        )

    def _provider_form(self, **overrides) -> dict[str, str]:
        today = date.today().isoformat()
        form = {
            "name": "Riverbend Handicraft Collective",
            "category": "artisan",
            "experience": "More than a decade of documented craft practice",
            "location": "Silli, Ranchi district",
            "description": "A locally hosted introduction to traditional craft techniques and material.",
            "listing_source_url": "https://example.org/collective",
            "verified_on": today,
            "contact_phone": "+91 98765 43210",
            "contact_email": "host@example.org",
            "contact_verified": "on",
            "contact_source_url": "https://example.org/contact",
            "contact_verified_on": today,
            "image_url": "https://example.org/craft.jpg",
            "image_source_url": "https://example.org/craft-photo",
            "image_attribution": "Community archive",
            "is_published": "on",
        }
        form.update(overrides)
        return form

    def _create_provider(self, **overrides) -> int:
        self._unlock_admin()
        self.client.get("/community/admin/providers/new")
        response = self.client.post(
            "/community/admin/providers/new",
            data={
                "csrf_token": self._csrf_token(),
                **self._provider_form(**overrides),
            },
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            from database import get_db

            row = get_db().execute(
                "SELECT id FROM community_providers WHERE name = ?",
                (overrides.get("name", "Riverbend Handicraft Collective"),),
            ).fetchone()
            return int(row["id"])

    def test_empty_directory_has_no_demo_data_and_offers_real_filters(self) -> None:
        response = self.client.get("/workspace/community-connect")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"No local experiences are listed", response.data)
        self.assertIn(b"No sample profiles are mixed into this directory", response.data)
        self.assertIn(b"Tour guides", response.data)
        self.assertIn(b"Traditional food experiences", response.data)
        self.assertIn(b"Admin section", response.data)
        self.assertIn(b"Browse cultural guides", response.data)
        self.assertIn(b"Explore places on the map", response.data)

    def test_admin_key_gate_requires_configured_secret_and_is_csrf_protected(self) -> None:
        bad_key_response = self.client.post(
            "/community/admin/unlock",
            data={"csrf_token": self._csrf_token(), "admin_key": "wrong"},
        )
        self.assertEqual(bad_key_response.status_code, 302)
        self.assertEqual(
            self.client.get("/community/admin").status_code,
            200,
        )
        with self.client.session_transaction() as browser_session:
            self.assertNotIn("community_admin", browser_session)

        missing_csrf = self.client.post(
            "/community/admin/unlock",
            data={"admin_key": ADMIN_KEY},
        )
        self.assertEqual(missing_csrf.status_code, 400)

        self._unlock_admin()
        with self.client.session_transaction() as browser_session:
            self.assertIs(browser_session["community_admin"], True)

    def test_admin_controls_are_disabled_without_a_configured_key(self) -> None:
        disabled_app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "separate-test-session-secret",
                "DATABASE_PATH": str(
                    Path(self.temporary_directory.name) / "no-admin-key.sqlite3"
                ),
                "COMMUNITY_ADMIN_KEY": "",
            }
        )
        client = disabled_app.test_client()
        client.get("/register")
        with client.session_transaction() as browser_session:
            csrf_token = browser_session["_csrf_token"]
        client.post(
            "/register",
            data={
                "csrf_token": csrf_token,
                "full_name": "Asha Munda",
                "email": "no-key@example.com",
            },
        )
        page = client.get("/community/admin")
        self.assertIn(b"Administration is disabled", page.data)
        self.assertNotIn(b'id="community-admin-key"', page.data)

        with client.session_transaction() as browser_session:
            csrf_token = browser_session["_csrf_token"]
        client.post(
            "/community/admin/unlock",
            data={"csrf_token": csrf_token, "admin_key": ADMIN_KEY},
        )
        with client.session_transaction() as browser_session:
            self.assertNotIn("community_admin", browser_session)

    def test_admin_can_publish_update_and_unpublish_sourced_profile(self) -> None:
        provider_id = self._create_provider()
        directory = self.client.get("/workspace/community-connect")
        self.assertEqual(directory.status_code, 200)
        self.assertIn(b"Riverbend Handicraft Collective", directory.data)
        self.assertIn(b"CONTACT VERIFIED", directory.data)
        self.assertIn(b"98765 43210", directory.data)
        self.assertIn(b"craft.jpg", directory.data)
        self.assertNotIn(b"No local experiences are listed", directory.data)
        filtered = self.client.get(
            "/workspace/community-connect?category=artisan&q=riverbend"
        )
        self.assertIn(b"Riverbend Handicraft Collective", filtered.data)
        excluded = self.client.get("/workspace/community-connect?category=guide")
        self.assertNotIn(b"Riverbend Handicraft Collective", excluded.data)

        edit_page = self.client.get(f"/community/admin/providers/{provider_id}/edit")
        self.assertEqual(edit_page.status_code, 200)
        updated = self.client.post(
            f"/community/admin/providers/{provider_id}/edit",
            data={
                "csrf_token": self._csrf_token(),
                **self._provider_form(name="Updated Riverbend Collective"),
            },
        )
        self.assertEqual(updated.status_code, 302)
        self.assertIn(
            b"Updated Riverbend Collective",
            self.client.get("/workspace/community-connect").data,
        )

        archived = self.client.post(
            f"/community/admin/providers/{provider_id}/archive",
            data={"csrf_token": self._csrf_token()},
        )
        self.assertEqual(archived.status_code, 302)
        directory_after_archive = self.client.get("/workspace/community-connect")
        self.assertNotIn(b"Updated Riverbend Collective", directory_after_archive.data)
        self.assertIn(b"No local experiences are listed", directory_after_archive.data)

    def test_public_cards_hide_unverified_contacts_and_unpublished_drafts(self) -> None:
        self._create_provider(
            name="Verified Listing Without Public Contact",
            contact_phone="",
            contact_email="",
            contact_verified="",
            contact_source_url="",
            contact_verified_on="",
        )
        self._create_provider(
            name="Private Draft Listing",
            is_published="",
            contact_phone="",
            contact_email="",
            contact_verified="",
            contact_source_url="",
            contact_verified_on="",
        )

        response = self.client.get("/workspace/community-connect")
        self.assertIn(b"Verified Listing Without Public Contact", response.data)
        self.assertIn(b"Contact details are not published because they have not been verified", response.data)
        self.assertNotIn(b"Private Draft Listing", response.data)
        self.assertNotIn(b"mailto:host@example.org", response.data)

    def test_enquiries_are_saved_only_for_published_providers_and_can_be_resolved(self) -> None:
        provider_id = self._create_provider()
        submitted = self.client.post(
            "/community/enquiries",
            data={
                "csrf_token": self._csrf_token(),
                "provider_id": str(provider_id),
                "message": "Could you share more about this workshop?",
            },
            follow_redirects=True,
        )
        self.assertEqual(submitted.status_code, 200)
        self.assertIn(b"No email is sent automatically", submitted.data)

        admin_page = self.client.get("/community/admin")
        self.assertIn(b"Could you share more about this workshop?", admin_page.data)
        self.assertIn(b"asha@example.com", admin_page.data)
        with self.app.app_context():
            from database import get_db

            enquiry = get_db().execute(
                "SELECT id, status FROM community_enquiries"
            ).fetchone()
            self.assertEqual(enquiry["status"], "new")
            enquiry_id = enquiry["id"]

        resolved = self.client.post(
            f"/community/admin/enquiries/{enquiry_id}/resolve",
            data={"csrf_token": self._csrf_token()},
        )
        self.assertEqual(resolved.status_code, 302)
        with self.app.app_context():
            from database import get_db

            enquiry = get_db().execute(
                "SELECT status, resolved_at FROM community_enquiries WHERE id = ?",
                (enquiry_id,),
            ).fetchone()
            self.assertEqual(enquiry["status"], "resolved")
            self.assertIsNotNone(enquiry["resolved_at"])

    def test_invalid_contact_and_unverified_listing_cannot_be_published(self) -> None:
        self._unlock_admin()
        self.client.get("/community/admin/providers/new")
        invalid = self.client.post(
            "/community/admin/providers/new",
            data={
                "csrf_token": self._csrf_token(),
                **self._provider_form(
                    contact_verified="",
                    contact_source_url="",
                    contact_verified_on="",
                ),
            },
        )
        self.assertEqual(invalid.status_code, 400)
        self.assertIn(b"Only enter contact details after verifying them", invalid.data)

        self.client.get("/community/admin/providers/new")
        missing_source = self.client.post(
            "/community/admin/providers/new",
            data={
                "csrf_token": self._csrf_token(),
                **self._provider_form(listing_source_url="", contact_phone="", contact_email=""),
            },
        )
        self.assertEqual(missing_source.status_code, 400)
        self.assertIn(b"source link is required before publishing", missing_source.data)


if __name__ == "__main__":
    unittest.main()
