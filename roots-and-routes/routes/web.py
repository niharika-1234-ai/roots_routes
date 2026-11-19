from __future__ import annotations

import base64
import secrets
import sqlite3
from io import BytesIO
from datetime import date

import qrcode
from flask import Blueprint, abort, current_app, flash, make_response, redirect, render_template, request, send_file, session, url_for
from qrcode.image.svg import SvgPathImage

from database import get_db
from services.auth_service import authenticate_user, register_user, validate_identity
from services.dashboard_service import (
    NAV_ITEMS,
    WORKSPACE_PAGES,
    filter_destinations,
    rank_hidden_gems,
    summarize_destinations,
)
from services.destination_service import get_destinations
from services.hidden_gem_sample_service import (
    HiddenGemSampleDataError,
    get_hidden_gem_samples,
)
from services.cultural_explorer_service import (
    CulturalExplorerDataError,
    canonical_public_url,
    cultural_destination_url,
    get_cultural_destination,
    get_cultural_destinations,
)
from services.event_service import CULTURAL_EVENT_CATEGORIES
from services.crowd_service import (
    CROWD_MONTHS,
    CrowdDataError,
    build_crowd_dashboard,
)
from services.carbon_service import CarbonFactorDataError, get_transport_factors
from services.budget_service import get_budget_options
from services.community_service import (
    COMMUNITY_CATEGORIES,
    CommunityValidationError,
    archive_provider,
    get_admin_enquiries,
    get_admin_provider,
    get_admin_providers,
    get_public_providers,
    resolve_enquiry,
    save_provider,
    submit_enquiry,
)
from services.safety_service import EMERGENCY_CONTACTS, SAFETY_TIPS
from services.security import csrf_token, valid_csrf_token
from services.passport_service import (
    PassportValidationError,
    build_passport_destinations,
    get_active_passport_qr_code,
    get_passport,
    issue_passport_qr_code,
    record_passport_visit,
    verify_passport_qr_code,
)
from services.itinerary_service import (
    ItineraryStorageError,
    delete_saved_itinerary,
    get_saved_itineraries,
)

web = Blueprint("web", __name__)


@web.get("/")
def home():
    if _current_user() is not None:
        return redirect(url_for("web.dashboard"))
    return redirect(url_for("web.login"))


@web.get("/login")
@web.post("/login")
def login():
    if _current_user() is not None:
        return redirect(_authenticated_landing_url())

    if request.method == "POST":
        _require_csrf()
        name, email, errors = validate_identity(
            request.form.get("full_name", ""),
            request.form.get("email", ""),
        )
        if errors:
            for error in errors:
                flash(error, "error")
            return render_template("auth.html", mode="login", full_name=name, email=email), 400

        user = authenticate_user(name, email)
        if user is None:
            flash("Those details don't match an account. Check them or register.", "error")
            return render_template("auth.html", mode="login", full_name=name, email=email), 401

        pending_passport_scan = session.get("pending_passport_scan")
        session.clear()
        session["user_id"] = user["id"]
        if isinstance(pending_passport_scan, dict):
            session["pending_passport_scan"] = pending_passport_scan
        return redirect(_authenticated_landing_url())

    return render_template("auth.html", mode="login", full_name="", email="")


@web.get("/register")
@web.post("/register")
def register():
    if _current_user() is not None:
        return redirect(_authenticated_landing_url())

    if request.method == "POST":
        _require_csrf()
        name, email, errors = validate_identity(
            request.form.get("full_name", ""),
            request.form.get("email", ""),
        )
        if errors:
            for error in errors:
                flash(error, "error")
            return render_template("auth.html", mode="register", full_name=name, email=email), 400

        try:
            user = register_user(name, email)
        except sqlite3.Error:
            current_app.logger.exception("Could not register user.")
            flash("We couldn't complete registration right now. Please try again.", "error")
            return render_template("auth.html", mode="register", full_name=name, email=email), 500
        if user is None:
            flash("An account with that email already exists. Please sign in instead.", "error")
            return render_template("auth.html", mode="register", full_name=name, email=email), 409

        pending_passport_scan = session.get("pending_passport_scan")
        session.clear()
        session["user_id"] = user["id"]
        if isinstance(pending_passport_scan, dict):
            session["pending_passport_scan"] = pending_passport_scan
        flash("Your account is ready. Welcome to ROOTS & ROUTES.", "success")
        return redirect(_authenticated_landing_url())

    return render_template("auth.html", mode="register", full_name="", email="")


@web.get("/dashboard")
def dashboard():
    user = _current_user()
    if user is None:
        return redirect(url_for("web.login"))
    destinations = get_destinations(current_app.config["DESTINATIONS_PATH"])
    recent_itineraries = _load_saved_itineraries(user["id"], destinations)[:3]
    return render_template(
        "index.html",
        user=user,
        sidebar_items=NAV_ITEMS,
        active_page="dashboard",
        recent_itineraries=recent_itineraries,
        **summarize_destinations(destinations),
    )


@web.get("/culture")
def cultural_index():
    return render_template(
        "cultural_index.html",
        user=_current_user(),
        cultural_destinations=_load_cultural_destinations(),
    )


@web.get("/culture/<slug>")
def cultural_destination(slug: str):
    try:
        destination = get_cultural_destination(
            current_app.config["CULTURAL_DESTINATIONS_PATH"],
            slug,
        )
    except CulturalExplorerDataError as error:
        current_app.logger.exception("Cultural guide data could not be loaded: %s", error)
        abort(500, description="Cultural guide data is temporarily unavailable.")
    if destination is None:
        abort(404)
    return render_template(
        "cultural_destination.html",
        user=None,
        destination=destination,
    )


@web.get("/workspace/<slug>")
def workspace(slug: str):
    user = _current_user()
    if user is None:
        return redirect(url_for("web.login"))
    page = WORKSPACE_PAGES.get(slug)
    if page is None:
        abort(404)
    page = {
        **page,
        "label": next(item["label"] for item in NAV_ITEMS if item["slug"] == slug),
    }

    destinations = get_destinations(current_app.config["DESTINATIONS_PATH"])
    query = request.args.get("q", "")[:120]
    category = request.args.get("category", "")[:80]
    ranked_gems = []
    hidden_gem_catalogue = []
    sample_hidden_gems = []
    hidden_gem_categories = set()
    crowd_dashboard = None
    carbon_factors = []
    community_providers = []
    budget_options = {}
    planner_initial = {}
    cultural_destinations = []
    passport_data = {}
    passport_destinations = []
    pending_passport_visit = None
    saved_itineraries = []
    if page["mode"] == "destinations":
        visible_destinations = filter_destinations(destinations, query, category or None)
    elif page["mode"] == "hidden_gems":
        matching_destinations = filter_destinations(destinations, query, category or None)
        ranked_gems = rank_hidden_gems(matching_destinations)
        try:
            all_sample_hidden_gems = get_hidden_gem_samples(
                current_app.config["HIDDEN_GEM_SAMPLES_PATH"]
            )
            sample_hidden_gems = get_hidden_gem_samples(
                current_app.config["HIDDEN_GEM_SAMPLES_PATH"],
                query,
                category,
            )
            hidden_gem_categories = {
                sample["category"] for sample in all_sample_hidden_gems
            }
        except HiddenGemSampleDataError:
            current_app.logger.exception("Hidden-gem sample data could not be loaded.")
            abort(500, description="Hidden-gem sample data is unavailable or invalid.")
        ranked_destination_ids = {
            item["destination"].id for item in ranked_gems
        }
        hidden_gem_catalogue = [
            destination
            for destination in matching_destinations
            if destination.id not in ranked_destination_ids
        ]
        visible_destinations = [
            item["destination"] for item in ranked_gems
        ]
    elif page["mode"] == "culture":
        visible_destinations = []
        cultural_destinations = _load_cultural_destinations()
    elif page["mode"] == "passport":
        visible_destinations = []
        passport_destinations = _passport_destination_registry(destinations)
        hidden_gem_ids = {
            item["destination"].id for item in rank_hidden_gems(destinations)
        }
        passport_data = get_passport(
            get_db(),
            user["id"],
            passport_destinations,
            hidden_gem_ids,
        )
        pending_passport_visit = _pending_passport_visit(passport_destinations)
    elif page["mode"] == "itineraries":
        visible_destinations = []
        saved_itineraries = _load_saved_itineraries(user["id"], destinations)
    elif page["mode"] == "intelligence":
        visible_destinations = destinations
        budget_options = get_budget_options()
    elif page["mode"] == "crowd":
        visible_destinations = destinations
        selected_destination_id = request.args.get(
            "destination_id",
            destinations[0].id if destinations else "",
        )
        month_parameter = request.args.get("month")
        if month_parameter is None:
            selected_month = date.today().month
        else:
            try:
                selected_month = int(month_parameter)
            except ValueError:
                abort(400, description="Choose a valid calendar month.")
        if not 1 <= selected_month <= len(CROWD_MONTHS):
            abort(400, description="Choose a valid calendar month.")
        try:
            crowd_dashboard = build_crowd_dashboard(
                current_app.config["CROWD_HISTORY_PATH"],
                destinations,
                selected_destination_id,
                selected_month,
            )
        except ValueError:
            abort(400, description="Choose a destination from the catalogue.")
        except CrowdDataError as error:
            current_app.logger.exception("Crowd sample data could not be loaded: %s", error)
            abort(500, description="Crowd sample data is unavailable or invalid.")
    elif page["mode"] == "carbon":
        visible_destinations = destinations
        try:
            carbon_factors = get_transport_factors(
                current_app.config["TRANSPORT_EMISSION_FACTORS_PATH"]
            )
        except CarbonFactorDataError as error:
            current_app.logger.exception("Carbon factor data could not be loaded: %s", error)
            abort(500, description="Transport emissions factor data is unavailable or invalid.")
    elif page["mode"] == "budget":
        visible_destinations = destinations
        budget_options = get_budget_options()
    elif page["mode"] == "planner":
        visible_destinations = destinations
        budget_options = get_budget_options()
        planner_initial = {
            "budget_inr": 30000,
            "days": 3,
            "travellers": 2,
            "travel_mode": "bus",
            "accommodation_preference": "budget",
            "food_preference": "budget",
            "destination_ids": [],
            "expense_overrides": {},
        }
    elif page["mode"] == "community":
        visible_destinations = destinations
        try:
            community_providers = get_public_providers(category, query)
        except CommunityValidationError as error:
            abort(400, description=str(error))
        except sqlite3.Error:
            current_app.logger.exception("Community provider listings could not be loaded.")
            abort(500, description="Community listings are temporarily unavailable.")
    elif page["mode"] in {"map", "sustainability", "weather"}:
        visible_destinations = destinations
    else:
        visible_destinations = []

    return render_template(
        "workspace.html",
        user=user,
        sidebar_items=NAV_ITEMS,
        active_page=slug,
        page=page,
        query=query,
        category=category,
        categories=sorted(
            {destination.category for destination in destinations}
            | hidden_gem_categories
        ),
        event_categories=CULTURAL_EVENT_CATEGORIES.items(),
        destinations=visible_destinations,
        ranked_gems=ranked_gems,
        hidden_gem_catalogue=hidden_gem_catalogue,
        sample_hidden_gems=sample_hidden_gems,
        crowd_dashboard=crowd_dashboard,
        crowd_months=CROWD_MONTHS,
        carbon_factors=carbon_factors,
        budget_options=budget_options,
        planner_initial=planner_initial,
        community_providers=community_providers,
        cultural_destinations=cultural_destinations,
        passport_data=passport_data,
        passport_destinations=passport_destinations,
        pending_passport_visit=pending_passport_visit,
        saved_itineraries=saved_itineraries,
        today=date.today().isoformat(),
        intelligence_route_origin_id=next(
            (item.id for item in destinations if item.id == "tagore-hill"),
            destinations[0].id if destinations else "",
        ),
        community_categories=COMMUNITY_CATEGORIES.items(),
        safety_contacts=EMERGENCY_CONTACTS,
        safety_tips=SAFETY_TIPS,
        is_community_admin=session.get("community_admin") is True,
        companion_context=_companion_context_for_template(
            session.get("travel_companion_context")
        ),
        companion_llm_configured=bool(
            current_app.config["TRAVEL_COMPANION_LLM_API_KEY"]
        ),
        **summarize_destinations(destinations),
    )


@web.post("/passport/visits")
def passport_visit_create():
    user = _current_user()
    if user is None:
        return redirect(url_for("web.login"))
    _require_csrf()
    destinations = _passport_destination_registry(
        get_destinations(current_app.config["DESTINATIONS_PATH"])
    )
    destination_id = request.form.get("destination_id", "")
    destination = next(
        (item for item in destinations if item["id"] == destination_id),
        None,
    )
    if destination is None:
        abort(400, description="Choose a destination from the travel passport catalogue.")

    try:
        result = record_passport_visit(
            get_db(),
            user["id"],
            destination,
            request.form.get("visited_on", ""),
            "self_reported",
        )
        get_db().commit()
    except PassportValidationError as error:
        flash(str(error), "error")
    except sqlite3.IntegrityError:
        get_db().rollback()
        flash("That visit is already recorded for the selected date.", "error")
    except sqlite3.Error:
        get_db().rollback()
        current_app.logger.exception("Could not save travel passport visit for user %s.", user["id"])
        flash("Your visit could not be saved right now. Please try again.", "error")
    else:
        flash(
            "Visit recorded as self-reported."
            if result == "created"
            else "Visit already recorded for that date.",
            "success" if result == "created" else "error",
        )
    return redirect(url_for("web.workspace", slug="travel-passport"))


@web.post("/passport/confirm-qr")
def passport_visit_confirm_qr():
    user = _current_user()
    if user is None:
        return redirect(url_for("web.login"))
    _require_csrf()
    destinations = _passport_destination_registry(
        get_destinations(current_app.config["DESTINATIONS_PATH"])
    )
    pending = _pending_passport_visit(destinations)
    if pending is None:
        return redirect(url_for("web.workspace", slug="travel-passport"))
    try:
        result = record_passport_visit(
            get_db(),
            user["id"],
            pending["destination"],
            date.today().isoformat(),
            "verified_qr",
            pending["code_id"],
        )
        get_db().commit()
    except PassportValidationError as error:
        flash(str(error), "error")
    except sqlite3.IntegrityError:
        get_db().rollback()
        flash("That destination visit is already recorded for today.", "error")
    except sqlite3.Error:
        get_db().rollback()
        current_app.logger.exception("Could not save verified passport visit for user %s.", user["id"])
        flash("The QR visit could not be saved right now. Please try again.", "error")
    else:
        flash(
            (
                f"Verified QR visit recorded for {pending['destination']['name']}."
                if result == "created"
                else f"Today's visit to {pending['destination']['name']} is now marked QR-verified."
            )
            if result != "already_recorded"
            else "That destination visit is already recorded for today.",
            "success" if result != "already_recorded" else "error",
        )
        session.pop("pending_passport_scan", None)
    return redirect(url_for("web.workspace", slug="travel-passport"))


@web.get("/passport/scan/<code_id>/<token>")
def passport_scan(code_id: str, token: str):
    claim = verify_passport_qr_code(get_db(), code_id, token)
    if claim is None:
        abort(410, description="This destination QR has expired or is not valid. Request a fresh code.")
    destinations = _passport_destination_registry(
        get_destinations(current_app.config["DESTINATIONS_PATH"])
    )
    if not any(item["id"] == claim["destination_id"] for item in destinations):
        abort(410, description="This destination is no longer available for passport check-ins.")
    session["pending_passport_scan"] = {"code_id": code_id}
    if _current_user() is None:
        flash("Sign in or create an account, then confirm the QR visit in your passport.", "success")
        return redirect(url_for("web.login"))
    flash("Destination QR validated. Confirm the visit in your passport to record it.", "success")
    return redirect(url_for("web.workspace", slug="travel-passport"))


@web.get("/passport/admin")
def passport_admin():
    user = _current_user()
    if user is None:
        return redirect(url_for("web.login"))
    destinations = _passport_destination_registry(
        get_destinations(current_app.config["DESTINATIONS_PATH"])
    )
    try:
        canonical_public_url("/passport/admin", current_app.config["PUBLIC_BASE_URL"])
        public_base_url_configured = True
    except ValueError:
        public_base_url_configured = False
    return render_template(
        "passport_admin.html",
        user=user,
        sidebar_items=NAV_ITEMS,
        active_page="travel-passport",
        destinations=destinations,
        is_admin=session.get("community_admin") is True,
        admin_key_configured=len(current_app.config["COMMUNITY_ADMIN_KEY"]) >= 32,
        public_base_url_configured=public_base_url_configured,
        qr_svg_data=None,
        qr_expires_at=None,
        qr_destination=None,
    )


@web.post("/passport/admin/unlock")
def passport_admin_unlock():
    if _current_user() is None:
        return redirect(url_for("web.login"))
    return _unlock_shared_admin("web.passport_admin", "passport")


@web.post("/passport/admin/qr")
def passport_admin_qr_create():
    user = _current_user()
    if user is None:
        return redirect(url_for("web.login"))
    if session.get("community_admin") is not True:
        return redirect(url_for("web.passport_admin"))
    _require_csrf()

    destinations = _passport_destination_registry(
        get_destinations(current_app.config["DESTINATIONS_PATH"])
    )
    destination_id = request.form.get("destination_id", "")
    destination = next(
        (item for item in destinations if item["id"] == destination_id),
        None,
    )
    if destination is None:
        abort(400, description="Choose a destination from the travel passport catalogue.")
    try:
        canonical_public_url("/passport/admin", current_app.config["PUBLIC_BASE_URL"])
    except ValueError:
        flash("Configure a canonical public HTTPS PUBLIC_BASE_URL before issuing passport QR codes.", "error")
        return redirect(url_for("web.passport_admin"))

    try:
        issued_code = issue_passport_qr_code(
            get_db(),
            user["id"],
            destination,
        )
        qr_path = url_for(
            "web.passport_scan",
            code_id=issued_code["id"],
            token=issued_code["token"],
        )
        qr_url = canonical_public_url(
            qr_path,
            current_app.config["PUBLIC_BASE_URL"],
        )
        qr_svg_data = base64.b64encode(_qr_svg_bytes(qr_url)).decode("ascii")
        get_db().commit()
    except sqlite3.Error:
        get_db().rollback()
        current_app.logger.exception("Could not issue passport QR code for user %s.", user["id"])
        flash("The passport QR code could not be issued right now.", "error")
        return redirect(url_for("web.passport_admin"))

    response = make_response(
        render_template(
            "passport_admin.html",
            user=user,
            sidebar_items=NAV_ITEMS,
            active_page="travel-passport",
            destinations=destinations,
            is_admin=True,
            admin_key_configured=True,
            public_base_url_configured=True,
            qr_svg_data=qr_svg_data,
            qr_expires_at=issued_code["expires_at"],
            qr_destination=destination,
        )
    )
    response.headers["Cache-Control"] = "no-store, private"
    response.headers["Pragma"] = "no-cache"
    return response


@web.post("/community/enquiries")
def community_enquiry():
    user = _current_user()
    if user is None:
        return redirect(url_for("web.login"))
    _require_csrf()
    try:
        provider_id = int(request.form.get("provider_id", ""))
    except (TypeError, ValueError):
        abort(400, description="Choose a valid community provider.")
    message = request.form.get("message", "")
    try:
        submitted = submit_enquiry(provider_id, user["id"], message)
    except CommunityValidationError as error:
        flash(str(error), "error")
        return redirect(url_for("web.workspace", slug="community-connect"))
    except sqlite3.Error:
        current_app.logger.exception("Could not save a community enquiry.")
        flash("Your enquiry could not be saved right now. Please try again.", "error")
        return redirect(url_for("web.workspace", slug="community-connect"))
    if not submitted:
        flash("That provider is no longer accepting enquiries.", "error")
    else:
        flash(
            "Your enquiry was added to the community inbox. No email is sent automatically; "
            "your account email is not verified.",
            "success",
        )
    return redirect(url_for("web.workspace", slug="community-connect"))


@web.get("/community/admin")
def community_admin():
    user = _current_user()
    if user is None:
        return redirect(url_for("web.login"))
    is_admin = session.get("community_admin") is True
    providers = []
    enquiries = []
    if is_admin:
        try:
            providers = get_admin_providers()
            enquiries = get_admin_enquiries()
        except sqlite3.Error:
            current_app.logger.exception("Community administration data could not be loaded.")
            abort(500, description="Community administration data is temporarily unavailable.")
    return render_template(
        "community_admin.html",
        user=user,
        sidebar_items=NAV_ITEMS,
        active_page="community-connect",
        page_title="Community administration",
        is_admin=is_admin,
        admin_key_configured=len(current_app.config["COMMUNITY_ADMIN_KEY"]) >= 32,
        providers=providers,
        enquiries=enquiries,
        category_labels=COMMUNITY_CATEGORIES,
    )


@web.post("/community/admin/unlock")
def community_admin_unlock():
    if _current_user() is None:
        return redirect(url_for("web.login"))
    return _unlock_shared_admin("web.community_admin", "community")


@web.get("/cultural/admin")
def cultural_admin():
    user = _current_user()
    if user is None:
        return redirect(url_for("web.login"))
    try:
        destinations = get_cultural_destinations(
            current_app.config["CULTURAL_DESTINATIONS_PATH"]
        )
    except CulturalExplorerDataError as error:
        current_app.logger.exception("Cultural QR generator data could not be loaded: %s", error)
        abort(500, description="Cultural QR generator data is temporarily unavailable.")
    try:
        cultural_destination_url(
            destinations[0]["slug"],
            current_app.config["PUBLIC_BASE_URL"],
        )
        public_base_url_configured = True
    except (ValueError, IndexError):
        public_base_url_configured = False
    return render_template(
        "cultural_admin.html",
        user=user,
        sidebar_items=NAV_ITEMS,
        active_page="cultural-explorer",
        destinations=destinations,
        is_admin=session.get("community_admin") is True,
        admin_key_configured=len(current_app.config["COMMUNITY_ADMIN_KEY"]) >= 32,
        public_base_url_configured=public_base_url_configured,
    )


@web.post("/cultural/admin/unlock")
def cultural_admin_unlock():
    if _current_user() is None:
        return redirect(url_for("web.login"))
    return _unlock_shared_admin("web.cultural_admin", "cultural")


@web.get("/cultural/admin/qr/<slug>.svg")
def cultural_admin_qr(slug: str):
    if _current_user() is None:
        return redirect(url_for("web.login"))
    if session.get("community_admin") is not True:
        return redirect(url_for("web.cultural_admin"))
    try:
        destination = get_cultural_destination(
            current_app.config["CULTURAL_DESTINATIONS_PATH"],
            slug,
        )
    except CulturalExplorerDataError as error:
        current_app.logger.exception("Cultural QR data could not be loaded: %s", error)
        abort(500, description="Cultural QR data is temporarily unavailable.")
    if destination is None:
        abort(404)
    try:
        target_url = cultural_destination_url(slug, current_app.config["PUBLIC_BASE_URL"])
    except ValueError as error:
        current_app.logger.error("Cultural QR codes cannot be generated: %s", error)
        abort(503, description="Configure a canonical HTTPS PUBLIC_BASE_URL before generating QR codes.")

    output = BytesIO(_qr_svg_bytes(target_url))
    output.seek(0)
    response = send_file(
        output,
        mimetype="image/svg+xml",
        as_attachment=request.args.get("download") == "1",
        download_name=f"{slug}-cultural-guide.svg",
        max_age=0,
    )
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@web.get("/community/admin/providers/new")
@web.post("/community/admin/providers/new")
def community_provider_new():
    user = _current_user()
    if user is None:
        return redirect(url_for("web.login"))
    if session.get("community_admin") is not True:
        return redirect(url_for("web.community_admin"))
    provider_form = _empty_provider_form()
    if request.method == "POST":
        _require_csrf()
        provider_form = request.form.to_dict()
        try:
            save_provider(provider_form, None, user["id"])
        except CommunityValidationError as error:
            flash(str(error), "error")
            return _render_community_provider_form(
                user,
                provider_form,
                None,
                "Add community listing",
                400,
            )
        except sqlite3.Error:
            current_app.logger.exception("Could not create a community provider listing.")
            flash("The listing could not be saved right now. Please try again.", "error")
            return _render_community_provider_form(
                user,
                provider_form,
                None,
                "Add community listing",
                500,
            )
        flash("Community listing saved.", "success")
        return redirect(url_for("web.community_admin"))
    return _render_community_provider_form(
        user,
        provider_form,
        None,
        "Add community listing",
    )


@web.get("/community/admin/providers/<int:provider_id>/edit")
@web.post("/community/admin/providers/<int:provider_id>/edit")
def community_provider_edit(provider_id: int):
    user = _current_user()
    if user is None:
        return redirect(url_for("web.login"))
    if session.get("community_admin") is not True:
        return redirect(url_for("web.community_admin"))
    try:
        provider = get_admin_provider(provider_id)
    except sqlite3.Error:
        current_app.logger.exception("Could not load community listing %s.", provider_id)
        abort(500, description="Community listing data is temporarily unavailable.")
    if provider is None:
        abort(404)
    provider_form = _provider_form_values(provider)
    if request.method == "POST":
        _require_csrf()
        provider_form = request.form.to_dict()
        try:
            save_provider(provider_form, provider_id, user["id"])
        except CommunityValidationError as error:
            flash(str(error), "error")
            return _render_community_provider_form(
                user,
                provider_form,
                provider_id,
                f"Edit {provider['name']}",
                400,
            )
        except LookupError:
            abort(404)
        except sqlite3.Error:
            current_app.logger.exception("Could not update community listing %s.", provider_id)
            flash("The listing could not be updated right now. Please try again.", "error")
            return _render_community_provider_form(
                user,
                provider_form,
                provider_id,
                f"Edit {provider['name']}",
                500,
            )
        flash("Community listing updated.", "success")
        return redirect(url_for("web.community_admin"))
    return _render_community_provider_form(
        user,
        provider_form,
        provider_id,
        f"Edit {provider['name']}",
    )


@web.post("/community/admin/providers/<int:provider_id>/archive")
def community_provider_archive(provider_id: int):
    user = _current_user()
    if user is None:
        return redirect(url_for("web.login"))
    if session.get("community_admin") is not True:
        return redirect(url_for("web.community_admin"))
    _require_csrf()
    try:
        archived = archive_provider(provider_id, user["id"])
    except sqlite3.Error:
        current_app.logger.exception("Could not unpublish community listing %s.", provider_id)
        flash("The listing could not be unpublished right now.", "error")
        return redirect(url_for("web.community_admin"))
    flash(
        "Listing unpublished; enquiry history has been retained."
        if archived
        else "That listing no longer exists.",
        "success" if archived else "error",
    )
    return redirect(url_for("web.community_admin"))


@web.post("/community/admin/enquiries/<int:enquiry_id>/resolve")
def community_enquiry_resolve(enquiry_id: int):
    if _current_user() is None:
        return redirect(url_for("web.login"))
    if session.get("community_admin") is not True:
        return redirect(url_for("web.community_admin"))
    _require_csrf()
    try:
        resolved = resolve_enquiry(enquiry_id)
    except sqlite3.Error:
        current_app.logger.exception("Could not update community enquiry %s.", enquiry_id)
        flash("The enquiry could not be updated right now.", "error")
        return redirect(url_for("web.community_admin"))
    flash(
        "Enquiry marked resolved." if resolved else "That enquiry is no longer open.",
        "success" if resolved else "error",
    )
    return redirect(url_for("web.community_admin"))


@web.post("/logout")
def logout():
    _require_csrf()
    session.clear()
    flash("You have been signed out.", "success")
    return redirect(url_for("web.login"))


@web.post("/itineraries/<int:itinerary_id>/delete")
def saved_itinerary_delete(itinerary_id: int):
    user = _current_user()
    if user is None:
        return redirect(url_for("web.login"))
    _require_csrf()
    try:
        deleted = delete_saved_itinerary(get_db(), user["id"], itinerary_id)
        get_db().commit()
    except sqlite3.Error:
        get_db().rollback()
        current_app.logger.exception(
            "Could not delete saved itinerary %s for user %s.",
            itinerary_id,
            user["id"],
        )
        flash("The itinerary could not be deleted right now.", "error")
    else:
        flash(
            "Saved itinerary deleted." if deleted else "That saved itinerary was not found.",
            "success" if deleted else "error",
        )
    return redirect(url_for("web.workspace", slug="my-itineraries"))


@web.context_processor
def inject_auth_helpers():
    return {"csrf_token": csrf_token}


def _load_cultural_destinations() -> list[dict]:
    try:
        return get_cultural_destinations(
            current_app.config["CULTURAL_DESTINATIONS_PATH"]
        )
    except CulturalExplorerDataError as error:
        current_app.logger.exception("Cultural guide data could not be loaded: %s", error)
        abort(500, description="Cultural guide data is temporarily unavailable.")


def _passport_destination_registry(destinations=None) -> list[dict]:
    catalogue = destinations or get_destinations(current_app.config["DESTINATIONS_PATH"])
    try:
        return build_passport_destinations(
            catalogue,
            _load_cultural_destinations(),
        )
    except PassportValidationError as error:
        current_app.logger.exception("Passport destination records are invalid: %s", error)
        abort(500, description="Passport destinations are temporarily unavailable.")


def _load_saved_itineraries(user_id: int, destinations) -> list[dict]:
    try:
        return get_saved_itineraries(
            get_db(),
            user_id,
            {destination.id: destination.name for destination in destinations},
        )
    except (sqlite3.Error, ItineraryStorageError):
        current_app.logger.exception("Saved itineraries could not be loaded for user %s.", user_id)
        abort(500, description="Saved itineraries are temporarily unavailable.")


def _pending_passport_visit(destinations: list[dict]) -> dict | None:
    pending = session.get("pending_passport_scan")
    if not isinstance(pending, dict):
        return None
    claim = get_active_passport_qr_code(get_db(), pending.get("code_id"))
    if claim is None:
        session.pop("pending_passport_scan", None)
        flash("The destination QR code expired before it could be confirmed. Scan a fresh code.", "error")
        return None
    destination = next(
        (item for item in destinations if item["id"] == claim["destination_id"]),
        None,
    )
    if destination is None:
        session.pop("pending_passport_scan", None)
        flash("This destination is no longer available for passport check-ins.", "error")
        return None
    return {
        "code_id": claim["id"],
        "destination": destination,
        "expires_at": claim["expires_at"],
    }


def _qr_svg_bytes(value: str) -> bytes:
    qr = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=8,
        border=4,
    )
    qr.add_data(value)
    qr.make(fit=True)
    image = qr.make_image(image_factory=SvgPathImage)
    output = BytesIO()
    image.save(output)
    return output.getvalue()


def _authenticated_landing_url() -> str:
    if isinstance(session.get("pending_passport_scan"), dict):
        return url_for("web.workspace", slug="travel-passport")
    return url_for("web.dashboard")


def _unlock_shared_admin(redirect_endpoint: str, admin_area: str):
    _require_csrf()
    configured_key = current_app.config["COMMUNITY_ADMIN_KEY"]
    if len(configured_key) < 32:
        flash(
            f"{admin_area.title()} administration is disabled. Configure a private key of at least 32 characters.",
            "error",
        )
        return redirect(url_for(redirect_endpoint))
    candidate = request.form.get("admin_key", "")
    if not secrets.compare_digest(configured_key, candidate):
        flash("The administration key was not accepted.", "error")
        return redirect(url_for(redirect_endpoint))
    session["community_admin"] = True
    flash(f"{admin_area.title()} administration unlocked for this session.", "success")
    return redirect(url_for(redirect_endpoint))


def _current_user() -> dict | None:
    user_id = session.get("user_id")
    if not isinstance(user_id, int):
        return None
    row = get_db().execute(
        "SELECT id, full_name, email FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()
    return dict(row) if row is not None else None


def _require_csrf() -> None:
    if not valid_csrf_token(request.form.get("csrf_token")):
        abort(400, description="The form expired. Reload the page and try again.")


def _companion_context_for_template(value: object) -> dict:
    if not isinstance(value, dict):
        return {
            "duration_days": None,
            "budget_inr": None,
            "destination_names": [],
            "interests": [],
        }
    return {
        "duration_days": value.get("duration_days"),
        "budget_inr": value.get("budget_inr"),
        "destination_names": value.get("destination_names", []),
        "interests": value.get("interests", []),
    }


def _empty_provider_form() -> dict[str, str]:
    return {
        "name": "",
        "category": "",
        "experience": "",
        "location": "",
        "description": "",
        "image_url": "",
        "image_source_url": "",
        "image_attribution": "",
        "listing_source_url": "",
        "verified_on": "",
        "contact_phone": "",
        "contact_email": "",
        "contact_verified": "",
        "contact_source_url": "",
        "contact_verified_on": "",
        "is_published": "",
    }


def _provider_form_values(provider: dict) -> dict[str, str]:
    values = _empty_provider_form()
    for field in values:
        if field in {"contact_verified", "is_published"}:
            values[field] = "on" if provider[field] else ""
        else:
            values[field] = provider[field] or ""
    return values


def _render_community_provider_form(
    user: dict,
    provider_form: dict[str, str],
    provider_id: int | None,
    form_title: str,
    status_code: int = 200,
):
    return (
        render_template(
            "community_provider_form.html",
            user=user,
            sidebar_items=NAV_ITEMS,
            active_page="community-connect",
            page_title="Community administration",
            form_title=form_title,
            provider_form=provider_form,
            provider_id=provider_id,
            community_categories=COMMUNITY_CATEGORIES.items(),
        ),
        status_code,
    )
