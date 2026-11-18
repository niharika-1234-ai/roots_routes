from __future__ import annotations

import secrets
import sqlite3
from datetime import date

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, session, url_for

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
from services.event_service import CULTURAL_EVENT_CATEGORIES
from services.crowd_service import (
    CROWD_MONTHS,
    CrowdDataError,
    build_crowd_dashboard,
)
from services.carbon_service import CarbonFactorDataError, get_transport_factors
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
        return redirect(url_for("web.dashboard"))

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

        session.clear()
        session["user_id"] = user["id"]
        return redirect(url_for("web.dashboard"))

    return render_template("auth.html", mode="login", full_name="", email="")


@web.get("/register")
@web.post("/register")
def register():
    if _current_user() is not None:
        return redirect(url_for("web.dashboard"))

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

        session.clear()
        session["user_id"] = user["id"]
        flash("Your account is ready. Welcome to ROOTS & ROUTES.", "success")
        return redirect(url_for("web.dashboard"))

    return render_template("auth.html", mode="register", full_name="", email="")


@web.get("/dashboard")
def dashboard():
    user = _current_user()
    if user is None:
        return redirect(url_for("web.login"))
    destinations = get_destinations(current_app.config["DESTINATIONS_PATH"])
    return render_template(
        "index.html",
        user=user,
        sidebar_items=NAV_ITEMS,
        active_page="dashboard",
        **summarize_destinations(destinations),
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
    crowd_dashboard = None
    carbon_factors = []
    community_providers = []
    if page["mode"] == "destinations":
        visible_destinations = filter_destinations(destinations, query, category or None)
    elif page["mode"] == "hidden_gems":
        matching_destinations = filter_destinations(destinations, query, category or None)
        ranked_gems = rank_hidden_gems(matching_destinations)
        visible_destinations = [
            item["destination"] for item in ranked_gems
        ]
    elif page["mode"] == "culture":
        visible_destinations = filter_destinations(destinations, query, "Culture")
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
    elif page["mode"] == "community":
        visible_destinations = destinations
        try:
            community_providers = get_public_providers(category, query)
        except CommunityValidationError as error:
            abort(400, description=str(error))
        except sqlite3.Error:
            current_app.logger.exception("Community provider listings could not be loaded.")
            abort(500, description="Community listings are temporarily unavailable.")
    elif page["mode"] in {"map", "sustainability"}:
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
        categories=sorted({destination.category for destination in destinations}),
        event_categories=CULTURAL_EVENT_CATEGORIES.items(),
        destinations=visible_destinations,
        ranked_gems=ranked_gems,
        crowd_dashboard=crowd_dashboard,
        crowd_months=CROWD_MONTHS,
        carbon_factors=carbon_factors,
        community_providers=community_providers,
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
    _require_csrf()
    configured_key = current_app.config["COMMUNITY_ADMIN_KEY"]
    if len(configured_key) < 32:
        flash("Community administration is disabled. Configure a private key of at least 32 characters.", "error")
        return redirect(url_for("web.community_admin"))
    candidate = request.form.get("admin_key", "")
    if not secrets.compare_digest(configured_key, candidate):
        flash("The administration key was not accepted.", "error")
        return redirect(url_for("web.community_admin"))
    session["community_admin"] = True
    flash("Community administration unlocked for this session.", "success")
    return redirect(url_for("web.community_admin"))


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


@web.context_processor
def inject_auth_helpers():
    return {"csrf_token": csrf_token}


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
