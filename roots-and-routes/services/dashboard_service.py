from __future__ import annotations

from typing import Any

from models.destination import Destination

LESSER_KNOWN_POPULARITY_MAX = 40

NAV_ITEMS = [
    {"label": "Dashboard", "slug": None, "group": "Overview", "icon": "DB"},
    {"label": "Explore Destinations", "slug": "explore-destinations", "group": "Discover", "icon": "EX"},
    {"label": "AI Travel Planner", "slug": "ai-travel-planner", "group": "Discover", "icon": "PL"},
    {"label": "AI Travel Companion", "slug": "ai-travel-companion", "group": "Discover", "icon": "CO"},
    {"label": "Interactive Maps", "slug": "interactive-maps", "group": "Discover", "icon": "MP"},
    {"label": "Hidden Gems", "slug": "hidden-gems", "group": "Discover", "icon": "HG"},
    {"label": "Crowd Prediction", "slug": "crowd-prediction", "group": "Discover", "icon": "CP"},
    {"label": "Community Connect", "slug": "community-connect", "group": "Plan & travel", "icon": "CC"},
    {"label": "Tourist Safety", "slug": "tourist-safety", "group": "Plan & travel", "icon": "TS"},
    {"label": "Weather Insights", "slug": "weather-insights", "group": "Plan & travel", "icon": "WI"},
    {"label": "Smart Budget", "slug": "smart-budget", "group": "Plan & travel", "icon": "SB"},
    {"label": "Cultural Explorer", "slug": "cultural-explorer", "group": "Plan & travel", "icon": "CE"},
    {"label": "Travel Passport", "slug": "travel-passport", "group": "Plan & travel", "icon": "TP"},
    {"label": "Smart Trip Intelligence", "slug": "smart-trip-intelligence", "group": "Plan & travel", "icon": "ST"},
    {"label": "Restaurants", "slug": "restaurants", "group": "Plan & travel", "icon": "RE"},
    {"label": "Hotels & Stays", "slug": "hotels-stays", "group": "Plan & travel", "icon": "HS"},
    {"label": "Cultural Events", "slug": "cultural-events", "group": "Plan & travel", "icon": "EV"},
    {"label": "My Itineraries", "slug": "my-itineraries", "group": "Your space", "icon": "IT"},
    {"label": "Sustainability Dashboard", "slug": "sustainability-dashboard", "group": "Your space", "icon": "SD"},
    {"label": "Profile", "slug": "profile", "group": "Your space", "icon": "PR"},
]

WORKSPACE_PAGES: dict[str, dict[str, Any]] = {
    "explore-destinations": {
        "mode": "destinations",
        "description": "Browse Jharkhand places with map coordinates and image credits linked to their sources.",
        "status": "Catalogue",
        "note": "Ratings are not supplied without evidence. Coordinates and images link to their source records; confirm current travel conditions before visiting.",
    },
    "ai-travel-planner": {
        "mode": "planner",
        "description": "Turn trip constraints and an editable budget estimate into a grounded Jharkhand itinerary draft.",
        "status": "Grounded itinerary draft",
        "note": "The itinerary is a starting point, not a confirmed route or booking. It does not verify opening hours, access, travel times, availability, or that the trip fits your budget.",
    },
    "ai-travel-companion": {
        "mode": "companion",
        "description": "Ask grounded questions about Jharkhand destinations, nearby mapped places, culture, and trip planning.",
        "status": "Grounded travel assistant",
        "note": "Answers use the destination catalogue and connected travel modules. Prices, crowd metrics, and event dates are never guessed.",
    },
    "interactive-maps": {
        "mode": "map",
        "description": "Plan a road route from your current location or another source, then explore mapped or synthetic nearby places.",
        "status": "Map available",
        "note": "Road directions use OSRM and require a source and destination; browser location is used only after you choose to share it. Known destinations are loaded locally. OpenStreetMap listings may be incomplete; restaurant and hotel fallbacks are clearly labelled synthetic samples.",
    },
    "hidden-gems": {
        "mode": "hidden_gems",
        "description": "Review evidence-backed candidates using natural value, cultural value, popularity, accessibility, and sustainability.",
        "status": "Evidence required",
        "note": f"A place is considered a candidate only with all five source-linked ratings and a popularity index of {LESSER_KNOWN_POPULARITY_MAX}/100 or lower. The threshold is a transparent prototype rule, not a claim about any place.",
    },
    "crowd-prediction": {
        "mode": "crowd",
        "description": "Explore clearly labelled sample crowd-index trends and seasonal projections for Jharkhand destinations.",
        "status": "Illustrative sample · not live",
        "note": "All current values are synthetic sample indices, not observed visitors, live counts, or verified crowd predictions.",
    },
    "community-connect": {
        "mode": "community",
        "description": "Discover locally hosted experiences and send enquiries to providers whose listings have been reviewed.",
        "status": "Community listings",
        "note": "Profiles are shown only after an administrator publishes them with a source and review date. No demo profiles are mixed into the directory; contact details appear only when separately verified.",
    },
    "tourist-safety": {
        "mode": "map",
        "map_category": "safety",
        "description": (
            "Find official emergency contacts, prepare a private trip check-in or SOS draft, "
            "and view mapped hospitals and police stations."
        ),
        "status": "Official contacts · mapped services",
        "note": "Emergency contacts link to official Jharkhand Police/ERSS sources. Nearby hospitals and police stations come from OpenStreetMap, may be incomplete or out of date, and are not an emergency dispatch service.",
    },
    "weather-insights": {
        "mode": "weather",
        "description": "Check current conditions and a live forecast for a Jharkhand destination before you travel.",
        "status": "Live forecast · OpenWeatherMap",
        "note": (
            "Weather comes from OpenWeatherMap's live API for the selected catalogue point. "
            "Forecasts are not official warnings or confirmation of a destination's access "
            "or safety; verify local advisories before travelling."
        ),
    },
    "smart-budget": {
        "mode": "budget",
        "description": "A trip-cost workspace for comparing transport, stays, meals, and activities.",
        "status": "Editable sample estimate",
        "note": "Sample rates are illustrative assumptions, not verified prices or live quotes. Edit category totals to reflect your own research.",
    },
    "cultural-explorer": {
        "mode": "culture",
        "description": "Explore source-linked cultural guides for selected Jharkhand destinations.",
        "status": "QR cultural guides",
        "note": "Cultural details are linked to official sources. Missing art or audio is identified rather than inferred.",
    },
    "travel-passport": {
        "mode": "passport",
        "description": "Track visited places, collect destination stamps, and follow your travel achievements.",
        "status": "Personal travel passport",
        "note": "Visits are private to your account. Self-reported visits and valid destination QR check-ins are labeled separately.",
    },
    "smart-trip-intelligence": {
        "mode": "intelligence",
        "description": "Bring destination services, travel conditions, estimates, safety, and evidence together in one view.",
        "status": "Destination intelligence",
        "note": "Select a catalogue destination to load its connected modules. Sample crowd indices and budget estimates are labeled; unsupported or unconfigured data is shown as unavailable, never invented.",
    },
    "restaurants": {
        "mode": "map",
        "map_category": "restaurants",
        "description": "Discover mapped restaurants and food places near a selected destination.",
        "status": "OpenStreetMap listings",
        "note": "Restaurant names, cuisine, ratings, prices, and coordinates are shown only when present in OpenStreetMap tags. Distance is straight-line, not driving distance; confirm details with the restaurant.",
    },
    "hotels-stays": {
        "mode": "map",
        "map_category": "hotels",
        "description": "Explore mapped hotels, resorts, homestays, and other accommodation near a destination.",
        "status": "OpenStreetMap listings",
        "note": "Accommodation type, photos, prices, and booking links appear only when mapped. Missing prices or links are not inferred; this is not a live availability feed.",
    },
    "cultural-events": {
        "mode": "map",
        "map_category": "cultural-events",
        "description": "Preview cultural-event layouts and filtering with clearly disclosed synthetic records.",
        "status": "Synthetic prototype dataset",
        "note": "The bundled event CSV is illustrative demo data, not a confirmed or verified public schedule. Recheck official or organiser sources before planning a visit.",
    },
    "my-itineraries": {
        "mode": "itineraries",
        "description": "Review and return to journeys saved to your account.",
        "status": "Your saved trips",
        "note": "Saved itinerary drafts are private to your prototype account. AI-assisted drafts are stored only when you choose Save itinerary.",
    },
    "sustainability-dashboard": {
        "mode": "sustainability",
        "description": "Review sustainability ratings when documented evidence is available.",
        "status": "Evidence needed",
        "note": "No sustainability scores are currently published because the catalogue has no supporting evidence for them.",
    },
    "profile": {
        "mode": "profile",
        "description": "Review the name and email address associated with this prototype profile.",
        "status": "Prototype profile",
        "note": "Name and email are not verified identity credentials.",
    },
}


def summarize_destinations(destinations: list[Destination]) -> dict[str, Any]:
    scored_destinations = [
        destination
        for destination in destinations
        if destination.sustainability_score is not None
    ]
    scores = [
        destination.sustainability_score
        for destination in scored_destinations
        if destination.sustainability_score is not None
    ]
    return {
        "destination_count": len(destinations),
        "district_count": len({destination.district for destination in destinations}),
        "category_count": len({destination.category for destination in destinations}),
        "average_score": round(sum(scores) / len(scores)) if scores else None,
        "featured": destinations[:3],
        "recommended": sorted(
            scored_destinations,
            key=lambda destination: (
                -(destination.sustainability_score or 0),
                destination.name,
            ),
        )[:3],
        "chart_data": [
            {"name": destination.name, "score": destination.sustainability_score}
            for destination in scored_destinations
        ],
    }


def rank_hidden_gems(destinations: list[Destination]) -> list[dict[str, Any]]:
    metric_fields = (
        ("natural_value", "natural_value_source"),
        ("cultural_value", "cultural_value_source"),
        ("popularity", "popularity_source"),
        ("accessibility", "accessibility_source"),
        ("sustainability_score", "sustainability_score_source"),
    )
    ranked = []
    for destination in destinations:
        if (
            destination.natural_value is None
            or destination.cultural_value is None
            or destination.popularity is None
            or destination.accessibility is None
            or destination.sustainability_score is None
        ):
            continue
        sources = [getattr(destination, source_field) for _, source_field in metric_fields]
        if (
            any(not source for source in sources)
            or destination.popularity > LESSER_KNOWN_POPULARITY_MAX
        ):
            continue
        ranking_score = round(
            (
                destination.natural_value
                + destination.cultural_value
                + (100 - destination.popularity)
                + destination.accessibility
                + destination.sustainability_score
            )
            / 5
        )
        ranked.append({"destination": destination, "ranking_score": ranking_score})
    return sorted(
        ranked,
        key=lambda item: (-item["ranking_score"], item["destination"].name),
    )


def filter_destinations(
    destinations: list[Destination],
    query: str = "",
    category: str | None = None,
) -> list[Destination]:
    normalized_query = query.strip().casefold()
    normalized_category = category.casefold() if category else None
    results = []
    for destination in destinations:
        searchable = " ".join(
            (destination.name, destination.district, destination.category, destination.description)
        ).casefold()
        if normalized_query and normalized_query not in searchable:
            continue
        if normalized_category and destination.category.casefold() != normalized_category:
            continue
        results.append(destination)
    return results
