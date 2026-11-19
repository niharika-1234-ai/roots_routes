"use strict";

const budgetCategories = [
  ["transportation", "Transportation"],
  ["accommodation", "Accommodation"],
  ["food", "Food"],
  ["activities", "Activities"],
  ["other", "Other expenses"],
];

const budgetState = {
  expenseOverrides: {},
  estimate: null,
  requestNumber: 0,
  debounceTimer: null,
};

document.addEventListener("DOMContentLoaded", initializeBudgetCalculator);

function initializeBudgetCalculator() {
  const form = document.querySelector("#budget-form");
  if (!form) {
    return;
  }

  form.addEventListener("input", (event) => {
    if (event.target.matches(".budget-expense-input")) {
      updateExpenseOverride(event.target);
    }
    queueBudgetCalculation(form);
  });
  form.addEventListener("change", () => queueBudgetCalculation(form));
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    calculateBudget(form);
  });
  document
    .querySelector("#budget-reset-expenses")
    .addEventListener("click", () => {
      budgetState.expenseOverrides = {};
      queueBudgetCalculation(form);
    });
  document
    .querySelector("#budget-plan-button")
    .addEventListener("click", () => continueToPlanner(form));

  calculateBudget(form);
}

function updateExpenseOverride(input) {
  const category = input.dataset.budgetExpense;
  if (!category) {
    return;
  }
  if (input.value.trim() === "") {
    delete budgetState.expenseOverrides[category];
    return;
  }
  budgetState.expenseOverrides[category] = Number(input.value);
}

function queueBudgetCalculation(form) {
  window.clearTimeout(budgetState.debounceTimer);
  budgetState.debounceTimer = window.setTimeout(
    () => calculateBudget(form),
    250,
  );
  setBudgetStatus("Updating the illustrative estimate…");
}

async function calculateBudget(form) {
  window.clearTimeout(budgetState.debounceTimer);
  const requestNumber = ++budgetState.requestNumber;
  const payload = {
    csrf_token: document.querySelector("#budget-csrf-token").value,
    budget_inr: Number(document.querySelector("#budget-total-input").value),
    days: Number(document.querySelector("#budget-days-input").value),
    travellers: Number(document.querySelector("#budget-travellers-input").value),
    travel_mode: "bus",
    accommodation_preference: document.querySelector("#budget-accommodation-input").value,
    food_preference: document.querySelector("#budget-food-input").value,
    expense_overrides: budgetState.expenseOverrides,
  };

  setBudgetStatus("Calculating sample estimates…");
  try {
    const response = await fetch(form.dataset.endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const result = await response.json();
    if (!response.ok) {
      throw new Error(result.error || "The budget estimate could not be calculated.");
    }
    if (requestNumber !== budgetState.requestNumber) {
      return;
    }

    budgetState.estimate = result;
    renderBudgetEstimate(result);
    setBudgetStatus("Estimate updated. Sample rates are not live prices or quotes.");
  } catch (error) {
    if (requestNumber !== budgetState.requestNumber) {
      return;
    }
    document.querySelector("#budget-results").hidden = true;
    document.querySelector("#budget-plan-button").disabled = true;
    setBudgetStatus(
      error instanceof Error ? error.message : "The budget estimate could not be calculated.",
      true,
    );
  }
}

function renderBudgetEstimate(result) {
  const formatCurrency = (amount) => `₹${Number(amount).toLocaleString("en-IN", {
    maximumFractionDigits: 2,
  })}`;
  document.querySelector("#budget-summary-budget").textContent =
    formatCurrency(result.inputs.budget_inr);
  document.querySelector("#budget-summary-estimate").textContent =
    formatCurrency(result.total_estimate_inr);
  document.querySelector("#budget-summary-per-person").textContent =
    formatCurrency(result.per_person_inr);

  const remainingLabel = document.querySelector("#budget-summary-remaining-label");
  const remaining = document.querySelector("#budget-summary-remaining");
  if (result.over_budget) {
    remainingLabel.textContent = "Over budget by";
    remaining.textContent = formatCurrency(Math.abs(result.remaining_budget_inr));
  } else {
    remainingLabel.textContent = "Remaining budget";
    remaining.textContent = formatCurrency(result.remaining_budget_inr);
  }

  for (const [category] of budgetCategories) {
    const input = document.querySelector(`[data-budget-expense="${category}"]`);
    const expense = result.expenses[category];
    if (input && expense && document.activeElement !== input) {
      input.value = String(expense.amount_inr);
    }
  }
  renderBudgetChart(result.expenses, result.total_estimate_inr, formatCurrency);
  document.querySelector("#budget-result-notice").textContent = result.sample_notice;
  document.querySelector("#budget-results").hidden = false;
  document.querySelector("#budget-plan-button").disabled = false;
}

function renderBudgetChart(expenses, total, formatCurrency) {
  const chart = document.querySelector("#budget-chart");
  chart.replaceChildren();
  for (const [category, label] of budgetCategories) {
    const amount = expenses[category].amount_inr;
    const item = document.createElement("li");
    item.className = "budget-chart-item";
    const heading = document.createElement("div");
    heading.className = "budget-chart-heading";
    const categoryLabel = document.createElement("span");
    categoryLabel.textContent = label;
    const value = document.createElement("strong");
    value.textContent = formatCurrency(amount);
    heading.append(categoryLabel, value);

    const track = document.createElement("div");
    track.className = "budget-chart-track";
    track.setAttribute("role", "img");
    track.setAttribute(
      "aria-label",
      `${label}: ${formatCurrency(amount)} of ${formatCurrency(total)}`,
    );
    const bar = document.createElement("span");
    bar.style.width = `${total > 0 ? Math.min((amount / total) * 100, 100) : 0}%`;
    track.append(bar);
    item.append(heading, track);
    chart.append(item);
  }
}

function continueToPlanner(form) {
  if (!budgetState.estimate) {
    return;
  }
  const destinationId = document.querySelector("#budget-destination-input").value;
  const draft = {
    budget_inr: Number(document.querySelector("#budget-total-input").value),
    days: Number(document.querySelector("#budget-days-input").value),
    travellers: Number(document.querySelector("#budget-travellers-input").value),
    travel_mode: "bus",
    accommodation_preference: document.querySelector("#budget-accommodation-input").value,
    food_preference: document.querySelector("#budget-food-input").value,
    expense_overrides: budgetState.expenseOverrides,
    destination_ids: destinationId ? [destinationId] : [],
  };
  try {
    window.sessionStorage.setItem("rootsRoutesPlannerDraft", JSON.stringify(draft));
  } catch (error) {
    setBudgetStatus("This browser could not pass trip details to the planner. Check its storage settings and try again.", true);
    console.error(error);
    return;
  }
  window.location.assign(form.dataset.plannerUrl);
}

function setBudgetStatus(message, isError = false) {
  const status = document.querySelector("#budget-status");
  status.textContent = message;
  status.classList.toggle("is-error", isError);
}
