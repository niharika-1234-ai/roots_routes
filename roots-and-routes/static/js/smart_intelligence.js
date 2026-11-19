"use strict";

document.addEventListener("DOMContentLoaded", initializeSmartTripIntelligence);

function initializeSmartTripIntelligence() {
  const controls = document.querySelector("#intelligence-controls");
  if (!controls) {
    return;
  }

  const destinationSelect = document.querySelector("#intelligence-destination");
  const originSelect = document.querySelector("#intelligence-origin");
  let activeController = null;
  let requestVersion = 0;
  let budgetTimer = null;

  destinationSelect.addEventListener("change", loadDestination);
  originSelect.addEventListener("change", loadRouteAndCarbon);
  for (const selector of [
    "#intelligence-travellers",
    "#intelligence-travel-mode",
  ]) {
    document.querySelector(selector).addEventListener("change", loadRouteAndCarbon);
  }
  for (const selector of [
    "#intelligence-days",
    "#intelligence-travellers",
    "#intelligence-budget-limit",
    "#intelligence-travel-mode",
    "#intelligence-accommodation",
    "#intelligence-food",
  ]) {
    document.querySelector(selector).addEventListener("change", loadBudget);
    document.querySelector(selector).addEventListener("input", () => {
      window.clearTimeout(budgetTimer);
      budgetTimer = window.setTimeout(loadBudget, 350);
    });
  }

  loadDestination();

  function loadDestination() {
    if (activeController) {
      activeController.abort();
    }
    activeController = new AbortController();
    requestVersion += 1;
    const version = requestVersion;
    const signal = activeController.signal;
    const destinationOption = destinationSelect.selectedOptions[0];
    if (!destinationOption) {
      setOverallStatus("Choose a destination to load its intelligence.", true);
      return;
    }
    if (originSelect.value === destinationSelect.value) {
      const alternativeOrigin = Array.from(originSelect.options).find(
        (option) => option.value !== destinationSelect.value,
      );
      if (alternativeOrigin) {
        originSelect.value = alternativeOrigin.value;
      }
    }

    const coordinates = {
      lat: Number(destinationOption.dataset.latitude),
      lon: Number(destinationOption.dataset.longitude),
    };
    if (
      !Number.isFinite(coordinates.lat)
      || !Number.isFinite(coordinates.lon)
    ) {
      setOverallStatus("The selected destination has no usable catalogue coordinates.", true);
      return;
    }

    setOverallStatus(`Loading connected modules for ${destinationOption.textContent.trim()}…`);
    const results = {};
    const tasks = [
      loadSection("core", () => loadCore(destinationSelect.value, signal), renderCore, version, results),
      loadSection("attractions", () => loadNearby("attractions", coordinates, signal), (data) => renderPlaces("attractions", data), version, results),
      loadSection("restaurants", () => loadNearby("restaurants", coordinates, signal), (data) => renderPlaces("restaurants", data), version, results),
      loadSection("hotels", () => loadNearby("hotels", coordinates, signal), (data) => renderPlaces("hotels", data), version, results),
      loadSection("events", () => loadEvents(coordinates, signal), renderEvents, version, results),
      loadSection("weather", () => loadWeather(destinationSelect.value, signal), renderWeather, version, results),
      loadSection("budget", () => loadBudgetData(signal), renderBudget, version, results),
      loadSection("route", () => loadRouteAndCarbonData(signal), renderRouteAndCarbon, version, results),
      loadSection("safety", () => loadSafetyServices(coordinates, signal), renderSafetyServices, version, results),
    ];

    Promise.all(tasks).then(() => {
      if (version === requestVersion) {
        renderSummary(destinationOption.textContent.trim(), results);
        const failures = Object.values(results).filter((result) => result && result.error).length;
        setOverallStatus(
          failures
            ? `Destination brief loaded with ${failures} unavailable module${failures === 1 ? "" : "s"}.`
            : `Connected destination brief loaded for ${destinationOption.textContent.trim()}.`,
          failures > 0,
        );
      }
    });
  }

  async function loadSection(name, loader, renderer, version, results) {
    setModuleStatus(name, "Loading…");
    try {
      const data = await loader();
      if (version !== requestVersion) {
        return;
      }
      results[name] = data;
      renderer(data);
      setModuleStatus(name, data.status || "Loaded from the connected source.");
    } catch (error) {
      if (error.name === "AbortError" || version !== requestVersion) {
        return;
      }
      results[name] = { error: error.message || "This module is unavailable." };
      setModuleStatus(name, results[name].error, true);
      renderUnavailable(name);
    }
  }

  async function loadCore(destinationId, signal) {
    const endpoint = new URL(controls.dataset.coreEndpoint, window.location.href);
    endpoint.searchParams.set("destination_id", destinationId);
    return requestJson(endpoint, { signal });
  }

  async function loadNearby(category, coordinates, signal) {
    const endpoint = new URL(controls.dataset.nearbyEndpoint, window.location.href);
    endpoint.searchParams.set("category", category);
    endpoint.searchParams.set("lat", coordinates.lat);
    endpoint.searchParams.set("lon", coordinates.lon);
    endpoint.searchParams.set("radius", 5000);
    const payload = await requestJson(endpoint, { signal });
    return {
      items: payload.places,
      status: `${payload.places.length} mapped place${payload.places.length === 1 ? "" : "s"} · OpenStreetMap`,
    };
  }

  async function loadEvents(coordinates, signal) {
    const endpoint = new URL(controls.dataset.eventsEndpoint, window.location.href);
    endpoint.searchParams.set("lat", coordinates.lat);
    endpoint.searchParams.set("lon", coordinates.lon);
    endpoint.searchParams.set("radius", 10000);
    const payload = await requestJson(endpoint, { signal });
    return {
      items: payload.events,
      status: `${payload.events.length} verified upcoming event${payload.events.length === 1 ? "" : "s"} within 10 km`,
    };
  }

  async function loadWeather(destinationId, signal) {
    const endpoint = new URL(controls.dataset.weatherEndpoint, window.location.href);
    endpoint.searchParams.set("destination_id", destinationId);
    const payload = await requestJson(endpoint, { signal });
    return { ...payload, status: `Live data · ${payload.provider}` };
  }

  async function loadBudgetData(signal) {
    const body = {
      csrf_token: document.querySelector("#intelligence-csrf-token").value,
      budget_inr: Number(document.querySelector("#intelligence-budget-limit").value),
      days: Number(document.querySelector("#intelligence-days").value),
      travellers: Number(document.querySelector("#intelligence-travellers").value),
      travel_mode: document.querySelector("#intelligence-travel-mode").value,
      accommodation_preference: document.querySelector("#intelligence-accommodation").value,
      food_preference: document.querySelector("#intelligence-food").value,
      expense_overrides: {},
    };
    const payload = await requestJson(controls.dataset.budgetEndpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal,
    });
    return { ...payload, status: "Illustrative sample estimate · INR" };
  }

  async function loadRouteAndCarbonData(signal) {
    if (!originSelect.value || originSelect.value === destinationSelect.value) {
      throw new Error("Choose a route origin different from the destination.");
    }
    const budgetMode = document.querySelector("#intelligence-travel-mode").value;
    const mode = budgetMode === "private_car" ? "car" : budgetMode;
    const payload = await requestJson(controls.dataset.routeCarbonEndpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        csrf_token: document.querySelector("#intelligence-csrf-token").value,
        origin_id: originSelect.value,
        destination_id: destinationSelect.value,
        travellers: Number(document.querySelector("#intelligence-travellers").value),
        mode,
      }),
      signal,
    });
    return {
      ...payload,
    };
  }

  async function loadSafetyServices(coordinates, signal) {
    const results = await Promise.all(
      ["hospitals", "police"].map(async (category) => {
        const payload = await requestJson(controls.dataset.safetyEndpoint, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            csrf_token: document.querySelector("#intelligence-csrf-token").value,
            category,
            coordinates: {
              latitude: coordinates.lat,
              longitude: coordinates.lon,
            },
            radius: 5000,
          }),
          signal,
        });
        return { category, places: payload.places };
      }),
    );
    return {
      hospitals: results.find((result) => result.category === "hospitals").places,
      police: results.find((result) => result.category === "police").places,
      status: "Official emergency links and nearby OSM listings · catalogue point only",
    };
  }

  function loadBudget() {
    if (!activeController || activeController.signal.aborted) {
      return;
    }
    loadSection(
      "budget",
      () => loadBudgetData(activeController.signal),
      renderBudget,
      requestVersion,
      {},
    );
  }

  function loadRouteAndCarbon() {
    if (!activeController || activeController.signal.aborted) {
      return;
    }
    loadSection(
      "route",
      () => loadRouteAndCarbonData(activeController.signal),
      renderRouteAndCarbon,
      requestVersion,
      {},
    );
  }

  function renderCore(data) {
    const crowd = data.crowd;
    const crowdContainer = document.querySelector("#intelligence-crowd");
    crowdContainer.replaceChildren();
    appendText(crowdContainer, "strong", `${crowd.level} sample index: ${crowd.prediction_index}/100`);
    appendText(crowdContainer, "p", `${crowd.month_name} ${crowd.forecast_year} · not observed visitor counts`);
    appendText(crowdContainer, "p", crowd.sample_notice);

    const sustainability = data.sustainability;
    const sustainabilityContainer = document.querySelector("#intelligence-sustainability");
    sustainabilityContainer.replaceChildren();
    if (sustainability.score === null) {
      appendText(sustainabilityContainer, "p", sustainability.note);
    } else {
      appendText(sustainabilityContainer, "strong", `${sustainability.score}/100`);
      appendText(sustainabilityContainer, "p", sustainability.note);
      appendLink(sustainabilityContainer, "Score evidence", sustainability.source_url);
    }

    renderLinkedItems(
      "#intelligence-alternatives",
      data.hidden_alternatives,
      (item) => `${item.name} · ${item.district} · evidence rank ${item.ranking_score}/100`,
      data.hidden_alternatives_note,
    );
    document.querySelector("#intelligence-alternatives-status").textContent =
      `${data.hidden_alternatives.length} evidence-ranked alternative${data.hidden_alternatives.length === 1 ? "" : "s"}`;
  }

  function renderPlaces(moduleName, data) {
    renderLinkedItems(
      `#intelligence-${moduleName}`,
      data.items,
      (item) => {
        const attributes = [
          item.place_type,
          `${item.distance_km} km`,
          item.price ? `${item.price_label}: ${item.price}` : "",
          item.cuisine,
          item.rating ? `Rating: ${item.rating}` : "",
          item.stars ? `${item.stars} stars` : "",
        ].filter(Boolean);
        return `${item.name}${attributes.length ? ` · ${attributes.join(" · ")}` : ""}`;
      },
      `No mapped ${moduleName} are listed near this catalogue point.`,
    );
    document.querySelector(`#intelligence-${moduleName}-status`).textContent = data.status;
  }

  function renderEvents(data) {
    renderLinkedItems(
      "#intelligence-events",
      data.items,
      (item) => `${item.name} · ${item.category_label} · ${item.start_date} · ${item.venue}`,
      "No upcoming source-verified event is listed in the curated calendar.",
    );
  }

  function renderWeather(data) {
    const container = document.querySelector("#intelligence-weather");
    container.replaceChildren();
    const current = data.current;
    appendText(container, "strong", `${current.temperature_c} °C · ${current.condition}`);
    appendText(container, "p", `Next-period rain probability: ${current.rain_probability_next_period}%`);
    const updated = new Date(data.last_updated);
    appendText(
      container,
      "small",
      `Last updated: ${Number.isNaN(updated.getTime()) ? "time unavailable" : updated.toLocaleString()}`,
    );
    for (const recommendation of data.recommendations) {
      appendText(container, "p", recommendation, "intelligence-guidance");
    }
    appendLink(container, "Weather provider", "https://openweathermap.org/");
  }

  function renderBudget(data) {
    const container = document.querySelector("#intelligence-budget");
    container.replaceChildren();
    const list = document.createElement("ul");
    list.className = "intelligence-expense-list";
    for (const [category, expense] of Object.entries(data.expenses)) {
      const item = document.createElement("li");
      item.append(
        document.createTextNode(`${formatCategory(category)}: `),
        strongText(formatCurrency(expense.amount_inr)),
      );
      list.append(item);
    }
    container.append(list);
    appendText(container, "strong", `Total sample estimate: ${formatCurrency(data.total_estimate_inr)}`);
    appendText(container, "p", `Per person: ${formatCurrency(data.per_person_inr)} · Remaining budget: ${formatCurrency(data.remaining_budget_inr)}`);
    appendText(container, "small", data.sample_notice);
  }

  function renderRouteAndCarbon(data) {
    const routeContainer = document.querySelector("#intelligence-route");
    routeContainer.replaceChildren();
    for (const route of data.routes) {
      appendText(routeContainer, "p", `${route.label}: ${route.distance_km} km · about ${route.duration_minutes} minutes`);
    }
    appendText(routeContainer, "small", data.route_note);
    appendLink(routeContainer, "OSRM source", "https://project-osrm.org/");

    const carbonContainer = document.querySelector("#intelligence-carbon");
    carbonContainer.replaceChildren();
    appendText(carbonContainer, "strong", `${data.carbon.total_kg_co2e} kg CO₂e · ${data.carbon.mode.mode_label}`);
    appendText(carbonContainer, "p", `${data.carbon.per_person_kg_co2e} kg CO₂e per traveller · one way`);
    appendText(carbonContainer, "small", data.carbon.factor_basis_note);
    if (data.carbon.suggestions.length) {
      appendText(carbonContainer, "p", data.carbon.suggestions[0], "intelligence-guidance");
    }
  }

  function renderSafetyServices(data) {
    renderLinkedItems(
      "#intelligence-hospitals",
      data.hospitals,
      (item) => `${item.name} · ${item.distance_km} km`,
      "No named hospital was returned by OpenStreetMap for this catalogue point.",
    );
    renderLinkedItems(
      "#intelligence-police",
      data.police,
      (item) => `${item.name} · ${item.distance_km} km`,
      "No named police station was returned by OpenStreetMap for this catalogue point.",
    );
    document.querySelector("#intelligence-safety-status").textContent = data.status;
  }

  function renderSummary(destinationLabel, results) {
    const core = results.core && !results.core.error ? results.core : null;
    const crowd = core?.crowd;
    const sustainability = core?.sustainability;
    const bulletPoints = [
      `${destinationLabel} is in the Jharkhand destination catalogue; services are looked up around its listed coordinates.`,
    ];
    if (results.attractions && !results.attractions.error) {
      bulletPoints.push(`${results.attractions.items.length} mapped attractions were returned.`);
    }
    if (results.restaurants && !results.restaurants.error) {
      bulletPoints.push(`${results.restaurants.items.length} mapped food places were returned.`);
    }
    if (results.hotels && !results.hotels.error) {
      bulletPoints.push(`${results.hotels.items.length} mapped stays were returned.`);
    }
    if (results.weather?.error) {
      bulletPoints.push("Live weather is unavailable; no sample weather is substituted.");
    } else if (results.weather) {
      bulletPoints.push(`Live weather is available from ${results.weather.provider}; check the current advisory before travel.`);
      if (results.weather.recommendations.length) {
        bulletPoints.push(`Weather guidance: ${results.weather.recommendations[0]}`);
      }
    }
    if (results.events && !results.events.error) {
      bulletPoints.push(`${results.events.items.length} verified upcoming cultural event${results.events.items.length === 1 ? "" : "s"} were found within 10 km.`);
    }
    if (results.budget && !results.budget.error) {
      bulletPoints.push(
        `Illustrative trip estimate: ${formatCurrency(results.budget.total_estimate_inr)} total, with ${formatCurrency(results.budget.remaining_budget_inr)} remaining from the selected sample budget.`,
      );
    }
    if (results.safety && !results.safety.error) {
      bulletPoints.push(
        `Mapped nearby services returned: ${results.safety.hospitals.length} hospitals and ${results.safety.police.length} police listings; confirm details before relying on them.`,
      );
    }
    if (results.route?.error) {
      bulletPoints.push("Road route and carbon estimate are unavailable until a valid OSRM route is returned.");
    } else if (results.route) {
      bulletPoints.push("The one-way road route and carbon estimate use OSRM distance and sourced operational factors.");
    }
    if (crowd) {
      bulletPoints.push(crowd.sample_notice);
    } else {
      bulletPoints.push("The labelled synthetic crowd sample is unavailable for this destination.");
    }
    if (sustainability?.status === "not_assessed") {
      bulletPoints.push("No source-backed sustainability score is available for this destination.");
    }
    if (sustainability?.status === "sourced") {
      bulletPoints.push(`The catalogue lists a source-backed sustainability score of ${sustainability.score}/100.`);
    }
    if (core && core.hidden_alternatives.length === 0) {
      bulletPoints.push(core.hidden_alternatives_note);
    }
    bulletPoints.push("This planning brief does not confirm opening hours, service availability, access, safety, or budget fit.");
    const summary = document.querySelector("#intelligence-summary");
    summary.replaceChildren();
    const list = document.createElement("ul");
    for (const point of bulletPoints) {
      appendText(list, "li", point);
    }
    summary.append(list);
  }

  function renderUnavailable(moduleName) {
    if (moduleName === "safety") {
      document.querySelector("#intelligence-safety-status").textContent =
        "Nearby mapped services are unavailable. Official emergency links remain listed above.";
      return;
    }
    const container = document.querySelector(`#intelligence-${moduleName}`);
    if (container) {
      container.replaceChildren();
      appendText(container, "p", "No live or sample data is shown for this module.");
    }
  }

  function renderLinkedItems(selector, items, describe, emptyMessage) {
    const container = document.querySelector(selector);
    container.replaceChildren();
    if (!items.length) {
      appendText(container, "p", emptyMessage);
      return;
    }
    const list = document.createElement("ul");
    list.className = "intelligence-place-list";
    for (const item of items) {
      const row = document.createElement("li");
      const source = item.source_url;
      if (source) {
        appendLink(row, describe(item), source);
      } else {
        appendText(row, "span", describe(item));
      }
      if (item.website_url) {
        appendLink(row, "Website", item.website_url);
      }
      list.append(row);
    }
    container.append(list);
  }

  function appendText(parent, tagName, text, className = "") {
    const element = document.createElement(tagName);
    element.textContent = text;
    if (className) {
      element.className = className;
    }
    parent.append(element);
    return element;
  }

  function appendLink(parent, text, href) {
    const link = document.createElement("a");
    link.textContent = text;
    link.href = href;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    parent.append(link);
    return link;
  }

  function strongText(text) {
    const strong = document.createElement("strong");
    strong.textContent = text;
    return strong;
  }

  function formatCurrency(amount) {
    return `₹${Number(amount).toLocaleString("en-IN")}`;
  }

  function formatCategory(category) {
    return category
      .split("_")
      .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
      .join(" ");
  }

  function setModuleStatus(name, message, isError = false) {
    const element = document.querySelector(`#intelligence-${name}-status`);
    if (!element) {
      return;
    }
    element.textContent = message;
    element.classList.toggle("is-error", isError);
  }

  function setOverallStatus(message, isError = false) {
    const element = document.querySelector("#intelligence-load-status");
    element.textContent = message;
    element.classList.toggle("is-error", isError);
  }

  async function requestJson(url, options = {}) {
    const response = await fetch(url, {
      headers: { Accept: "application/json", ...(options.headers || {}) },
      ...options,
    });
    let payload;
    try {
      payload = await response.json();
    } catch {
      throw new Error("A connected travel service returned an unreadable response.");
    }
    if (!response.ok) {
      throw new Error(payload.error || "This travel service is temporarily unavailable.");
    }
    return payload;
  }
}
