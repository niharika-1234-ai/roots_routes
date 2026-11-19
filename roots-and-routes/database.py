from __future__ import annotations

import sqlite3
from pathlib import Path

from flask import Flask, current_app, g


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        database_path = Path(current_app.config["DATABASE_PATH"])
        database_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(database_path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        g.db = connection
    return g.db


def close_db(_error: BaseException | None = None) -> None:
    connection = g.pop("db", None)
    if connection is not None:
        connection.close()


def init_db() -> None:
    database_path = Path(current_app.config["DATABASE_PATH"])
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database_path, timeout=5)
    try:
        with connection:
            connection.executescript(
                """
                PRAGMA foreign_keys = ON;
                CREATE TABLE IF NOT EXISTS saved_trips (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    destination_ids TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                    itinerary_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    full_name TEXT NOT NULL,
                    email TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS passport_qr_codes (
                    id TEXT PRIMARY KEY,
                    destination_id TEXT NOT NULL,
                    destination_name TEXT NOT NULL,
                    token_hash TEXT NOT NULL UNIQUE,
                    issued_by_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    issued_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    revoked_at TEXT
                );
                CREATE TABLE IF NOT EXISTS passport_visits (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    destination_id TEXT NOT NULL,
                    destination_name TEXT NOT NULL,
                    district TEXT NOT NULL,
                    category TEXT NOT NULL,
                    visited_on TEXT NOT NULL,
                    verification_method TEXT NOT NULL CHECK (
                        verification_method IN ('self_reported', 'verified_qr')
                    ),
                    qr_code_id TEXT REFERENCES passport_qr_codes(id),
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (user_id, destination_id, visited_on),
                    CHECK (
                        (verification_method = 'verified_qr' AND qr_code_id IS NOT NULL)
                        OR (verification_method = 'self_reported' AND qr_code_id IS NULL)
                    )
                );
                CREATE INDEX IF NOT EXISTS passport_visits_user_date
                    ON passport_visits (user_id, visited_on DESC, created_at DESC);
                CREATE INDEX IF NOT EXISTS passport_visits_user_destination
                    ON passport_visits (user_id, destination_id);
                CREATE TABLE IF NOT EXISTS community_providers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    category TEXT NOT NULL CHECK (
                        category IN (
                            'guide',
                            'artisan',
                            'food_experience',
                            'tribal_art_workshop',
                            'village_tourism',
                            'cultural_activity'
                        )
                    ),
                    experience TEXT NOT NULL,
                    location TEXT NOT NULL,
                    description TEXT NOT NULL,
                    image_url TEXT NOT NULL DEFAULT '',
                    image_source_url TEXT NOT NULL DEFAULT '',
                    image_attribution TEXT NOT NULL DEFAULT '',
                    listing_source_url TEXT NOT NULL DEFAULT '',
                    verified_on TEXT NOT NULL DEFAULT '',
                    contact_phone TEXT NOT NULL DEFAULT '',
                    contact_email TEXT NOT NULL DEFAULT '',
                    contact_verified INTEGER NOT NULL DEFAULT 0 CHECK (
                        contact_verified IN (0, 1)
                    ),
                    contact_source_url TEXT NOT NULL DEFAULT '',
                    contact_verified_on TEXT NOT NULL DEFAULT '',
                    is_published INTEGER NOT NULL DEFAULT 0 CHECK (
                        is_published IN (0, 1)
                    ),
                    created_by_user_id INTEGER NOT NULL REFERENCES users(id),
                    updated_by_user_id INTEGER NOT NULL REFERENCES users(id),
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    CHECK (
                        is_published = 0
                        OR (listing_source_url <> '' AND verified_on <> '')
                    ),
                    CHECK (
                        contact_verified = 1
                        OR (contact_phone = '' AND contact_email = '')
                    ),
                    CHECK (
                        contact_verified = 0
                        OR (
                            contact_source_url <> ''
                            AND contact_verified_on <> ''
                            AND (contact_phone <> '' OR contact_email <> '')
                        )
                    ),
                    CHECK (
                        image_url = ''
                        OR (
                            image_source_url <> ''
                            AND image_attribution <> ''
                        )
                    )
                );
                CREATE TABLE IF NOT EXISTS community_enquiries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    provider_id INTEGER NOT NULL REFERENCES community_providers(id),
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    message TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'new' CHECK (
                        status IN ('new', 'resolved')
                    ),
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    resolved_at TEXT
                );
                CREATE INDEX IF NOT EXISTS community_providers_public_category
                    ON community_providers (is_published, category, name);
                CREATE INDEX IF NOT EXISTS community_enquiries_status_created
                    ON community_enquiries (status, created_at DESC);
                """
            )
            saved_trip_columns = {
                row[1]
                for row in connection.execute("PRAGMA table_info(saved_trips)")
            }
            if "user_id" not in saved_trip_columns:
                connection.execute(
                    "ALTER TABLE saved_trips ADD COLUMN user_id INTEGER REFERENCES users(id) ON DELETE CASCADE"
                )
            if "itinerary_json" not in saved_trip_columns:
                connection.execute(
                    "ALTER TABLE saved_trips ADD COLUMN itinerary_json TEXT NOT NULL DEFAULT '{}'"
                )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS saved_trips_user_created
                ON saved_trips (user_id, created_at DESC, id DESC)
                """
            )
    finally:
        connection.close()


def init_app(app: Flask) -> None:
    app.teardown_appcontext(close_db)
    with app.app_context():
        init_db()
