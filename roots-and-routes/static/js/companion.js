"use strict";

function setupTravelCompanion() {
  const form = document.querySelector("#companion-form");
  const messageField = document.querySelector("#companion-message");
  const messages = document.querySelector("#companion-messages");
  const status = document.querySelector("#companion-status");
  const modeBadge = document.querySelector("#companion-mode");
  const submitButton = form?.querySelector('button[type="submit"]');
  const submitLabel = document.querySelector("#companion-submit-label");
  if (!form || !messageField || !messages || !status || !submitButton || !submitLabel) {
    return;
  }

  const addMessage = (role, text, sources = []) => {
    const article = document.createElement("article");
    article.className = `companion-message companion-message-${role}`;
    const label = document.createElement("span");
    label.className = "companion-message-label";
    label.textContent = role === "user" ? "YOU" : "ROOTS & ROUTES";
    const paragraph = document.createElement("p");
    paragraph.textContent = text;
    article.append(label, paragraph);

    const safeSources = sources.filter((source) => {
      if (!source || typeof source.label !== "string" || typeof source.url !== "string") {
        return false;
      }
      try {
        return new URL(source.url).protocol === "https:";
      } catch {
        return false;
      }
    });
    if (safeSources.length) {
      const sourceList = document.createElement("div");
      sourceList.className = "companion-sources";
      const sourceLabel = document.createElement("span");
      sourceLabel.textContent = "Sources";
      sourceList.append(sourceLabel);
      safeSources.forEach((source) => {
        const link = document.createElement("a");
        link.href = source.url;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        link.textContent = source.label;
        sourceList.append(link);
      });
      article.append(sourceList);
    }

    messages.append(article);
    messages.scrollTop = messages.scrollHeight;
  };

  const renderContext = (context) => {
    if (!context || typeof context !== "object") {
      return;
    }
    const duration = document.querySelector("#companion-context-duration");
    const budget = document.querySelector("#companion-context-budget");
    const places = document.querySelector("#companion-context-places");
    const interests = document.querySelector("#companion-context-interests");
    if (duration) {
      duration.textContent = Number.isInteger(context.duration_days)
        ? `${context.duration_days} days`
        : "Not set";
    }
    if (budget) {
      budget.textContent = Number.isInteger(context.budget_inr)
        ? `₹${context.budget_inr.toLocaleString("en-IN")}`
        : "Not set";
    }
    if (places) {
      places.textContent = Array.isArray(context.destination_names) && context.destination_names.length
        ? context.destination_names.join(", ")
        : "Not set";
    }
    if (interests) {
      interests.textContent = Array.isArray(context.interests) && context.interests.length
        ? context.interests.map((interest) => interest.replaceAll("_", " ")).join(", ")
        : "Not set";
    }
  };

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const message = messageField.value.trim();
    if (!message) {
      status.textContent = "Enter a question first.";
      messageField.focus();
      return;
    }

    addMessage("user", message);
    messageField.value = "";
    status.textContent = "Checking the available sources…";
    submitButton.disabled = true;
    submitLabel.textContent = "Thinking";

    try {
      const response = await fetch("/api/companion/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message,
          csrf_token: form.elements.csrf_token.value,
        }),
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.error || "The travel companion could not answer right now.");
      }

      renderContext(payload.context);
      addMessage("assistant", payload.answer, payload.sources);
      if (modeBadge) {
        modeBadge.textContent = payload.mode === "ai" ? "AI-assisted" : "Grounded local response";
      }
      status.textContent = payload.notice || "";
    } catch (error) {
      const errorMessage = error instanceof Error
        ? error.message
        : "The travel companion could not answer right now.";
      addMessage("assistant", errorMessage);
      status.textContent = errorMessage;
    } finally {
      submitButton.disabled = false;
      submitLabel.textContent = "Send";
      messageField.focus();
    }
  });

  document.querySelectorAll("[data-companion-prompt]").forEach((button) => {
    button.addEventListener("click", () => {
      messageField.value = button.dataset.companionPrompt || "";
      form.requestSubmit();
    });
  });

  document.querySelector("#clear-companion-context")?.addEventListener("click", () => {
    messageField.value = "Clear trip context";
    form.requestSubmit();
  });
}

document.addEventListener("DOMContentLoaded", setupTravelCompanion);
