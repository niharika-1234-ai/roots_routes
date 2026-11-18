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
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    full_name TEXT NOT NULL,
                    email TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
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
    finally:
        connection.close()


def init_app(app: Flask) -> None:
    app.teardown_appcontext(close_db)
    with app.app_context():
        init_db()
