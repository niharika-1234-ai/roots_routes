"use strict";

let latestDraft = null;

document.addEventListener("DOMContentLoaded", initializeTripPlanner);

function initializeTripPlanner() {
  const form = document.querySelector("#planner-form");
  if (!form) {
    return;
  }

  const destinationInputs = Array.from(
    form.querySelectorAll('input[name="destination_ids"]'),
  );
  applyBudgetHandoff(form, destinationInputs);
  document.querySelector("#planner-save-button").addEventListener("click", async () => {
    if (!latestDraft) {
      return;
    }
    await savePlannerItinerary(form, destinationInputs, latestDraft);
  });
  destinationInputs.forEach((input) => {
    input.addEventListener("change", () => {
      const selected = destinationInputs.filter((item) => item.checked);
      if (selected.length > 5) {
        input.checked = false;
        setPlannerStatus("Choose no more than five destinations.", true);
      }
    });
  });
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    generatePlannerItinerary(form);
  });
}

function applyBudgetHandoff(form, destinationInputs) {
  let rawDraft;
  try {
    rawDraft = window.sessionStorage.getItem("rootsRoutesPlannerDraft");
    window.sessionStorage.removeItem("rootsRoutesPlannerDraft");
  } catch (error) {
    setPlannerStatus("The current tab could not read the budget handoff. Enter your trip details manually.", true);
    console.error(error);
    return;
  }
  if (!rawDraft) {
    return;
  }

  let draft;
  try {
    draft = JSON.parse(rawDraft);
  } catch {
    setPlannerStatus("The budget handoff was invalid. Enter your trip details manually.", true);
    return;
  }
  if (!draft || typeof draft !== "object" || Array.isArray(draft)) {
    setPlannerStatus("The budget handoff was invalid. Enter your trip details manually.", true);
    return;
  }

  for (const [field, selector] of [
    ["budget_inr", "#planner-budget-input"],
    ["days", "#planner-days-input"],
    ["travellers", "#planner-travellers-input"],
  ]) {
    const input = document.querySelector(selector);
    const value = draft[field];
    if (
      Number.isInteger(value)
      && value >= Number(input.min)
      && value <= Number(input.max)
    ) {
      input.value = String(value);
    }
  }

  for (const [field, selector] of [
    ["accommodation_preference", "#planner-accommodation-input"],
    ["food_preference", "#planner-food-input"],
  ]) {
    const input = document.querySelector(selector);
    if (
      typeof draft[field] === "string"
      && Array.from(input.options, (option) => option.value).includes(draft[field])
    ) {
      input.value = draft[field];
    }
  }

  const allowedCategories = new Set([
    "transportation",
    "accommodation",
    "food",
    "activities",
    "other",
  ]);
  const overrides = {};
  if (draft.expense_overrides && typeof draft.expense_overrides === "object") {
    Object.entries(draft.expense_overrides).forEach(([category, amount]) => {
      if (
        allowedCategories.has(category)
        && Number.isInteger(amount)
        && amount >= 0
        && amount <= 100000000
      ) {
        overrides[category] = amount;
      }
    });
  }
  document.querySelector("#planner-expense-overrides").value =
    JSON.stringify(overrides);

  const allowedDestinationIds = new Set(
    destinationInputs.map((input) => input.value),
  );
  const selectedIds = Array.isArray(draft.destination_ids)
    ? draft.destination_ids.filter((id) => (
      typeof id === "string" && allowedDestinationIds.has(id)
    )).slice(0, 5)
    : [];
  destinationInputs.forEach((input) => {
    input.checked = selectedIds.includes(input.value);
  });
}

async function generatePlannerItinerary(form) {
  const status = document.querySelector("#planner-status");
  const submitButton = form.querySelector('button[type="submit"]');
  const submitLabel = document.querySelector("#planner-submit-label");
  const selectedDestinations = Array.from(
    form.querySelectorAll('input[name="destination_ids"]:checked'),
    (input) => input.value,
  );
  if (selectedDestinations.length > 5) {
    setPlannerStatus("Choose no more than five destinations.", true);
    return;
  }

  let expenseOverrides;
  try {
    expenseOverrides = JSON.parse(
      document.querySelector("#planner-expense-overrides").value || "{}",
    );
  } catch {
    setPlannerStatus("Budget calculator details are invalid. Return to the calculator and try again.", true);
    return;
  }

  const payload = {
    csrf_token: document.querySelector("#planner-csrf-token").value,
    budget_inr: Number(document.querySelector("#planner-budget-input").value),
    days: Number(document.querySelector("#planner-days-input").value),
    travellers: Number(document.querySelector("#planner-travellers-input").value),
    travel_mode: "bus",
    accommodation_preference: document.querySelector("#planner-accommodation-input").value,
    food_preference: document.querySelector("#planner-food-input").value,
    expense_overrides: expenseOverrides,
    destination_ids: selectedDestinations,
  };

  document.querySelector("#planner-result").hidden = true;
  submitButton.disabled = true;
  submitLabel.textContent = "Generating";
  setPlannerStatus("Building a catalogue-grounded itinerary draft…");
  try {
    const response = await fetch(form.dataset.endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const result = await response.json();
    if (!response.ok) {
      throw new Error(result.error || "The itinerary could not be generated.");
    }

    renderPlannerResult(result);
    latestDraft = result;
    const saveControls = document.querySelector("#planner-save-controls");
    const selectedNames = Array.from(
      form.querySelectorAll('input[name="destination_ids"]:checked'),
      (input) => input.parentElement.textContent.trim().split(/\s+/)[0],
    );
    document.querySelector("#planner-save-title").value =
      selectedNames.length ? `${selectedNames[0]} itinerary` : `${payload.days}-day Jharkhand trip`;
    document.querySelector("#planner-save-status").textContent = "";
    saveControls.hidden = false;
    status.textContent = result.itinerary.notice || "";
    status.classList.toggle("is-error", false);
  } catch (error) {
    setPlannerStatus(
      error instanceof Error ? error.message : "The itinerary could not be generated.",
      true,
    );
  } finally {
    submitButton.disabled = false;
    submitLabel.textContent = "Generate itinerary draft";
  }
}

async function savePlannerItinerary(form, destinationInputs, result) {
  const button = document.querySelector("#planner-save-button");
  const status = document.querySelector("#planner-save-status");
  const title = document.querySelector("#planner-save-title").value.trim();
  if (!title) {
    status.textContent = "Enter a name for this itinerary.";
    status.classList.add("is-error");
    return;
  }
  button.disabled = true;
  status.classList.remove("is-error");
  status.textContent = "Saving itinerary…";
  try {
    const response = await fetch(form.dataset.saveEndpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        csrf_token: document.querySelector("#planner-csrf-token").value,
        title,
        destination_ids: destinationInputs
          .filter((input) => input.checked)
          .map((input) => input.value),
        itinerary: result.itinerary,
        budget: result.budget,
      }),
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || "The itinerary could not be saved.");
    }
    status.textContent = "Itinerary saved. Open My Itineraries to review or delete it.";
    document.querySelector("#planner-saved-itineraries-link").hidden = false;
  } catch (error) {
    status.textContent =
      error instanceof Error ? error.message : "The itinerary could not be saved.";
    status.classList.add("is-error");
  } finally {
    button.disabled = false;
  }
}

function renderPlannerResult(result) {
  const itinerary = result.itinerary;
  const estimate = result.budget;
  const formatCurrency = (amount) => `₹${Number(amount).toLocaleString("en-IN", {
    maximumFractionDigits: 2,
  })}`;
  const remaining = estimate.remaining_budget_inr;
  const budgetLine = estimate.over_budget
    ? `The estimate is over the entered budget by ${formatCurrency(Math.abs(remaining))}.`
    : `${formatCurrency(remaining)} remains in the sample estimate.`;
  const categoryLines = Object.entries(estimate.expenses).map(([category, item]) => (
    `${category.replaceAll("_", " ")} ${formatCurrency(item.amount_inr)}`
  ));
  const preferences = estimate.inputs;
  const preferenceLine = [
    `stay: ${preferences.accommodation_preference}`,
    `food: ${preferences.food_preference}`,
  ].join(" · ");

  document.querySelector("#planner-budget-summary").textContent =
    `Illustrative estimate: ${formatCurrency(estimate.total_estimate_inr)} total ` +
    `(${formatCurrency(estimate.per_person_inr)} per person) for ` +
    `${estimate.inputs.travellers} travellers. ${preferenceLine}. ${budgetLine} ` +
    `Categories: ${categoryLines.join(" · ")}. ${estimate.sample_notice}`;
  document.querySelector("#planner-result-mode").textContent =
    itinerary.mode === "ai"
      ? "AI-assisted draft from listed destination records"
      : "Grounded local draft; no AI response was used";
  document.querySelector("#planner-answer").textContent = itinerary.answer;

  const sources = document.querySelector("#planner-sources");
  sources.replaceChildren();
  const safeSources = Array.isArray(itinerary.sources)
    ? itinerary.sources.filter((source) => {
      if (!source || typeof source.label !== "string" || typeof source.url !== "string") {
        return false;
      }
      try {
        return new URL(source.url).protocol === "https:";
      } catch {
        return false;
      }
    })
    : [];
  if (safeSources.length) {
    const label = document.createElement("span");
    label.textContent = "Destination sources";
    sources.append(label);
    safeSources.forEach((source) => {
      const link = document.createElement("a");
      link.href = source.url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = source.label;
      sources.append(link);
    });
  }
  document.querySelector("#planner-result").hidden = false;
}

function setPlannerStatus(message, isError = false) {
  const status = document.querySelector("#planner-status");
  status.textContent = message;
  status.classList.toggle("is-error", isError);
}
