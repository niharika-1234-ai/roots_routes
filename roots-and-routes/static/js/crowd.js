"use strict";

function renderCrowdChart() {
  const canvas = document.querySelector("#crowd-history-chart");
  const source = document.querySelector("#crowd-chart-data");
  if (!canvas || !source || !window.Chart) {
    return;
  }

  const chartData = JSON.parse(source.textContent);
  new Chart(canvas, {
    type: "line",
    data: chartData,
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: {
        intersect: false,
        mode: "index",
      },
      plugins: {
        legend: {
          position: "bottom",
          labels: {
            usePointStyle: true,
            boxWidth: 7,
            boxHeight: 7,
            color: "#657367",
            font: { size: 10 },
            padding: 18,
          },
        },
        tooltip: {
          callbacks: {
            label: (context) => {
              const value = context.parsed.y;
              return value === null
                ? `${context.dataset.label}: no estimate`
                : `${context.dataset.label}: sample index ${value}/100`;
            },
          },
        },
      },
      scales: {
        x: {
          grid: { display: false },
          ticks: { color: "#7a887c", font: { size: 10 } },
          border: { display: false },
        },
        y: {
          min: 0,
          max: 100,
          title: {
            display: true,
            text: "Synthetic sample index (0–100)",
            color: "#758477",
            font: { size: 10 },
          },
          grid: { color: "#edf0e9" },
          ticks: { stepSize: 20, color: "#7a887c", font: { size: 9 } },
          border: { display: false },
        },
      },
    },
  });
}

document.addEventListener("DOMContentLoaded", renderCrowdChart);
