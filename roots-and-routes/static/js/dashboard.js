"use strict";

function setupSidebar() {
  const sidebar = document.querySelector("#app-sidebar");
  const toggle = document.querySelector("[data-sidebar-toggle]");
  const scrim = document.querySelector("[data-sidebar-close]");
  if (!sidebar || !toggle || !scrim) {
    return;
  }

  const setOpen = (open) => {
    sidebar.classList.toggle("is-open", open);
    scrim.classList.toggle("is-open", open);
    toggle.setAttribute("aria-expanded", String(open));
    toggle.setAttribute("aria-label", open ? "Close navigation" : "Open navigation");
  };
  toggle.addEventListener("click", () => setOpen(!sidebar.classList.contains("is-open")));
  scrim.addEventListener("click", () => setOpen(false));
  sidebar.querySelectorAll(".nav-link").forEach((link) => {
    link.addEventListener("click", () => setOpen(false));
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      setOpen(false);
    }
  });
}

function setupNotifications() {
  const toggle = document.querySelector("[data-notification-toggle]");
  const panel = document.querySelector("#notification-panel");
  if (!toggle || !panel) {
    return;
  }

  toggle.addEventListener("click", () => {
    const isOpen = toggle.getAttribute("aria-expanded") === "true";
    toggle.setAttribute("aria-expanded", String(!isOpen));
    panel.hidden = isOpen;
  });
  document.addEventListener("click", (event) => {
    if (!toggle.contains(event.target) && !panel.contains(event.target)) {
      toggle.setAttribute("aria-expanded", "false");
      panel.hidden = true;
    }
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      toggle.setAttribute("aria-expanded", "false");
      panel.hidden = true;
    }
  });
}

function setupGlobalSearch() {
  const form = document.querySelector("[data-global-search]");
  const toggle = document.querySelector("[data-search-toggle]");
  const input = form?.querySelector('input[type="search"]');
  if (!form || !toggle || !input) {
    return;
  }

  toggle.addEventListener("click", () => input.focus());
}

function renderSustainabilityChart() {
  const canvas = document.querySelector("#sustainability-chart");
  const source = document.querySelector("#sustainability-data");
  if (!canvas || !source || !window.Chart) {
    return;
  }

  const records = JSON.parse(source.textContent);
  if (!records.length) {
    return;
  }

  new Chart(canvas, {
    type: "bar",
    data: {
      labels: records.map((record) => record.name),
      datasets: [{
        data: records.map((record) => record.score),
        backgroundColor: records.map((_, index) => index === 0 ? "#39784d" : "#b9d1b3"),
        borderRadius: 5,
        barThickness: 11,
      }],
    },
    options: {
      indexAxis: "y",
      maintainAspectRatio: false,
      scales: {
        x: {
          min: 0,
          max: 100,
          grid: { color: "#edf0e9" },
          ticks: { color: "#8a968c", font: { size: 9 } },
          border: { display: false },
        },
        y: {
          grid: { display: false },
          ticks: { color: "#657367", font: { size: 10 } },
          border: { display: false },
        },
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: (context) => `Sourced sustainability score: ${context.parsed.x}/100`,
          },
        },
      },
    },
  });
}

document.addEventListener("DOMContentLoaded", () => {
  setupSidebar();
  setupNotifications();
  setupGlobalSearch();
  renderSustainabilityChart();
});
