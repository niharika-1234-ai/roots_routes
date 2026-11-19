"use strict";

document.addEventListener("DOMContentLoaded", initializeWeatherWorkspace);

function initializeWeatherWorkspace() {
  const form = document.querySelector("#weather-form");
  if (!form) {
    return;
  }

  const destinationSelect = document.querySelector("#weather-destination");
  const loadButton = document.querySelector("#weather-load");
  const status = document.querySelector("#weather-status");
  const results = document.querySelector("#weather-results");

  destinationSelect.addEventListener("change", () => {
    results.hidden = true;
    status.textContent = "Destination changed. Request its live weather to see current conditions.";
    status.classList.remove("is-error", "is-loading");
  });
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    loadDestinationWeather();
  });

  async function loadDestinationWeather() {
    results.hidden = true;
    loadButton.disabled = true;
    loadButton.textContent = "Loading live weather…";
    status.textContent = "Requesting current conditions and forecast…";
    status.classList.remove("is-error");
    status.classList.add("is-loading");

    try {
      const endpoint = new URL(form.dataset.endpoint, window.location.href);
      endpoint.searchParams.set("destination_id", destinationSelect.value);
      const response = await fetch(endpoint, {
        headers: { Accept: "application/json" },
      });
      let payload;
      try {
        payload = await response.json();
      } catch {
        throw new Error("The weather service returned an unreadable response.");
      }
      if (!response.ok) {
        throw new Error(payload.error || "Live weather is unavailable.");
      }
      renderWeather(payload);
      results.hidden = false;
      status.textContent = `Live weather loaded for ${payload.destination.name}.`;
    } catch (error) {
      status.textContent = error.message || "Live weather is unavailable. Try again later.";
      status.classList.add("is-error");
    } finally {
      loadButton.disabled = false;
      loadButton.textContent = "Refresh live weather";
      status.classList.remove("is-loading");
    }
  }
}

function renderWeather(weather) {
  const { destination, current } = weather;
  document.querySelector("#weather-destination-name").textContent =
    `${destination.name} · ${destination.district}`;
  document.querySelector("#weather-temperature").textContent =
    `${Number(current.temperature_c).toFixed(1)} °C`;
  document.querySelector("#weather-condition").textContent = current.condition;
  document.querySelector("#weather-rain-probability").textContent =
    `${Math.round(current.rain_probability_next_period)}%`;

  const updatedTime = document.querySelector("#weather-updated-time");
  const updatedDate = new Date(weather.last_updated);
  updatedTime.dateTime = weather.last_updated;
  updatedTime.textContent = Number.isNaN(updatedDate.getTime())
    ? "time unavailable"
    : updatedDate.toLocaleString();

  renderForecast(weather.forecast);
  renderRecommendations(weather.recommendations);
}

function renderForecast(forecast) {
  const container = document.querySelector("#weather-forecast");
  container.replaceChildren();

  for (const day of forecast) {
    const card = document.createElement("article");
    card.className = "weather-forecast-card";
    const date = document.createElement("h4");
    date.textContent = formatForecastDate(day.date);
    const condition = document.createElement("p");
    condition.textContent = day.condition;
    const temperatures = document.createElement("strong");
    temperatures.textContent =
      `${Number(day.temperature_min_c).toFixed(1)}° / ${Number(day.temperature_max_c).toFixed(1)}°C`;
    const rain = document.createElement("small");
    rain.textContent = `Peak 3-hour rain chance: ${Math.round(day.rain_probability)}%`;
    card.append(date, condition, temperatures, rain);
    container.append(card);
  }
}

function renderRecommendations(recommendations) {
  const list = document.querySelector("#weather-recommendations");
  list.replaceChildren();

  for (const recommendation of recommendations) {
    const item = document.createElement("li");
    item.textContent = recommendation;
    list.append(item);
  }
}

function formatForecastDate(value) {
  const date = new Date(`${value}T12:00:00`);
  if (Number.isNaN(date.getTime())) {
    return "Forecast date unavailable";
  }
  return date.toLocaleDateString("en-IN", {
    weekday: "short",
    day: "numeric",
    month: "short",
  });
}
