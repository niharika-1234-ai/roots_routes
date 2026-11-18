from __future__ import annotations

import re
import sqlite3

from database import get_db

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def validate_identity(full_name: str, email: str) -> tuple[str, str, list[str]]:
    name = " ".join(full_name.split())
    normalized_email = email.strip().lower()
    errors = []

    if not name:
        errors.append("Enter your full name.")
    elif len(name) > 100:
        errors.append("Your name must be 100 characters or fewer.")

    if len(normalized_email) > 254 or not EMAIL_PATTERN.fullmatch(normalized_email):
        errors.append("Enter a valid email address.")

    return name, normalized_email, errors


def register_user(full_name: str, email: str) -> dict | None:
    connection = get_db()
    try:
        cursor = connection.execute(
            "INSERT INTO users (full_name, email) VALUES (?, ?)",
            (full_name, email),
        )
        connection.commit()
    except sqlite3.IntegrityError:
        connection.rollback()
        return None

    row = connection.execute(
        "SELECT id, full_name, email FROM users WHERE id = ?",
        (cursor.lastrowid,),
    ).fetchone()
    if row is None:
        raise sqlite3.DatabaseError("Registered user could not be loaded.")
    return dict(row)


def authenticate_user(full_name: str, email: str) -> dict | None:
    row = get_db().execute(
        "SELECT id, full_name, email FROM users WHERE email = ? AND full_name = ? COLLATE NOCASE",
        (email, full_name),
    ).fetchone()
    return dict(row) if row is not None else None
