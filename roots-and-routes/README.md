# ROOTS & ROUTES

An extensible Flask starter for discovering eco-cultural destinations in Jharkhand. It includes a premium sign-in/registration flow, a responsive SaaS-style dashboard, session-protected workspaces, SQLite user records and travel passports, a searchable destination catalogue, a local community-provider directory, an interactive Leaflet map, tourist safety assistance, live destination weather, an editable sample trip-budget calculator and itinerary planner, Chart.js sample crowd analytics, a sourced travel-emissions calculator, QR cultural guides, and a unified destination-intelligence workspace.

## Requirements

- Python 3.10 or newer
- Internet access for the Leaflet/OpenStreetMap and Chart.js assets, map tiles, and the Unsplash sign-in background; live weather also needs an OpenWeatherMap API key

## Install and run (Windows PowerShell)

From the project directory:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
Copy-Item .env.example .env
$env:SESSION_SECRET = [guid]::NewGuid().ToString()
# Optional: enable provider administration with a high-entropy private key.
$env:COMMUNITY_ADMIN_KEY = [guid]::NewGuid().ToString("N") + [guid]::NewGuid().ToString("N")
python app.py
```

Open <http://127.0.0.1:5000>. Register with your name and email, then sign in using the same details. Every dashboard workspace opens its own route; features requiring unavailable live feeds, pricing, or verified listings say when their data is missing. The Travel Companion works in local rule-based mode by default. To stop the development server, press `Ctrl+C`.

The app loads `.env` from the project directory and also accepts environment variables set by the shell (shell variables take precedence). Use a persistent, private `SESSION_SECRET` outside local development and set `SESSION_COOKIE_SECURE=1` when serving over HTTPS. Set `FLASK_DEBUG=0` outside development.

To enable live weather, obtain an API key from [OpenWeatherMap](https://openweathermap.org/api) and set `OPENWEATHER_API_KEY` in `.env` or the server environment. Keep the key private; it is used only by the server.

## Sign-in prototype limitations

Registration and login use only a full name and email address. This is not identity verification or secure account authentication because there is no password, email verification, or other secret credential. Do not use sensitive information or rely on it to protect private data. The Flask session cookie is HTTP-only and same-site, and form submissions use CSRF tokens, but those measures do not make a name-and-email-only login secure. If passwords are introduced, store only salted password hashes using a suitable password-hashing library; never store plaintext passwords.

Run the complete test suite from the project directory with `python -m unittest discover -s tests -v`.

## Project architecture

```text
roots-and-routes/
├── app.py                       Flask app factory and development entry point
├── database.py                  SQLite connection lifecycle and schema setup
├── routes/                      Web and API blueprints
├── services/                    Destination catalogue and data-access logic
│   ├── auth_service.py          Name/email registration and sign-in
│   ├── budget_service.py        Validates inputs and calculates editable sample trip budgets
│   ├── crowd_service.py         Validates sample indices and calculates seasonal projections
│   ├── cultural_explorer_service.py Validates sourced guide content and canonical QR URLs
│   ├── carbon_service.py        Validates configurable emission factors and calculates estimates
│   ├── dashboard_service.py     Navigation, page metadata, and dashboard summaries
│   ├── event_service.py         Validates and filters scheduled cultural events
│   ├── itinerary_service.py     Validates, stores, and retrieves user-owned itinerary drafts
│   ├── map_service.py           Nominatim, OSRM, and Overpass integrations
│   ├── passport_service.py      User-scoped travel history, achievements, and expiring QR check-ins
│   ├── safety_service.py        Source-linked emergency contacts and general safety tips
│   ├── security.py              Session-backed CSRF token helpers
│   ├── weather_service.py       OpenWeatherMap current conditions and forecast integration
│   └── travel_companion_service.py Grounded answers and optional LLM integration
├── models/                      Typed domain models
├── data/                        Destination/cultural guide records, event, crowd, and transport data
├── templates/                   Jinja HTML templates
└── static/
    ├── css/                     Responsive application and auth stylesheets
    ├── js/                      Dashboard, budget/planner, companion, crowd/carbon charts, catalogue, map, safety, weather, and destination intelligence
    └── images/                  Local image assets, including a community-card placeholder
```

## Destination catalogue and evidence

The starter catalogue includes Hundru Falls, Dassam Falls, Jonha Falls, Betla National Park, Netarhat, Patratu Valley, Deoghar, Parasnath Hills, Tagore Hill, and McCluskieganj. Place names, districts, and map points link to their OpenStreetMap records; Patratu Valley uses an explicitly labelled approximate anchor at the mapped Patratu settlement, and the Betla point is an approximate area point rather than an entrance. Map data is © OpenStreetMap contributors and is available under the Open Database License (ODbL); retain attribution and follow the [ODbL terms](https://www.openstreetmap.org/copyright).

Destination photos are linked to Wikimedia Commons file pages. Each photo card displays the author, license, and license link when required. Re-check the file page before reuse because file metadata and licenses may change. OpenStreetMap tiles are provided by the OpenStreetMap community; follow its tile usage policy. The map and chart libraries are loaded from public CDNs.

## Interactive map and road routing

The **Interactive Maps** workspace uses Leaflet with OpenStreetMap tiles. Destination names in the source and destination fields autocomplete from the local catalogue. For other places, use **Search location** to request explicit Nominatim search results; the public Nominatim service is not called while typing because its usage policy prohibits autocomplete. The server caches successful searches and applies a process-local one-second request interval. The public Nominatim limit is per application, so a multi-process deployment needs a shared rate limiter/cache to stay within policy. Map searches are user-triggered; do not send personal or confidential information.

Road routes, route geometry, distance, travel-time estimates, turn-by-turn steps, and any alternatives come from OSRM's driving profile. The app does not substitute straight-line distance when routing is unavailable. Restaurant and accommodation discovery queries OpenStreetMap through Overpass. Straight-line distance is calculated from the selected destination to each mapped place; it is not driving distance. Cuisine, rating, price, type, and booking fields are shown only when corresponding OSM tags are present; images are displayed only for mapped Wikimedia Commons files, with a link to the file/license page. The budget filter requires an explicit budget tag or budget-hotel classification; hostels are not automatically described as budget. OSM/Overpass coverage may be sparse, and external services can be unavailable.

The Restaurants, Hotels & Stays, and Cultural Events workspaces share the interactive map, destination selector, nearby markers, and OSRM directions. Cultural Events are distinct from OSM event venues. Future records with exact dates, a venue, coordinates, a source link, a `government`, `organizer`, or `venue` source type, and a `verified_on` date in `data/cultural_events.csv` are published. Government sources must use a `.gov.in` or `.gov` domain. The bundled event CSV is a clearly disclosed **synthetic demo dataset** for interface and feature testing: each record has `data_status=synthetic`, an illustrative date and venue, and a disclosure note. Synthetic records must not be presented as confirmed schedules or used for real travel planning. Replace or remove them with official government/tourism, event-organizer, or venue listings before production use, and re-check event details before updating `verified_on`. The Jharkhand Tourism [festival information page](https://tourism.jharkhand.gov.in/festivals) provides cultural context but is not a date-and-venue calendar.

The provider base URLs and Nominatim identification string can be changed through `.env`: `NOMINATIM_BASE_URL`, `NOMINATIM_USER_AGENT`, `OSRM_BASE_URL`, and `OVERPASS_URL`. Keep a recognizable application User-Agent and contact information for deployed use. The public geocoding, routing, and Overpass services are best-effort shared services, not production SLAs; follow their current usage policies and configure self-hosted or other providers if demand requires it.

## Smart Crowd Prediction

The **Crowd Prediction** workspace is an algorithm/UI demonstration. `data/crowd_history_sample.csv` contains synthetic monthly indices for the listed destinations and sample years 2023–2025. The values are invented for the prototype, are not actual historical visitor data, and must never be treated as live counts or verified crowd predictions.

For a selected destination and calendar month, the simple projection starts with the latest sample-year index and adds the average annual change between the earliest and latest sample years for that same month. This preserves the sample's month-of-year pattern and makes a one-year projection, clamped to 0–100. The dashboard labels Low as 0–35, Moderate as 36–65, and High as 66–100. Suggested periods are the three months with lowest sample projections for that destination; alternatives are catalogue destinations with lower sample projections for the selected month.

These are relative synthetic indices, not counts. The sample has no verified visitor history, occupancy feed, event, weather, or access-condition inputs. Its seasonal pattern is illustrative only and cannot establish when a real destination is quieter or best to visit. Replace it with sourced, comparable historical data before using results for operational decisions, and retain clear provenance and units.

## Travel Carbon Footprint

The authenticated **Carbon Footprint** workspace calculates a one-way trip estimate, reports total and per-traveller operational emissions, compares car, bus, train, bicycle, and walking, and provides a printable sustainability report. When both locations are selected from the local destination catalogue or resolved through an explicit Nominatim search, the API requests an OSRM road distance. If that route cannot be calculated, a user-entered distance can be used and is labelled as such. The same distance is used for every comparison; OSRM road distance is not an actual bus or rail route length.

Factors are in `data/transport_emission_factors.csv` and can be changed through the `TRANSPORT_EMISSION_FACTORS_PATH` setting. Each record identifies its units, calculation basis, source, year, and limitations. The default positive factors come from the UK Department for Energy Security and Net Zero's 2026 **Business travel - land** conversion-factor workbook: average car (unknown fuel type), average local bus, and national rail. The workbook is linked from the official [2026 publication page](https://www.gov.uk/government/publications/greenhouse-gas-reporting-conversion-factors-2026). These are UK reporting factors, not measurements for Jharkhand or India; replace them with appropriate local sources before treating estimates as locally representative.

Calculations preserve the workbook's unit basis: car is kg CO₂e per vehicle-kilometre, so one car's trip total is distance × factor and is divided by the traveller count only for the per-person result. Bus and rail are per passenger-kilometre, so their group total is distance × factor × travellers. Bicycle and walking use zero **direct operational** emissions as a stated calculator boundary assumption, not as sourced lifecycle factors. Upstream fuel, vehicle manufacture, infrastructure, and other lifecycle impacts are excluded. Results are CO₂-equivalent (CO₂e), not pure CO₂; they are estimates and do not account for uncertainty or mode availability.

The calculator endpoint requires an authenticated session and CSRF token. Tests cover factor provenance and validation, vehicle-versus-passenger calculation, OSRM distance selection, manual fallback, and authentication/input checks.

## Local Community Connect

The authenticated **Community Connect** directory supports tour guides, handicraft artisans, traditional food experiences, tribal art workshops, village tourism, and cultural activities. It filters published SQLite listings by type or search text and renders profile cards with experience, location, description, and an image when a sourced image is available. If no image is supplied, the card uses a local illustration. The directory starts empty; no provider profiles or sample contact details are fabricated.

To enable the admin area, set a private `COMMUNITY_ADMIN_KEY` of at least 32 characters in the environment or `.env` (the `.env` file is git-ignored). Sign in, open **Community Connect → Admin section**, and unlock with that key. The key is checked server-side and is not placed in the session; successful access is limited to the browser session. Administrators can add, edit, publish, and unpublish listings, and review/resolve enquiries. Unpublishing retains the provider record and enquiry history. Publishing requires an HTTPS listing source and a review date. Contact fields are accepted only with a separate verification source, date, and an explicit permission checkbox; unverified contacts are not returned to the public directory. Images also require HTTPS source and attribution.

Traveller enquiries are stored in the local SQLite inbox and are not emailed automatically. The sender's account email is shown to administrators as unverified, since the prototype sign-in uses only a name and email address. The admin key is a prototype gate, not a substitute for production authentication, rate limiting, access logging, and secure secret management. Do not deploy this name-and-email account system or a shared admin key as production identity controls.

## QR Cultural Explorer

The public **Cultural Explorer** at `/culture` and its destination pages are readable without signing in so a phone camera can open QR links directly. Curated guides are currently available for Baba Baidyanath Dham Temple and Parasnath Hills, in `data/cultural_destinations.json`. Historical, tribal-tradition, and festival notes link to Deoghar or Giridih district administration and Jharkhand Tourism sources. The pages distinguish site-specific information from statewide context; local art or audio is explicitly marked unavailable when no destination-specific, attributed material has been verified. Cultural photographs link to their Wikimedia Commons source and show attribution/license information.

To generate QR codes, configure `PUBLIC_BASE_URL` as the canonical public HTTPS origin, sign in, open **Cultural Explorer → Administrator QR generator**, and unlock with the existing `COMMUNITY_ADMIN_KEY`. HTTP origins are accepted for localhost development only. QR SVGs contain only the configured canonical destination URL, not a request Host header; the SVG endpoint is restricted to the administrator session and sends no-store responses. Test each code on a phone before printing. If the site is deployed under a URL prefix, configure the application/proxy so the QR target resolves to the same public guide route.

The current version is QR-linked web content only. Augmented reality is not implemented; destination data reserves an extension list for future AR work without exposing an AR feature now. The shared community admin key and prototype sign-in are not production identity controls.

## Digital Travel Passport

The authenticated **Travel Passport** stores dated destination visits in SQLite, keyed by the signed-in prototype account. Visitors can record a self-reported visit or confirm a current administrator-issued destination QR check-in. The passport shows visit history, stamps, supported-destination completion, and progress toward Waterfall Explorer, Nature Lover, Culture Enthusiast, Hidden Gem Discoverer, and Eco Traveller achievements. A same-day self-reported record can be upgraded to QR-verified; the two methods remain separately labelled.

Passport QR codes use the existing `COMMUNITY_ADMIN_KEY` administration gate and require `PUBLIC_BASE_URL` to be set to the canonical public HTTPS origin (HTTP is allowed for localhost development). Each code expires after 15 minutes, and only a token hash is stored in SQLite. A visitor must sign in and explicitly confirm the scan before a verified visit is recorded. QR validation proves only that the administrator-issued code was valid; it does not prove physical presence or visitor identity, and the feature does not request device location. Achievement progress that depends on evidence not yet present in the catalogue stays unavailable rather than being inferred.

Passport rows are isolated by user ID in the application, but the prototype's name-and-email-only login is not secure authentication. Do not treat this implementation as a production identity or privacy boundary without replacing the sign-in system and adding appropriate operational protections.

## Smart Trip Intelligence

The authenticated **Smart Trip Intelligence** workspace automatically assembles destination services around the selected catalogue point: OpenStreetMap nearby attractions, restaurants, and stays; dated/source-verified cultural events; live OpenWeatherMap data when `OPENWEATHER_API_KEY` is configured; an editable illustrative trip budget; OSRM road routes; transport-factor carbon estimates; official emergency links and mapped safety services; and catalogue crowd, sustainability, and hidden-gem evidence. A grounded summary calls out returned signals and important limitations. Links connect the brief to the planner, budget calculator, passport, map, safety, weather, Cultural Explorer, and carbon workspaces.

The route origin is selected from catalogue destinations, initially Tagore Hill; the browser's geolocation API is not used. The current crowd index is synthetic sample data, not observed visitors. Budget prices are illustrative assumptions, not quotes. Sustainability scores and hidden-gem alternatives appear only when their evidence criteria are met; the current catalogue has no qualifying sourced scores or hidden-gem candidates. Live weather is never replaced with sample conditions when the API key or provider is unavailable. Nearby hospitals and police stations are community-mapped OSM records, not an official dispatch directory; use the linked official emergency contacts for urgent assistance. Every module reports unavailable provider data rather than fabricating a result.

## Tourist Safety Assistance

The authenticated **Tourist Safety** workspace links to India's 112 Emergency Response Support System and the Jharkhand Police portal. The official Jharkhand Police homepage currently displays a Dial 100/112 banner. The additional Jharkhand Police DG Control Room numbers shown are taken from its official [contact directory](https://jhpolice.gov.in/contact-us), which reported an update on 17 November 2026 when checked. Recheck official pages before relying on a number; 112 is the prominently presented emergency option.

Nearby hospitals and police stations are looked up from OpenStreetMap through the configured Overpass endpoint and shown as mapped points with individual OSM record links. These entries are community-mapped, not an official service directory, may be incomplete or out of date, and do not confirm opening hours, availability, or emergency response. They are not a substitute for calling 112.

Browser location is requested only after the user presses **Use my location once** and approves the browser prompt. The browser may remember that permission; users can revoke it in their browser's site settings. Location is held in page memory, can be removed with **Forget location**, and is not saved in the app database. A nearby lookup sends the selected coordinates to the app server and the third-party Overpass service; safety searches bypass the app's in-process nearby-results cache. The trip check-in and SOS controls create user-reviewed `mailto:` or SMS drafts on the device; they do not send or store messages, and the app cannot confirm delivery. Exact coordinates are excluded unless the user separately enables **Include a link to my current location in the contact draft**. The emergency call link opens the device's dialer for 112; the app cannot place or verify calls. No live location tracking, background location access, or automatic SOS sending is implemented.

## Weather-Based Travel Recommendations

The authenticated **Weather Insights** workspace retrieves current conditions and the 5-day/3-hour forecast from the OpenWeatherMap API for a destination selected from the local catalogue. The server requires `OPENWEATHER_API_KEY`; the key is never sent to the browser. The current temperature and condition, rain probability for the next forecast period, daily forecast summaries, provider observation time, and weather-based recommendations are shown only after a successful live response. If the key is missing or the provider fails, the workspace reports that live weather is unavailable and displays no sample or fallback weather.

Rain probabilities are OpenWeatherMap forecast-period probabilities; each displayed daily percentage is the highest 3-hour probability in that local date, not the chance of any rain all day. Recommendations use the returned forecast, including elevated-rain and thunderstorm periods. When heavy-rain conditions with at least a 50% provider probability appear within 24 hours for a catalogue waterfall, the page advises checking official local advisories and access status, and considering postponement or another destination. This is general travel guidance, not an official weather alert, site-access report, or guarantee of conditions. The selected catalogue coordinates are sent to the app server and OpenWeatherMap only when the user requests or refreshes weather; the app does not request device location.

## Smart Trip Budget and AI Travel Planner

The authenticated **Smart Budget** calculator estimates transportation, accommodation, food, activities, and other expenses from the trip duration, traveller count, mode, and preferences. Every default rate is an explicitly labelled illustrative sample assumption, not a local price, live quote, or verified fare. Accommodation uses up to two travellers per room and `days - 1` nights (zero for a one-day trip); private-car capacity is up to four travellers per vehicle. These are assumptions. Users can edit each category total; the calculator then updates total cost, per-person cost, remaining/over-budget amount, and an accessible breakdown chart. The estimate is calculated locally on the server and is not saved to an account.

**Continue to itinerary planner** carries the budget inputs, user-edited category totals, and optional destination focus to the **AI Travel Planner** in the current browser tab's session storage; they are not added to the URL or saved by the calculator. The planner can include up to five catalogue destinations and generates a destinations-only draft. When an OpenAI-compatible provider is configured, it may organize the grounded draft using the trip constraints; otherwise the local catalogue-based draft is used. After generating a draft, choose **Save itinerary** to persist the outline and editable sample budget in SQLite under the current user account. **My Itineraries** lists and can delete those saved drafts. Each account sees only rows with its own user ID; pre-feature legacy rows without an owner are not exposed. Neither planner mode verifies prices, budget fit, routes, travel times, opening hours, availability, site access, or safety. Verify details with current official/local sources before booking or travelling. Optional AI generation sends the trip budget, preferences, sample estimate, and selected public catalogue records to the configured provider; account details are not sent. Do not enter personal or sensitive information.

## AI Travel Companion

The authenticated **AI Travel Companion** workspace provides a chat interface for destination lookups, waterfalls, nearby OpenStreetMap restaurants and stays, verified cultural-event listings, and itinerary context. Its local fallback uses the destination catalogue and existing map/event services. It explicitly declines to promise a budget without sourced transport, accommodation, meal, and entry prices; it also will not infer current crowd levels or unscheduled event dates.

To enable optional OpenAI-compatible chat completions, set `OPENAI_API_KEY` in `.env`; `OPENAI_CHAT_COMPLETIONS_URL` and `OPENAI_MODEL` can select another compatible endpoint/model. Leave the key blank for rule-based mode. No extra Python package is required. The chat assistant's unsupported budget, crowd, event, and provider-failure cases use the local response. It receives a grounded draft and relevant public records, not the raw chat message, account identity, or saved itinerary context. The separate planner behavior and its data disclosure are described above. Never place secrets or personal details in travel prompts.

The short itinerary context (duration, budget, destination IDs, and interests) is kept in Flask's signed session cookie by the companion and planner, and is cleared by logout or the chat's **Clear** action. Flask's default cookie is signed, not encrypted; do not treat this prototype as secure storage for confidential information. The chat transcript and budget estimates are not persisted to the database.

Natural value, cultural value, popularity, accessibility, and sustainability ratings are intentionally blank until there is suitable evidence. The Hidden Gems page admits a destination only when all five ratings have individual source links and its sourced popularity index is at most 40/100. Eligible records are ranked using an equal-weight mean of natural value, cultural value, inverse popularity, accessibility, and sustainability. This is a transparent prototype rule, not a factual label; the current catalogue has no qualifying records. Add sourced, methodologically consistent values and their source URLs to `data/destinations.csv` before ranking any destinations.
