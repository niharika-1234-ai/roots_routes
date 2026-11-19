from __future__ import annotations

import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify

from database import init_app as init_database
from routes import register_routes
from services.destination_service import DestinationDataError


PROJECT_ROOT = Path(__file__).resolve().parent
load_dotenv(PROJECT_ROOT / ".env")


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    emission_factors_path = Path(
        os.environ.get(
            "TRANSPORT_EMISSION_FACTORS_PATH",
            str(PROJECT_ROOT / "data" / "transport_emission_factors.csv"),
        )
    )
    if not emission_factors_path.is_absolute():
        emission_factors_path = PROJECT_ROOT / emission_factors_path
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SESSION_SECRET") or os.urandom(32),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("SESSION_COOKIE_SECURE", "0") == "1",
        DATABASE_PATH=os.environ.get(
            "DATABASE_PATH",
            str(Path(app.instance_path) / "roots_and_routes.sqlite3"),
        ),
        DESTINATIONS_PATH=PROJECT_ROOT / "data" / "destinations.csv",
        HIDDEN_GEM_SAMPLES_PATH=PROJECT_ROOT / "data" / "hidden_gems_sample.json",
        CULTURAL_DESTINATIONS_PATH=PROJECT_ROOT / "data" / "cultural_destinations.json",
        CULTURAL_EVENTS_PATH=PROJECT_ROOT / "data" / "cultural_events.csv",
        CROWD_HISTORY_PATH=PROJECT_ROOT / "data" / "crowd_history_sample.csv",
        TRANSPORT_EMISSION_FACTORS_PATH=emission_factors_path,
        COMMUNITY_ADMIN_KEY=os.environ.get("COMMUNITY_ADMIN_KEY", "").strip(),
        PUBLIC_BASE_URL=os.environ.get("PUBLIC_BASE_URL", "").strip().rstrip("/"),
        NOMINATIM_BASE_URL=os.environ.get(
            "NOMINATIM_BASE_URL",
            "https://nominatim.openstreetmap.org",
        ),
        NOMINATIM_USER_AGENT=os.environ.get(
            "NOMINATIM_USER_AGENT",
            "ROOTS-AND-ROUTES/1.0",
        ),
        OSRM_BASE_URL=os.environ.get(
            "OSRM_BASE_URL",
            "https://router.project-osrm.org",
        ),
        OVERPASS_URL=os.environ.get(
            "OVERPASS_URL",
            "https://overpass-api.de/api/interpreter",
        ),
        OPENWEATHER_API_KEY=os.environ.get("OPENWEATHER_API_KEY", "").strip(),
        TRAVEL_COMPANION_LLM_API_KEY=os.environ.get("OPENAI_API_KEY", "").strip(),
        TRAVEL_COMPANION_LLM_ENDPOINT=os.environ.get(
            "OPENAI_CHAT_COMPLETIONS_URL",
            "https://api.openai.com/v1/chat/completions",
        ),
        TRAVEL_COMPANION_LLM_MODEL=os.environ.get(
            "OPENAI_MODEL",
            "gpt-4o-mini",
        ),
    )
    if test_config is not None:
        app.config.update(test_config)

    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    init_database(app)
    register_routes(app)

    @app.errorhandler(DestinationDataError)
    def handle_destination_data_error(error: DestinationDataError):
        app.logger.exception("Destination catalogue could not be loaded: %s", error)
        return jsonify({"error": "Destination data is temporarily unavailable."}), 500

    if not app.debug and not app.testing:
        logging.basicConfig(level=logging.INFO)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "5000")),
        debug=os.environ.get("FLASK_DEBUG") == "1",
    )
