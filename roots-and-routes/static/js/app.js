"use strict";

const mapState = {
  map: null,
  destinations: [],
  destinationsByName: new Map(),
  destinationsById: new Map(),
  locations: { source: null, destination: null },
  geocodeRequests: { source: 0, destination: 0 },
  routes: [],
  routeLayers: null,
  routeMarkers: null,
  destinationMarkers: null,
  nearbyMarkers: null,
  nearbyPlaces: [],
  lastNearbyCategory: "",
  moduleCategory: "",
};

document.addEventListener("DOMContentLoaded", initializeMapWorkspace);

async function initializeMapWorkspace() {
  const mapElement = document.querySelector("#destination-map");
  if (!mapElement) {
    return;
  }

  mapState.moduleCategory = document.querySelector(".nearby-section")?.dataset.moduleCategory || "";
  setupRouteControls();
  initializeMap(mapElement);
  await loadDestinations();
  if (mapState.moduleCategory === "cultural-events") {
    await loadCulturalEvents(false);
  }
}

function initializeMap(element) {
  const status = document.querySelector("#map-status");
  if (!window.L) {
    setStatus(status, "The map library did not load. Check your connection and reload the page.", true);
    return;
  }

  mapState.map = L.map(element).setView([23.6, 85.3], 7);
  mapState.destinationMarkers = L.layerGroup().addTo(mapState.map);
  mapState.routeLayers = L.layerGroup().addTo(mapState.map);
  mapState.routeMarkers = L.layerGroup().addTo(mapState.map);
  mapState.nearbyMarkers = L.layerGroup().addTo(mapState.map);

  const tiles = L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    maxZoom: 19,
  }).addTo(mapState.map);
  tiles.on("tileerror", () => {
    setStatus(status, "Some map tiles could not be loaded. The map data may be temporarily unavailable.", true);
  });
  tiles.on("load", () => {
    setStatus(status, "Map data © OpenStreetMap contributors.");
  });
}

async function loadDestinations() {
  const catalogueStatus = document.querySelector("#catalogue-status");
  try {
    const destinations = await requestJson("/api/destinations");
    mapState.destinations = destinations;
    for (const destination of destinations) {
      mapState.destinationsByName.set(destination.name.trim().toLocaleLowerCase(), destination);
      mapState.destinationsById.set(destination.id, destination);
    }
    renderDestinationChoices(destinations);
    renderDestinationMarkers(destinations);
    resolveCatalogueInput("source");
    resolveCatalogueInput("destination");
    if (catalogueStatus) {
      catalogueStatus.textContent = `${destinations.length} destination${destinations.length === 1 ? "" : "s"} in the catalogue.`;
    }
  } catch (error) {
    setStatus(catalogueStatus, error.message || "Destinations could not be loaded.", true);
    setStatus(document.querySelector("#map-status"), "Destination data could not be loaded.", true);
    console.error(error);
  }
}

function renderDestinationChoices(destinations) {
  const datalist = document.querySelector("#destination-suggestions");
  const destinationSelect = document.querySelector("#catalogue-destination");
  const list = document.querySelector("#destination-list");
  if (!datalist || !destinationSelect || !list) {
    return;
  }

  datalist.replaceChildren();
  destinationSelect.replaceChildren(new Option("Choose a Jharkhand destination", ""));
  list.replaceChildren();
  for (const destination of destinations) {
    datalist.append(new Option(destination.name));
    destinationSelect.append(
      new Option(`${destination.name} · ${destination.district}`, destination.id),
    );

    const item = document.createElement("article");
    item.className = "map-place-item";
    const title = document.createElement("strong");
    title.textContent = destination.name;
    const description = document.createElement("p");
    description.textContent = `${destination.district} · ${destination.category}`;
    const choose = document.createElement("button");
    choose.type = "button";
    choose.className = "map-place-select";
    choose.textContent = "Use as destination";
    choose.addEventListener("click", () => selectCatalogueDestination(destination));
    item.append(title, description, choose);
    list.append(item);
  }
}

function renderDestinationMarkers(destinations) {
  if (!mapState.destinationMarkers) {
    return;
  }
  mapState.destinationMarkers.clearLayers();
  for (const destination of destinations) {
    const marker = L.marker([destination.latitude, destination.longitude]);
    const popup = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = destination.name;
    const choose = document.createElement("button");
    choose.type = "button";
    choose.className = "map-popup-action";
    choose.textContent = "Use as destination";
    choose.addEventListener("click", () => selectCatalogueDestination(destination));
    popup.append(title, document.createElement("br"), choose);
    marker.bindPopup(popup).addTo(mapState.destinationMarkers);
  }
}

function setupRouteControls() {
  const form = document.querySelector("#route-planner-form");
  const destinationSelect = document.querySelector("#catalogue-destination");
  const swapButton = document.querySelector("#swap-locations");
  const currentLocationButton = document.querySelector("#use-current-location");
  const nearbyButtons = document.querySelectorAll("[data-nearby-category]");
  const cuisineFilter = document.querySelector("#restaurant-cuisine-filter");
  const stayTypeFilter = document.querySelector("#stay-type-filter");
  const eventCategoryFilter = document.querySelector("#event-category-filter");
  const eventSearchForm = document.querySelector("#event-search-form");

  for (const role of ["source", "destination"]) {
    const input = document.querySelector(`#route-${role}`);
    if (!input) {
      continue;
    }
    input.addEventListener("input", () => handleLocationInput(role));
    input.addEventListener("change", () => resolveCatalogueInput(role));

    const searchButton = document.querySelector(`[data-geocode="${role}"]`);
    searchButton?.addEventListener("click", () => searchLocation(role, searchButton));
  }

  currentLocationButton?.addEventListener("click", () => useCurrentLocation(currentLocationButton));
  window.addEventListener("roots-routes:set-map-location", (event) => {
    const location = event.detail;
    if (
      !Number.isFinite(location?.latitude)
      || !Number.isFinite(location?.longitude)
      || Math.abs(location.latitude) > 90
      || Math.abs(location.longitude) > 180
    ) {
      return;
    }
    const currentLocation = {
      label: "My current location",
      latitude: location.latitude,
      longitude: location.longitude,
      sourceUrl: "",
      destinationId: null,
      deviceLocation: true,
    };
    setResolvedLocation("source", currentLocation);
    if (mapState.moduleCategory === "safety") {
      setResolvedLocation("destination", currentLocation);
    }
    mapState.map?.setView([location.latitude, location.longitude], 14);
  });
  window.addEventListener("roots-routes:clear-map-location", () => {
    let destinationCleared = false;
    for (const role of ["source", "destination"]) {
      if (mapState.locations[role]?.deviceLocation) {
        mapState.locations[role] = null;
        document.querySelector(`#route-${role}`).value = "";
        destinationCleared = destinationCleared || role === "destination";
      }
    }
    if (destinationCleared) {
      document.querySelector("#catalogue-destination").value = "";
    }
    invalidateRoute();
    if (destinationCleared) {
      clearNearbyResults();
      updateNearbyButtons();
    }
    setStatus(document.querySelector("#route-status"), "Current location cleared from the map.");
  });

  form?.addEventListener("submit", (event) => {
    event.preventDefault();
    calculateRoute();
  });
  destinationSelect?.addEventListener("change", () => {
    const destination = mapState.destinationsById.get(destinationSelect.value);
    if (destination) {
      selectCatalogueDestination(destination);
    } else {
      mapState.locations.destination = null;
      document.querySelector("#route-destination").value = "";
      invalidateRoute();
      clearNearbyResults();
      updateNearbyButtons();
    }
  });
  swapButton?.addEventListener("click", swapLocations);
  for (const button of nearbyButtons) {
    button.addEventListener("click", () => loadNearbyPlaces(button));
  }
  cuisineFilter?.addEventListener("change", renderFilteredNearbyPlaces);
  stayTypeFilter?.addEventListener("change", renderFilteredNearbyPlaces);
  eventCategoryFilter?.addEventListener("change", () => {
    if (mapState.moduleCategory === "cultural-events") {
      loadCulturalEvents(
        mapState.lastNearbyCategory === "cultural-events"
        && Boolean(mapState.locations.destination),
      );
    } else if (mapState.lastNearbyCategory === "cultural-events") {
      const eventButton = document.querySelector('[data-nearby-category="cultural-events"]');
      if (eventButton && mapState.locations.destination) {
        loadNearbyPlaces(eventButton);
      }
    }
  });
  eventSearchForm?.addEventListener("submit", (event) => {
    event.preventDefault();
    loadCulturalEvents(
      mapState.lastNearbyCategory === "cultural-events"
      && Boolean(mapState.locations.destination),
    );
  });
  updateNearbyButtons();
}

function useCurrentLocation(button) {
  const status = document.querySelector("#route-status");
  if (!navigator.geolocation) {
    setStatus(status, "This browser does not support location access. Search for a source location instead.", true);
    return;
  }

  button.disabled = true;
  setStatus(status, "Waiting for your browser's location permission…", false, true);
  navigator.geolocation.getCurrentPosition(
    (position) => {
      const location = {
        label: "My current location",
        latitude: position.coords.latitude,
        longitude: position.coords.longitude,
        sourceUrl: "",
        destinationId: null,
        deviceLocation: true,
      };
      setResolvedLocation("source", location);
      mapState.map?.setView([location.latitude, location.longitude], 14);
      button.disabled = false;
    },
    (error) => {
      const messages = {
        1: "Location permission was denied. Search for a source location instead.",
        2: "Your device could not determine a location. Try again or search for a source.",
        3: "Location lookup timed out. Try again or search for a source.",
      };
      setStatus(status, messages[error.code] || "Current location is unavailable. Search for a source instead.", true);
      button.disabled = false;
    },
    { enableHighAccuracy: false, maximumAge: 30000, timeout: 10000 },
  );
}

function handleLocationInput(role) {
  const input = document.querySelector(`#route-${role}`);
  mapState.geocodeRequests[role] += 1;
  const suggestions = document.querySelector(`#location-results-${role}`);
  suggestions.replaceChildren();
  suggestions.hidden = true;
  const current = mapState.locations[role];
  if (current && current.label !== input.value.trim()) {
    mapState.locations[role] = null;
    if (role === "destination") {
      document.querySelector("#catalogue-destination").value = "";
      clearNearbyResults();
      updateNearbyButtons();
    }
    invalidateRoute();
    setStatus(
      document.querySelector("#route-status"),
      "A location changed. Resolve both locations and calculate the road route again.",
    );
  } else if (!current) {
    setStatus(
      document.querySelector("#route-status"),
      "Choose a catalogue suggestion or search this location on OpenStreetMap.",
    );
  }
}

function resolveCatalogueInput(role) {
  const input = document.querySelector(`#route-${role}`);
  const destination = mapState.destinationsByName.get(input.value.trim().toLocaleLowerCase());
  if (destination) {
    setResolvedLocation(role, catalogueLocation(destination));
  }
}

function selectCatalogueDestination(destination) {
  setResolvedLocation("destination", catalogueLocation(destination));
  document.querySelector("#catalogue-destination").value = destination.id;
  setStatus(
    document.querySelector("#route-status"),
    `${destination.name} selected from the destination catalogue.`,
  );
  if (mapState.map) {
    mapState.map.setView([destination.latitude, destination.longitude], 11);
  }
}

function catalogueLocation(destination) {
  return {
    label: destination.name,
    latitude: destination.latitude,
    longitude: destination.longitude,
    sourceUrl: destination.source_url,
    destinationId: destination.id,
  };
}

function setResolvedLocation(role, location) {
  mapState.locations[role] = location;
  const routeInput = document.querySelector(`#route-${role}`);
  if (routeInput) {
    routeInput.value = location.label;
  }
  window.dispatchEvent(new CustomEvent("roots-routes:map-location-changed", {
    detail: { role, label: location.label },
  }));
  const locationResults = document.querySelector(`#location-results-${role}`);
  if (locationResults) {
    locationResults.replaceChildren();
    locationResults.hidden = true;
  }
  if (role === "destination") {
    const matchingDestination = location.destinationId
      ? location.destinationId
      : "";
    document.querySelector("#catalogue-destination").value = matchingDestination;
    clearNearbyResults();
    updateNearbyButtons();
  }
  invalidateRoute();
  setStatus(
    document.querySelector("#route-status"),
    `${role === "source" ? "Starting point" : "Destination"} selected: ${location.label}`,
  );
}

function swapLocations() {
  const sourceInput = document.querySelector("#route-source");
  const destinationInput = document.querySelector("#route-destination");
  const sourceValue = sourceInput.value;
  const destinationValue = destinationInput.value;
  const sourceLocation = mapState.locations.source;
  const destinationLocation = mapState.locations.destination;

  sourceInput.value = destinationValue;
  destinationInput.value = sourceValue;
  mapState.locations.source = destinationLocation;
  mapState.locations.destination = sourceLocation;
  document.querySelector("#location-results-source").hidden = true;
  document.querySelector("#location-results-destination").hidden = true;
  document.querySelector("#catalogue-destination").value =
    sourceLocation?.destinationId || "";
  invalidateRoute();
  clearNearbyResults();
  updateNearbyButtons();
  setStatus(document.querySelector("#route-status"), "Starting point and destination swapped.");
}

async function searchLocation(role, button) {
  const input = document.querySelector(`#route-${role}`);
  const query = input.value.trim();
  const resultsContainer = document.querySelector(`#location-results-${role}`);
  if (query.length < 3) {
    setStatus(
      document.querySelector("#route-status"),
      "Enter at least three characters before searching.",
      true,
    );
    return;
  }

  button.disabled = true;
  const requestId = ++mapState.geocodeRequests[role];
  setStatus(document.querySelector("#route-status"), "Searching OpenStreetMap for this location…", false, true);
  resultsContainer.replaceChildren();
  resultsContainer.hidden = true;
  try {
    const response = await requestJson(`/api/geocode?q=${encodeURIComponent(query)}`);
    if (requestId !== mapState.geocodeRequests[role] || input.value.trim() !== query) {
      return;
    }
    if (!response.results.length) {
      setStatus(document.querySelector("#route-status"), "No matching locations were found. Try a more specific search.", true);
      return;
    }
    for (const result of response.results) {
      const option = document.createElement("button");
      option.type = "button";
      option.setAttribute("role", "option");
      option.textContent = result.label;
      option.addEventListener("click", () => {
        setResolvedLocation(role, {
          label: result.label,
          latitude: result.latitude,
          longitude: result.longitude,
          sourceUrl: result.source_url,
          destinationId: null,
        });
      });
      resultsContainer.append(option);
    }
    resultsContainer.hidden = false;
    setStatus(
      document.querySelector("#route-status"),
      `${response.results.length} location${response.results.length === 1 ? "" : "s"} found. Choose the correct match.`,
    );
  } catch (error) {
    setStatus(document.querySelector("#route-status"), error.message || "Location search failed. Try again later.", true);
    console.error(error);
  } finally {
    button.disabled = false;
  }
}

async function calculateRoute() {
  const source = mapState.locations.source;
  const destination = mapState.locations.destination;
  const submitButton = document.querySelector("#route-planner-form button[type='submit']");
  if (!source || !destination) {
    setStatus(
      document.querySelector("#route-status"),
      "Choose a source (or use your current location) and a destination before requesting directions.",
      true,
    );
    return;
  }

  submitButton.disabled = true;
  setStatus(document.querySelector("#route-status"), "Calculating a road route with OSRM…", false, true);
  invalidateRoute();
  try {
    const query = new URLSearchParams({
      source_lat: String(source.latitude),
      source_lon: String(source.longitude),
      destination_lat: String(destination.latitude),
      destination_lon: String(destination.longitude),
    });
    const response = await requestJson(`/api/route?${query}`);
    if (response.code === "NoRoute" || !response.routes?.length) {
      setStatus(document.querySelector("#route-status"), "OSRM could not find a drivable road route between these locations.", true);
      return;
    }
    mapState.routes = response.routes;
    renderRouteOptions();
    document.querySelector("#route-results").hidden = false;
    selectRoute(0);
    setStatus(document.querySelector("#route-status"), "Road route calculated from the OSRM road network.");
  } catch (error) {
    setStatus(document.querySelector("#route-status"), error.message || "Road routing failed. Try again later.", true);
    console.error(error);
  } finally {
    submitButton.disabled = false;
  }
}

function renderRouteOptions() {
  const container = document.querySelector("#route-options");
  const note = document.querySelector("#route-alternatives-note");
  container.replaceChildren();
  mapState.routes.forEach((route, index) => {
    const button = document.createElement("button");
    button.type = "button";
    button.setAttribute("aria-pressed", index === 0 ? "true" : "false");
    button.textContent = `Route ${index + 1} · ${formatDistance(route.distance)} · ${formatDuration(route.duration)}`;
    button.addEventListener("click", () => selectRoute(index));
    container.append(button);
  });
  note.textContent = mapState.routes.length > 1
    ? `${mapState.routes.length} route options were returned by OSRM.`
    : "OSRM did not return an alternative route for this trip.";
}

function selectRoute(index) {
  const route = mapState.routes[index];
  if (!route) {
    return;
  }
  const coordinates = route.geometry?.coordinates;
  if (!Array.isArray(coordinates) || coordinates.length < 2) {
    setStatus(document.querySelector("#route-status"), "The routing service returned a route without usable road geometry.", true);
    return;
  }

  document.querySelectorAll("#route-options button").forEach((button, buttonIndex) => {
    button.setAttribute("aria-pressed", String(buttonIndex === index));
  });
  renderRouteSummary(route);
  renderTurnByTurn(route);
  if (!mapState.map) {
    return;
  }

  mapState.routeLayers.clearLayers();
  mapState.routeMarkers.clearLayers();
  let selectedLayer = null;
  mapState.routes.forEach((candidate, candidateIndex) => {
    const points = candidate.geometry?.coordinates;
    if (!Array.isArray(points) || points.length < 2) {
      return;
    }
    const line = L.polyline(
      points.map(([longitude, latitude]) => [latitude, longitude]),
      candidateIndex === index
        ? { color: "#237247", weight: 6, opacity: 0.9 }
        : { color: "#708276", weight: 4, opacity: 0.6, dashArray: "7 7" },
    ).addTo(mapState.routeLayers);
    if (candidateIndex === index) {
      selectedLayer = line;
    }
    line.on("click", () => selectRoute(candidateIndex));
  });

  addRouteMarker(mapState.locations.source, "source", "Starting point");
  addRouteMarker(mapState.locations.destination, "destination", "Destination");
  const bounds = selectedLayer?.getBounds();
  if (bounds?.isValid()) {
    mapState.map.fitBounds(bounds, { padding: [28, 28], maxZoom: 14 });
  }
}

function addRouteMarker(location, role, label) {
  if (!location || !mapState.routeMarkers) {
    return;
  }
  const marker = L.marker([location.latitude, location.longitude], {
    icon: L.divIcon({
      className: `route-pin route-pin-${role}`,
      iconSize: [16, 16],
      iconAnchor: [8, 16],
    }),
  });
  const popup = document.createElement("strong");
  popup.textContent = `${label}: ${location.label}`;
  marker.bindPopup(popup).addTo(mapState.routeMarkers);
}

function renderRouteSummary(route) {
  const summary = document.querySelector("#route-summary");
  summary.replaceChildren();
  for (const [label, value] of [
    ["Road distance", formatDistance(route.distance)],
    ["Estimated drive", formatDuration(route.duration)],
  ]) {
    const item = document.createElement("div");
    const strong = document.createElement("strong");
    strong.textContent = value;
    const caption = document.createElement("span");
    caption.textContent = label;
    item.append(strong, caption);
    summary.append(item);
  }
}

function renderTurnByTurn(route) {
  const list = document.querySelector("#turn-by-turn");
  list.replaceChildren();
  const steps = (route.legs || []).flatMap((leg) => leg.steps || []);
  if (!steps.length) {
    const item = document.createElement("li");
    item.textContent = "Turn-by-turn directions were not returned for this road route.";
    list.append(item);
    return;
  }
  for (const step of steps) {
    const item = document.createElement("li");
    const distance = step.distance > 0 ? ` · ${formatDistance(step.distance)}` : "";
    item.textContent = `${instructionFor(step)}${distance}`;
    list.append(item);
  }
}

function instructionFor(step) {
  const maneuver = step.maneuver || {};
  const modifier = maneuver.modifier || "";
  const road = step.name || step.ref || "";
  let instruction;
  switch (maneuver.type) {
    case "depart":
      instruction = "Start";
      break;
    case "arrive":
      instruction = "Arrive at your destination";
      break;
    case "roundabout":
    case "rotary":
      instruction = maneuver.exit
        ? `At the roundabout, take exit ${maneuver.exit}`
        : "Enter the roundabout";
      break;
    case "turn":
    case "end of road":
      instruction = `Turn ${modifier || "ahead"}`;
      break;
    case "fork":
      instruction = `Keep ${modifier || "straight"}`;
      break;
    case "merge":
      instruction = "Merge";
      break;
    case "on ramp":
      instruction = "Take the ramp";
      break;
    case "off ramp":
      instruction = "Take the exit ramp";
      break;
    default:
      instruction = modifier ? `Continue ${modifier}` : "Continue";
  }
  if (road && maneuver.type !== "arrive") {
    instruction += maneuver.type === "depart" ? ` on ${road}` : ` onto ${road}`;
  }
  return instruction;
}

async function loadNearbyPlaces(button) {
  const destination = mapState.locations.destination;
  const category = button.dataset.nearbyCategory;
  if (category === "cultural-events" && !destination) {
    await loadCulturalEvents(false);
    return;
  }
  if (!destination) {
    setStatus(document.querySelector("#nearby-status"), "Choose a destination first.", true);
    return;
  }
  const status = document.querySelector("#nearby-status");
  const categoryButtons = [...document.querySelectorAll("[data-nearby-category]")];
  categoryButtons.forEach((item) => { item.disabled = true; });
  setStatus(status, `Searching nearby ${category === "hotels" ? "hotels and stays" : category}…`, false, true);
  mapState.lastNearbyCategory = category;
  categoryButtons.forEach((item) => {
    item.setAttribute("aria-pressed", String(item === button));
  });
  try {
    if (category === "cultural-events") {
      await loadCulturalEvents(true);
      return;
    }
    let response;
    if (mapState.moduleCategory === "safety") {
      const nearbySection = document.querySelector(".nearby-section");
      response = await requestJson(nearbySection.dataset.safetyNearbyUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          category,
          coordinates: {
            latitude: destination.latitude,
            longitude: destination.longitude,
          },
          radius: 5000,
          csrf_token: document.querySelector("#safety-csrf-token").value,
        }),
      });
    } else {
      const query = new URLSearchParams({
        category,
        lat: String(destination.latitude),
        lon: String(destination.longitude),
        radius: "5000",
      });
      response = await requestJson(`/api/nearby?${query}`);
    }
    const visibleCount = renderNearbyPlaces(response.places || []);
    const categoryLabel = category === "police" ? "police stations" : category;
    setStatus(
      status,
      visibleCount
        ? `${visibleCount} nearby place${visibleCount === 1 ? "" : "s"} found within 5 km, including labelled sample data.`
        : response.places.length
          ? "No mapped listings match the selected category filter."
          : `No named ${categoryLabel} were found within 5 km in the available OpenStreetMap data.`,
    );
  } catch (error) {
    setStatus(status, error.message || "Nearby places could not be loaded. Try again later.", true);
    console.error(error);
  } finally {
    updateNearbyButtons();
  }
}

async function loadCulturalEvents(nearbyOnly) {
  const status = document.querySelector("#nearby-status");
  const destination = mapState.locations.destination;
  if (nearbyOnly && !destination) {
    setStatus(status, "Choose a destination to find nearby cultural events.", true);
    return;
  }

  const query = new URLSearchParams();
  const category = document.querySelector("#event-category-filter")?.value;
  const search = document.querySelector("#event-search")?.value.trim();
  if (category) {
    query.set("category", category);
  }
  if (search) {
    query.set("q", search);
  }
  if (nearbyOnly && destination) {
    query.set("lat", String(destination.latitude));
    query.set("lon", String(destination.longitude));
    query.set("radius", "5000");
  }

  const categoryButtons = [...document.querySelectorAll("[data-nearby-category]")];
  categoryButtons.forEach((item) => { item.disabled = true; });
  mapState.lastNearbyCategory = "cultural-events";
  setStatus(
    status,
    nearbyOnly ? "Loading cultural event records near this destination…" : "Loading upcoming cultural event records…",
    false,
    true,
  );
  try {
    const response = await requestJson(`/api/cultural-events${query.size ? `?${query}` : ""}`);
    const events = response.events || [];
    renderCulturalEvents(events);
    const locationDescription = nearbyOnly ? " within 5 km" : "";
    setStatus(
      status,
      events.length
        ? `${events.length} synthetic demo event${events.length === 1 ? "" : "s"} — not confirmed public schedules${locationDescription}.`
        : `No cultural event demo records${locationDescription}.`,
    );
  } catch (error) {
    setStatus(status, error.message || "Verified cultural events could not be loaded.", true);
    console.error(error);
  } finally {
    updateNearbyButtons();
  }
}

function renderNearbyPlaces(places) {
  mapState.nearbyPlaces = places;
  const cuisineFilter = document.querySelector("#restaurant-cuisine-filter");
  if (cuisineFilter) {
    const cuisines = [...new Set(
      places.flatMap((place) => (place.cuisine || "").split(";").map((value) => value.trim()).filter(Boolean)),
    )].sort((first, second) => first.localeCompare(second));
    cuisineFilter.replaceChildren(new Option("All mapped cuisines", ""));
    cuisines.forEach((cuisine) => cuisineFilter.add(new Option(cuisine, cuisine)));
  }
  return renderFilteredNearbyPlaces();
}

function renderFilteredNearbyPlaces() {
  const list = document.querySelector("#nearby-results");
  if (!list) {
    return;
  }
  list.replaceChildren();
  mapState.nearbyMarkers?.clearLayers();
  const cuisine = document.querySelector("#restaurant-cuisine-filter")?.value || "";
  const stayType = document.querySelector("#stay-type-filter")?.value || "";
  const places = mapState.nearbyPlaces.filter((place) => {
    const matchesCuisine = !cuisine || (place.cuisine || "").split(";").some((item) => item.trim() === cuisine);
    const matchesStayType = !stayType
      || (stayType === "budget"
        ? place.budget_tagged
        : stayType === "other"
          ? !["Hotel", "Resort", "Homestay", "Guest house", "Hostel"].includes(place.place_type)
          : place.place_type === stayType);
    return matchesCuisine && matchesStayType;
  });
  const bounds = [];
  const selectedDestination = mapState.locations.destination;
  if (selectedDestination && places.length) {
    bounds.push([selectedDestination.latitude, selectedDestination.longitude]);
  }

  for (const place of places) {
    const item = document.createElement("article");
    item.className = "map-place-item";
    const title = document.createElement("strong");
    title.textContent = place.name;
    const metadata = document.createElement("div");
    metadata.className = "map-place-metadata";
    appendPlaceMetadata(metadata, place);
    if (place.image_url) {
      const figure = document.createElement("figure");
      const image = document.createElement("img");
      image.className = "map-place-image";
      image.src = place.image_url;
      image.alt = `${place.name} image from Wikimedia Commons`;
      image.loading = "lazy";
      figure.append(image);
      if (place.image_source_url) {
        const attribution = document.createElement("figcaption");
        const imageSource = document.createElement("a");
        imageSource.href = place.image_source_url;
        imageSource.target = "_blank";
        imageSource.rel = "noopener noreferrer";
        imageSource.textContent = "Wikimedia Commons · license";
        attribution.append(imageSource);
        figure.append(attribution);
      }
      item.append(figure);
    }
    const description = document.createElement("p");
    description.textContent = place.details || place.place_type || place.category;
    const source = document.createElement("a");
    source.href = place.source_url;
    source.target = "_blank";
    source.rel = "noopener noreferrer";
    source.textContent = place.is_synthetic
      ? "Synthetic sample record · not live availability"
      : "OpenStreetMap record";
    item.append(title, description, metadata);
    appendPlaceLinks(item, place);
    item.append(source);
    list.append(item);

    if (mapState.nearbyMarkers) {
      const marker = L.marker([place.latitude, place.longitude], {
        icon: L.divIcon({
          className: `route-pin ${place.category === "hospitals"
            ? "route-pin-hospital"
            : place.category === "police"
              ? "route-pin-police"
              : "route-pin-nearby"}`,
          iconSize: [12, 12],
          iconAnchor: [6, 6],
        }),
      });
      marker.bindPopup(createPlacePopup(place)).addTo(mapState.nearbyMarkers);
      bounds.push([place.latitude, place.longitude]);
    }
  }
  if (places.length && mapState.map) {
    mapState.map.fitBounds(bounds, { padding: [28, 28], maxZoom: 14 });
  }
  if (mapState.nearbyPlaces.length && !places.length) {
    setStatus(
      document.querySelector("#nearby-status"),
      "No mapped listings match the selected category filter.",
      true,
    );
  }
  return places.length;
}

function appendPlaceMetadata(container, place) {
  const details = [];
  if (Number.isFinite(place.distance_km)) {
    details.push(`${place.distance_km.toFixed(1)} km straight-line`);
  }
  if (place.cuisine) {
    details.push(`Cuisine: ${place.cuisine}`);
  }
  if (place.place_type) {
    details.push(place.place_type);
  }
  if (place.budget_tagged) {
    details.push("Explicit budget tag");
  }
  if (place.rating) {
    details.push(`Mapped rating: ${place.rating}`);
  }
  if (place.stars) {
    details.push(`Stars tag: ${place.stars}`);
  }
  if (place.price) {
    details.push(`${place.price_label || "Listed price"}: ${place.price}`);
  }
  for (const detail of details) {
    const pill = document.createElement("span");
    pill.textContent = detail;
    container.append(pill);
  }
}

function appendPlaceLinks(container, place) {
  for (const [url, label] of [
    [place.booking_url, "Booking page"],
    [place.website_url, "Website"],
  ]) {
    if (!url) {
      continue;
    }
    const link = document.createElement("a");
    link.href = url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.textContent = label;
    container.append(link);
  }
}

function createPlacePopup(place) {
  const popup = document.createElement("div");
  const title = document.createElement("strong");
  title.textContent = place.name;
  popup.append(title);
  return popup;
}

function renderCulturalEvents(events) {
  const list = document.querySelector("#nearby-results");
  list.replaceChildren();
  mapState.nearbyPlaces = [];
  mapState.nearbyMarkers?.clearLayers();
  const bounds = [];
  const selectedDestination = mapState.locations.destination;
  if (selectedDestination && events.length) {
    bounds.push([selectedDestination.latitude, selectedDestination.longitude]);
  }

  for (const event of events) {
    const item = document.createElement("article");
    item.className = "map-place-item cultural-event-card";
    const title = document.createElement("strong");
    title.textContent = event.name;
    const category = document.createElement("span");
    category.className = "event-category-pill";
    category.textContent = event.category_label;
    const dateLine = document.createElement("p");
    dateLine.textContent = event.is_synthetic
      ? `Illustrative date: ${formatEventDate(event.start_date, event.end_date)}`
      : `Verified date: ${formatEventDate(event.start_date, event.end_date)}`;
    if (event.is_synthetic) {
      dateLine.classList.add("event-synthetic-date");
    }
    const venue = document.createElement("p");
    venue.textContent = `${event.venue} · ${event.district}`;
    const description = document.createElement("p");
    description.textContent = event.description;
    const metadata = document.createElement("div");
    metadata.className = "map-place-metadata";
    if (Number.isFinite(event.distance_km)) {
      const distance = document.createElement("span");
      distance.textContent = `${event.distance_km.toFixed(1)} km straight-line`;
      metadata.append(distance);
    }
    const source = document.createElement("a");
    source.href = event.source_url;
    source.target = "_blank";
    source.rel = "noopener noreferrer";
    source.textContent = event.is_synthetic
      ? `SYNTHETIC DEMO · ${event.source_name} · ${event.verification_note}`
      : `${event.source_name} (${event.source_type}) · verified ${event.verified_on}`;
    item.append(title, category, dateLine, venue, description, metadata, source);
    list.append(item);

    if (window.L && mapState.nearbyMarkers) {
      const marker = L.marker([event.latitude, event.longitude], {
        icon: L.divIcon({
          className: "route-pin route-pin-event",
          iconSize: [14, 14],
          iconAnchor: [7, 7],
        }),
      });
      marker.bindPopup(createPlacePopup(event)).addTo(mapState.nearbyMarkers);
      bounds.push([event.latitude, event.longitude]);
    }
  }
  if (events.length && mapState.map) {
    mapState.map.fitBounds(bounds, { padding: [28, 28], maxZoom: 13 });
  }
}

function formatEventDate(startDate, endDate) {
  const options = { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" };
  const start = new Date(`${startDate}T00:00:00Z`).toLocaleDateString("en-IN", options);
  if (startDate === endDate) {
    return start;
  }
  const end = new Date(`${endDate}T00:00:00Z`).toLocaleDateString("en-IN", options);
  return `${start} – ${end}`;
}

function routeToPlace(place) {
  const origin = mapState.locations.destination || mapState.locations.source;
  const target = {
    label: place.venue || place.name,
    latitude: place.latitude,
    longitude: place.longitude,
    sourceUrl: place.source_url,
    destinationId: null,
  };
  if (!origin) {
    setResolvedLocation("destination", target);
    setStatus(
      document.querySelector("#route-status"),
      "Destination selected. Choose a starting point to calculate road directions.",
    );
    return;
  }
  setResolvedLocation("source", origin);
  setResolvedLocation("destination", target);
  calculateRoute();
}

function clearNearbyResults() {
  mapState.nearbyMarkers?.clearLayers();
  document.querySelector("#nearby-results")?.replaceChildren();
  mapState.nearbyPlaces = [];
  mapState.lastNearbyCategory = "";
  document.querySelectorAll("[data-nearby-category]").forEach((button) => {
    button.setAttribute("aria-pressed", "false");
  });
  const status = document.querySelector("#nearby-status");
  if (status) {
    status.textContent = "Choose a destination to search nearby.";
    status.classList.remove("is-error", "is-loading");
  }
}

function updateNearbyButtons() {
  const hasDestination = Boolean(mapState.locations.destination);
  document.querySelectorAll("[data-nearby-category]").forEach((button) => {
    button.disabled = !hasDestination
      && !(mapState.moduleCategory === "cultural-events"
        && button.dataset.nearbyCategory === "cultural-events");
  });
}

function invalidateRoute() {
  mapState.routes = [];
  mapState.routeLayers?.clearLayers();
  mapState.routeMarkers?.clearLayers();
  const results = document.querySelector("#route-results");
  if (results) {
    results.hidden = true;
  }
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, {
    ...options,
    headers: {
      Accept: "application/json",
      ...(options.headers || {}),
    },
  });
  let payload;
  try {
    payload = await response.json();
  } catch (error) {
    throw new Error("The server returned an unreadable response.");
  }
  if (!response.ok) {
    throw new Error(payload.error || `The request failed (${response.status}).`);
  }
  return payload;
}

function formatDistance(metres) {
  if (!Number.isFinite(metres)) {
    return "—";
  }
  return metres >= 1000 ? `${(metres / 1000).toFixed(1)} km` : `${Math.round(metres)} m`;
}

function formatDuration(seconds) {
  if (!Number.isFinite(seconds)) {
    return "—";
  }
  const minutes = Math.max(1, Math.round(seconds / 60));
  const hours = Math.floor(minutes / 60);
  const remainingMinutes = minutes % 60;
  return hours ? `${hours} hr ${remainingMinutes} min` : `${minutes} min`;
}

function setStatus(element, message, isError = false, isLoading = false) {
  if (!element) {
    return;
  }
  if (!element) {
    return;
  }
  element.textContent = message;
  element.classList.toggle("is-error", isError);
  element.classList.toggle("is-loading", isLoading);
}
