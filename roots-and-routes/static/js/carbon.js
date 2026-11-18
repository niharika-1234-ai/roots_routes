"use strict";

const carbonState = {
  destinationsByName: new Map(),
  locations: { source: null, destination: null },
  chart: null,
};

document.addEventListener("DOMContentLoaded", initializeCarbonWorkspace);

function initializeCarbonWorkspace() {
  const form = document.querySelector("#carbon-form");
  if (!form) {
    return;
  }

  for (const role of ["source", "destination"]) {
    const input = document.querySelector(`#carbon-${role}`);
    input.addEventListener("input", () => handleCarbonLocationInput(role));
    input.addEventListener("change", () => resolveCarbonCatalogueInput(role));
    document
      .querySelector(`[data-carbon-geocode="${role}"]`)
      .addEventListener("click", () => searchCarbonLocation(role));
  }
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    calculateCarbonEstimate(form);
  });
  document
    .querySelector("#carbon-print-report")
    .addEventListener("click", () => {
      document.body.classList.add("carbon-print-mode");
      window.print();
      document.body.classList.remove("carbon-print-mode");
    });

  loadCarbonDestinations(form.dataset.destinationsUrl);
}

async function loadCarbonDestinations(url) {
  const datalist = document.querySelector("#carbon-destination-options");
  try {
    const destinations = await requestJson(url);
    datalist.replaceChildren();
    for (const destination of destinations) {
      carbonState.destinationsByName.set(
        destination.name.trim().toLocaleLowerCase(),
        destination,
      );
      datalist.append(new Option(destination.name));
    }
    resolveCarbonCatalogueInput("source");
    resolveCarbonCatalogueInput("destination");
  } catch (error) {
    setCarbonStatus(
      `The local destination list could not be loaded. You can still search locations or enter a manual distance. ${error.message}`,
      true,
    );
    console.error(error);
  }
}

function handleCarbonLocationInput(role) {
  const input = document.querySelector(`#carbon-${role}`);
  const results = document.querySelector(`#carbon-location-results-${role}`);
  results.replaceChildren();
  results.hidden = true;
  const current = carbonState.locations[role];
  if (current && current.label !== input.value.trim()) {
    carbonState.locations[role] = null;
  }
}

function resolveCarbonCatalogueInput(role) {
  const input = document.querySelector(`#carbon-${role}`);
  const label = input.value.trim();
  const destination = carbonState.destinationsByName.get(label.toLocaleLowerCase());
  if (destination) {
    carbonState.locations[role] = {
      label: destination.name,
      latitude: destination.latitude,
      longitude: destination.longitude,
      coordinateNote: destination.coordinates_note,
    };
  } else if (carbonState.locations[role]?.label !== label) {
    carbonState.locations[role] = null;
  }
}

async function searchCarbonLocation(role) {
  const form = document.querySelector("#carbon-form");
  const input = document.querySelector(`#carbon-${role}`);
  const resultsContainer = document.querySelector(`#carbon-location-results-${role}`);
  const button = document.querySelector(`[data-carbon-geocode="${role}"]`);
  const query = input.value.trim();
  if (query.length < 3) {
    setCarbonStatus("Enter at least three characters before searching.", true);
    input.focus();
    return;
  }

  button.disabled = true;
  setCarbonStatus(`Searching for ${role} locations…`);
  resultsContainer.replaceChildren();
  resultsContainer.hidden = true;
  try {
    const response = await requestJson(
      `${form.dataset.geocodeUrl}?q=${encodeURIComponent(query)}`,
    );
    if (!Array.isArray(response.results) || response.results.length === 0) {
      setCarbonStatus("No matching locations were returned. Try a more specific search.", true);
      return;
    }
    for (const result of response.results) {
      const option = document.createElement("button");
      option.type = "button";
      option.setAttribute("role", "option");
      option.className = "carbon-location-result";
      option.textContent = result.label;
      option.addEventListener("click", () => {
        const selectedLabel = result.label.slice(0, 160);
        input.value = selectedLabel;
        carbonState.locations[role] = {
          label: selectedLabel,
          latitude: result.latitude,
          longitude: result.longitude,
          coordinateNote: "",
        };
        resultsContainer.replaceChildren();
        resultsContainer.hidden = true;
        setCarbonStatus(`${role === "source" ? "Starting place" : "Destination"} resolved.`);
      });
      resultsContainer.append(option);
    }
    resultsContainer.hidden = false;
    setCarbonStatus("Choose the matching location from the search results.");
  } catch (error) {
    setCarbonStatus(error.message || "Location search is temporarily unavailable.", true);
  } finally {
    button.disabled = false;
  }
}

async function calculateCarbonEstimate(form) {
  const source = document.querySelector("#carbon-source").value.trim();
  const destination = document.querySelector("#carbon-destination").value.trim();
  const mode = document.querySelector("#carbon-mode").value;
  const travellers = Number(document.querySelector("#carbon-travellers").value);
  const distanceInput = document.querySelector("#carbon-distance");
  const manualDistance = distanceInput.value.trim()
    ? Number(distanceInput.value)
    : null;
  const submitButton = form.querySelector('button[type="submit"]');

  if (!source || !destination) {
    setCarbonStatus("Enter both a starting place and destination.", true);
    return;
  }
  if (!Number.isInteger(travellers) || travellers < 1 || travellers > 1000) {
    setCarbonStatus("Enter a whole number of travellers from 1 to 1000.", true);
    return;
  }
  if (
    manualDistance !== null
    && (!Number.isFinite(manualDistance) || manualDistance <= 0 || manualDistance > 50000)
  ) {
    setCarbonStatus("Manual distance must be greater than 0 and no more than 50,000 km.", true);
    return;
  }

  resolveCarbonCatalogueInput("source");
  resolveCarbonCatalogueInput("destination");
  const sourceLocation = carbonState.locations.source;
  const destinationLocation = carbonState.locations.destination;
  const body = {
    csrf_token: document.querySelector("#carbon-csrf-token").value,
    source,
    destination,
    mode,
    travellers,
    manual_distance_km: manualDistance,
    source_coordinates: sourceLocation && destinationLocation
      ? {
          latitude: sourceLocation.latitude,
          longitude: sourceLocation.longitude,
        }
      : null,
    destination_coordinates: sourceLocation && destinationLocation
      ? {
          latitude: destinationLocation.latitude,
          longitude: destinationLocation.longitude,
        }
      : null,
  };

  document.querySelector("#carbon-report").hidden = true;
  submitButton.disabled = true;
  setCarbonStatus(
    sourceLocation && destinationLocation
      ? "Calculating an OSRM road distance and comparing emissions…"
      : "Calculating from your manually entered distance…",
  );
  try {
    const estimate = await requestJson(form.dataset.endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    renderCarbonEstimate(estimate);
    const chartReady = renderCarbonChart(estimate.comparisons);
    setCarbonStatus(
      chartReady
        ? "Estimate complete. Review the factor sources and distance notes below."
        : "Estimate complete. The comparison table is available, but the chart library did not load.",
        false,
    );
  } catch (error) {
    setCarbonStatus(error.message || "The estimate could not be calculated.", true);
  } finally {
    submitButton.disabled = false;
  }
}

function renderCarbonEstimate(estimate) {
  const report = document.querySelector("#carbon-report");
  document.querySelector("#carbon-trip-title").textContent =
    `${estimate.source} → ${estimate.destination} · ${estimate.travellers} traveller${estimate.travellers === 1 ? "" : "s"}`;
  document.querySelector("#carbon-total-emissions").textContent =
    `${formatKilograms(estimate.total_kg_co2e)} kg`;
  document.querySelector("#carbon-person-emissions").textContent =
    `${formatKilograms(estimate.per_person_kg_co2e)} kg`;
  document.querySelector("#carbon-distance-result").textContent =
    `${formatDistance(estimate.distance_km)} km`;
  document.querySelector("#carbon-distance-source").textContent =
    estimate.distance_source === "osrm" ? "OSRM road network" : "User-entered distance";
  const approximateCoordinateNotes = ["source", "destination"]
    .map((role) => carbonState.locations[role]?.coordinateNote)
    .filter(Boolean);
  const coordinateNote = approximateCoordinateNotes.length
    ? ` Catalogue coordinate note: ${approximateCoordinateNotes.join(" ")}`
    : "";
  document.querySelector("#carbon-route-note").textContent =
    `${estimate.distance_note}${coordinateNote}`;
  document.querySelector("#carbon-method-note").textContent =
    `${estimate.factor_basis_note} Default car, bus, and rail factors are UK reporting proxies, not India-specific measurements. The estimate is one way; comparison uses the same distance for every mode.`;

  renderCarbonSuggestions(estimate.suggestions);
  renderCarbonComparisonRows(estimate.comparisons);
  report.hidden = false;
}

function renderCarbonSuggestions(suggestions) {
  const list = document.querySelector("#carbon-suggestions");
  list.replaceChildren();
  for (const suggestion of suggestions) {
    const item = document.createElement("li");
    item.textContent = suggestion;
    list.append(item);
  }
}

function renderCarbonComparisonRows(comparisons) {
  const body = document.querySelector("#carbon-comparison-rows");
  body.replaceChildren();
  for (const comparison of comparisons) {
    const row = document.createElement("tr");
    if (comparison.is_selected) {
      row.className = "carbon-selected-row";
    }

    const modeCell = document.createElement("th");
    modeCell.scope = "row";
    modeCell.textContent = comparison.is_selected
      ? `${comparison.mode_label} · selected`
      : comparison.mode_label;
    const factorCell = document.createElement("td");
    factorCell.textContent =
      `${formatFactor(comparison.kg_co2e_per_unit)} kg CO₂e / ${comparison.unit}`;
    const totalCell = document.createElement("td");
    totalCell.textContent = `${formatKilograms(comparison.total_kg_co2e)} kg`;
    const perPersonCell = document.createElement("td");
    perPersonCell.textContent = `${formatKilograms(comparison.per_person_kg_co2e)} kg`;
    const sourceCell = document.createElement("td");
    sourceCell.append(document.createTextNode(comparison.source_name));
    if (comparison.factor_year) {
      sourceCell.append(document.createTextNode(` · ${comparison.factor_year}`));
    }
    if (comparison.source_url) {
      sourceCell.append(document.createTextNode(" "));
      sourceCell.append(createSourceLink(comparison.source_url, "Source"));
    } else {
      sourceCell.append(document.createTextNode(" · boundary assumption"));
    }
    if (comparison.document_url) {
      sourceCell.append(document.createTextNode(" "));
      sourceCell.append(createSourceLink(comparison.document_url, "Workbook"));
    }

    row.append(modeCell, factorCell, totalCell, perPersonCell, sourceCell);
    body.append(row);
  }
}

function createSourceLink(url, label) {
  const link = document.createElement("a");
  link.href = url;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  link.textContent = label;
  return link;
}

function renderCarbonChart(comparisons) {
  const canvas = document.querySelector("#carbon-comparison-chart");
  if (!canvas || !window.Chart) {
    return false;
  }
  if (carbonState.chart) {
    carbonState.chart.destroy();
  }
  carbonState.chart = new Chart(canvas, {
    type: "bar",
    data: {
      labels: comparisons.map((item) => item.mode_label),
      datasets: [{
        label: "Total operational emissions (kg CO₂e)",
        data: comparisons.map((item) => item.total_kg_co2e),
        backgroundColor: comparisons.map((item) =>
          item.is_selected ? "#276445" : "#b7d5bc"),
        borderRadius: 7,
        maxBarThickness: 42,
      }],
    },
    options: {
      indexAxis: "y",
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: (context) => `${formatKilograms(context.parsed.x)} kg CO₂e`,
          },
        },
      },
      scales: {
        x: {
          beginAtZero: true,
          grid: { color: "#edf0e9" },
          ticks: { color: "#7a887c", font: { size: 10 } },
          title: {
            display: true,
            text: "Estimated total for all travellers (kg CO₂e)",
            color: "#758477",
            font: { size: 10 },
          },
          border: { display: false },
        },
        y: {
          grid: { display: false },
          ticks: { color: "#617065", font: { size: 11 } },
          border: { display: false },
        },
      },
    },
  });
  return true;
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, {
    ...options,
    headers: { Accept: "application/json", ...(options.headers || {}) },
  });
  let payload;
  try {
    payload = await response.json();
  } catch {
    throw new Error("The server returned an unreadable response.");
  }
  if (!response.ok) {
    throw new Error(payload.error || "The request could not be completed.");
  }
  return payload;
}

function setCarbonStatus(message, isError = false) {
  const status = document.querySelector("#carbon-status");
  if (!status) {
    return;
  }
  status.textContent = message;
  status.classList.toggle("is-error", isError);
}

function formatKilograms(value) {
  return Number(value).toLocaleString(undefined, {
    minimumFractionDigits: 3,
    maximumFractionDigits: 4,
  });
}

function formatFactor(value) {
  return Number(value) === 0 ? "0" : Number(value).toFixed(5);
}

function formatDistance(value) {
  return Number(value).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}
