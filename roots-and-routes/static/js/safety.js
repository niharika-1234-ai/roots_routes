"use strict";

document.addEventListener("DOMContentLoaded", initializeSafetyTools);

function initializeSafetyTools() {
  const form = document.querySelector("#safety-checkin-form");
  if (!form) {
    return;
  }

  const locationButton = document.querySelector("#safety-use-location");
  const clearLocationButton = document.querySelector("#safety-clear-location");
  const includeLocation = document.querySelector("#safety-include-location");
  const locationStatus = document.querySelector("#safety-location-status");
  const shareStatus = document.querySelector("#safety-share-status");
  const draftLink = document.querySelector("#safety-draft-link");
  const contactInput = document.querySelector("#safety-contact");
  const returnTimeInput = document.querySelector("#safety-return-time");
  const prepareButton = document.querySelector("#safety-prepare-draft");
  const prepareSosButton = document.querySelector("#safety-prepare-sos");
  const clearDetailsButton = document.querySelector("#safety-clear-details");
  let currentLocation = null;
  const invalidateDraft = () => {
    if (draftLink.hidden) {
      return;
    }
    draftLink.hidden = true;
    draftLink.removeAttribute("href");
    shareStatus.textContent = "Details changed. Prepare a new draft before sharing.";
  };

  locationButton.addEventListener("click", () => {
    if (!navigator.geolocation) {
      locationStatus.textContent = "This browser does not support location access.";
      return;
    }

    if (currentLocation) {
      currentLocation = null;
      clearLocationButton.disabled = true;
      includeLocation.checked = false;
      includeLocation.disabled = true;
      window.dispatchEvent(new CustomEvent("roots-routes:clear-map-location"));
      invalidateDraft();
    }
    locationButton.disabled = true;
    locationStatus.textContent = "Waiting for your browser's location permission…";
    navigator.geolocation.getCurrentPosition(
      (position) => {
        currentLocation = {
          latitude: position.coords.latitude,
          longitude: position.coords.longitude,
        };
        locationButton.disabled = false;
        clearLocationButton.disabled = false;
        includeLocation.disabled = false;
        invalidateDraft();
        locationStatus.textContent = "Location is available for this page session. Nearby searches send it to this app and Overpass; a contact draft includes it only if you opt in below.";
        window.dispatchEvent(new CustomEvent("roots-routes:set-map-location", {
          detail: currentLocation,
        }));
      },
      (error) => {
        locationButton.disabled = false;
        const messages = {
          1: "Location permission was denied. You can still choose a catalogue destination on the map.",
          2: "Your device could not determine a location. Try again or choose a catalogue destination.",
          3: "Location lookup timed out. Try again or choose a catalogue destination.",
        };
        locationStatus.textContent = messages[error.code] || "Location is unavailable. Choose a catalogue destination instead.";
      },
      { enableHighAccuracy: false, maximumAge: 30000, timeout: 10000 },
    );
  });

  clearLocationButton.addEventListener("click", () => {
    currentLocation = null;
    clearLocationButton.disabled = true;
    includeLocation.checked = false;
    includeLocation.disabled = true;
    invalidateDraft();
    locationStatus.textContent = "Current location cleared from this page.";
    window.dispatchEvent(new CustomEvent("roots-routes:clear-map-location"));
  });

  clearDetailsButton.addEventListener("click", () => {
    contactInput.value = "";
    returnTimeInput.value = "";
    draftLink.hidden = true;
    draftLink.removeAttribute("href");
    shareStatus.textContent = "Contact details and the generated draft cleared from this page.";
  });
  form.addEventListener("input", invalidateDraft);
  includeLocation.addEventListener("change", invalidateDraft);
  document.querySelector("#route-source").addEventListener("input", invalidateDraft);
  document.querySelector("#route-destination").addEventListener("input", invalidateDraft);
  window.addEventListener("roots-routes:map-location-changed", invalidateDraft);

  prepareButton.addEventListener("click", () => prepareDraft(false));
  prepareSosButton.addEventListener("click", () => prepareDraft(true));

  function prepareDraft(isSos) {
    draftLink.hidden = true;
    draftLink.removeAttribute("href");

    const contact = contactInput.value.trim();
    const destination = document.querySelector("#route-destination").value.trim();
    const source = document.querySelector("#route-source").value.trim();
    const expectedReturn = returnTimeInput.value;
    if (!isEmailAddress(contact) && !isPhoneNumber(contact)) {
      shareStatus.textContent = "Enter a valid email address or phone number for your trusted contact.";
      return;
    }
    if (!isSos && !destination) {
      shareStatus.textContent = "Choose or search for a destination in the map route planner first.";
      return;
    }
    if (!isSos && !expectedReturn) {
      shareStatus.textContent = "Set an expected return time for your check-in.";
      return;
    }
    if (expectedReturn && Number.isNaN(new Date(expectedReturn).getTime())) {
      shareStatus.textContent = "Enter a valid expected return time.";
      return;
    }

    const lines = isSos
      ? ["ROOTS & ROUTES SOS assistance", "I need help. Please contact me as soon as possible."]
      : ["ROOTS & ROUTES travel check-in"];
    if (destination) {
      lines.push(`Route: ${source || "Not specified"} → ${destination}`);
    }
    if (expectedReturn) {
      lines.push(`Expected return: ${new Date(expectedReturn).toLocaleString()}`);
    }
    if (includeLocation.checked && currentLocation) {
      const { latitude, longitude } = currentLocation;
      const mapUrl = `https://www.openstreetmap.org/?mlat=${latitude}&mlon=${longitude}#map=16/${latitude}/${longitude}`;
      lines.push(`My current location: ${mapUrl}`);
    }
    if (!isSos) {
      lines.push("Please contact me if I miss this check-in.");
    }
    const message = lines.join("\n");
    const isEmail = contact.includes("@");
    draftLink.href = isEmail
      ? `mailto:${encodeURIComponent(contact).replace(/%40/gi, "@")}?subject=${encodeURIComponent(isSos ? "SOS assistance" : "Travel check-in")}&body=${encodeURIComponent(message)}`
      : `sms:${normalizePhoneNumber(contact)}?body=${encodeURIComponent(message)}`;
    draftLink.textContent = `Open ${isEmail ? "email" : "SMS"} ${isSos ? "SOS" : "check-in"} draft`;
    draftLink.hidden = false;
    shareStatus.textContent = isSos
      ? "SOS draft prepared. Nothing has been sent; review and send it in your own app. For immediate danger, call 112."
      : "Draft prepared. No message has been sent; open the draft and send it yourself. Delivery cannot be confirmed here.";
  }
}

function isEmailAddress(value) {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value);
}

function isPhoneNumber(value) {
  const digits = value.replace(/\D/g, "");
  return /^\+?[\d()\s.-]+$/.test(value) && digits.length >= 7 && digits.length <= 15;
}

function normalizePhoneNumber(value) {
  const digits = value.replace(/\D/g, "");
  return `${value.trim().startsWith("+") ? "+" : ""}${digits}`;
}
