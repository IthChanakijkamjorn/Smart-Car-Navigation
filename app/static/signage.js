// Signage display logic: poll the server and repaint the screen.
// Deliberately plain JavaScript - no framework, no build step, so it keeps
// working on the simple browsers built into signage devices.

(function () {
  "use strict";

  // Arrow drawn for each direction hint coming from the destination record.
  var ARROWS = {
    left: "\u2190",     // ←
    right: "\u2192",    // →
    straight: "\u2191", // ↑
    up: "\u2191",
    back: "\u2193"
  };

  var body = document.body;
  var arrowEl = document.getElementById("arrow");
  var destinationEl = document.getElementById("destination");
  var plateEl = document.getElementById("plate");
  var connectionEl = document.getElementById("connection");

  function render(data) {
    // Body class drives the colour scheme (see signage.css).
    body.className = "state-" + (data.state || "idle");

    if (data.state === "guiding") {
      arrowEl.textContent = ARROWS[data.direction_hint] || "";
      destinationEl.textContent = data.destination || data.message || "";
    } else {
      arrowEl.textContent = data.state === "unregistered" ? "\u26A0" : "";
      destinationEl.textContent = data.message || "";
    }
    plateEl.textContent = data.plate_number && data.state !== "idle" ? data.plate_number : "";
  }

  function setConnection(online) {
    connectionEl.textContent = online ? "online" : "reconnecting...";
    connectionEl.className = online ? "ok" : "error";
  }

  function poll() {
    fetch(POLL_URL, { cache: "no-store" })
      .then(function (response) {
        if (!response.ok) { throw new Error("HTTP " + response.status); }
        return response.json();
      })
      .then(function (data) {
        setConnection(true);
        render(data);
      })
      .catch(function () {
        // Keep the last message on screen; the server is probably restarting.
        setConnection(false);
      });
  }

  render(INITIAL);
  var intervalMs = (INITIAL && INITIAL.poll_interval_ms) || 1000;
  setInterval(poll, intervalMs);
  poll();
})();
