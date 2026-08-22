(() => {
  const bodyDataset = document.body ? document.body.dataset : {};
  const optimizeUrl = bodyDataset.optimizeUrl || "";
  const suggestUrl = bodyDataset.suggestUrl || "";

  if (!optimizeUrl || !suggestUrl) {
    console.error("Missing optimize or suggest URL configuration.");
    return;
  }

  const REQUEST_TIMEOUT_MS = 45000;
  const SUGGEST_DEBOUNCE_MS = 850;
  const SUGGEST_TIMEOUT_MS = 8000;
  const MIN_SUGGEST_QUERY_LEN = 3;

  const map = L.map("map", { zoomControl: true }).setView([39.8283, -98.5795], 4);

  L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png", {
    attribution: '&copy; <a href="https://carto.com/">CARTO</a>',
    maxZoom: 19,
  }).addTo(map);

  const layerGroup = L.layerGroup().addTo(map);

  function markerIcon(color) {
    return L.divIcon({
      className: "",
      html: '<div style="width:18px;height:18px;border-radius:50%;background:' + color + ';border:2px solid #fff;box-shadow:0 2px 10px rgba(0,0,0,.5);"></div>',
      iconSize: [18, 18],
      iconAnchor: [9, 9],
    });
  }

  const icons = {
    start: markerIcon("#ffffff"),
    end: markerIcon("#3b82f6"),
    stop: markerIcon("#22c55e"),
  };

  const form = document.getElementById("routeForm");
  const originInput = document.getElementById("originInput");
  const destinationInput = document.getElementById("destinationInput");
  const originSuggestions = document.getElementById("originSuggestions");
  const destinationSuggestions = document.getElementById("destinationSuggestions");
  const alternativesBox = document.getElementById("alternativesBox");
  const alternativesList = document.getElementById("alternativesList");
  const searchBtn = document.getElementById("searchBtn");
  const searchBtnLabel = document.getElementById("searchBtnLabel");
  const requestLoaderBackdrop = document.getElementById("requestLoaderBackdrop");
  const requestLoaderModal = document.getElementById("requestLoaderModal");
  const errorBox = document.getElementById("errorBox");
  const engineBadge = document.getElementById("engineBadge");

  const timeWeight = document.getElementById("timeWeight");
  const priceWeight = document.getElementById("priceWeight");
  const timeLabel = document.getElementById("timeLabel");
  const priceLabel = document.getElementById("priceLabel");
  const avgMpgInput = document.getElementById("avgMpgInput");
  const tankCapacityInput = document.getElementById("tankCapacityInput");
  const startFuelInput = document.getElementById("startFuelInput");

  const emptyState = document.getElementById("emptyState");
  const resultBlock = document.getElementById("resultBlock");
  const distanceValue = document.getElementById("distanceValue");
  const durationValue = document.getElementById("durationValue");
  const fuelValue = document.getElementById("fuelValue");
  const scoreValue = document.getElementById("scoreValue");
  const fuelModelNote = document.getElementById("fuelModelNote");
  const routeDetails = document.getElementById("routeDetails");

  let optimizeAbortController = null;
  const suggestTimers = { origin: null, destination: null };
  const suggestControllers = { origin: null, destination: null };

  let currentPayload = null;
  let currentAlternatives = [];
  let selectedAlternativeIndex = -1;
  let currentRequestToken = 0;

  let selectedOriginPlace = null;
  let selectedDestinationPlace = null;

  function esc(value) {
    return String(value)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function toNumber(value, fallback = 0) {
    const numeric = Number(value);
    return Number.isFinite(numeric) ? numeric : fallback;
  }

  function parseCoordinate(value, min, max) {
    if (value === null || value === undefined || value === "") {
      return null;
    }

    const numeric = Number(value);
    if (!Number.isFinite(numeric)) {
      return null;
    }

    if (numeric < min || numeric > max) {
      return null;
    }

    return numeric;
  }

  function formatMiles(distanceMeters) {
    const miles = toNumber(distanceMeters) / 1609.344;
    return Math.max(0, Math.round(miles)) + " mi";
  }

  function formatDuration(seconds) {
    const total = Math.max(0, Math.round(toNumber(seconds)));
    const h = Math.floor(total / 3600);
    const m = Math.floor((total % 3600) / 60);
    if (h <= 0) {
      return m + "m";
    }

    return h + "h " + m + "m";
  }

  function formatMoney(value) {
    return "$" + toNumber(value).toFixed(2);
  }

  function formatCompactNumber(value) {
    const numeric = toNumber(value);
    const rounded = Math.round(numeric * 10) / 10;
    if (Math.abs(rounded - Math.round(rounded)) < 0.0001) {
      return String(Math.round(rounded));
    }

    return rounded.toFixed(1);
  }

  function showError(message) {
    errorBox.textContent = message;
    errorBox.classList.add("active");
  }

  function clearError() {
    errorBox.textContent = "";
    errorBox.classList.remove("active");
  }

  function renderEngineBadge(engine, notices = []) {
    const messageParts = [];

    if (engine === "fallback_estimate") {
      messageParts.push(
        "Estimated route: live providers were unavailable, so this result uses fallback calculations.",
      );
    }

    if (Array.isArray(notices)) {
      notices.forEach((notice) => {
        if (typeof notice === "string" && notice.trim()) {
          messageParts.push(notice.trim());
        }
      });
    }

    if (messageParts.length > 0) {
      engineBadge.textContent = messageParts.join(" ");
      engineBadge.classList.add("active");
      return;
    }

    engineBadge.textContent = "";
    engineBadge.classList.remove("active");
  }

  function setSearching(isSearching) {
    searchBtn.disabled = isSearching;
    if (searchBtnLabel) {
      searchBtnLabel.textContent = isSearching ? "Calculating..." : "Find Route";
    }

    if (!requestLoaderBackdrop || !requestLoaderModal) {
      return;
    }

    if (isSearching) {
      requestLoaderBackdrop.hidden = false;
      requestLoaderModal.hidden = false;

      window.requestAnimationFrame(() => {
        requestLoaderBackdrop.classList.add("is-visible");
        requestLoaderModal.classList.add("is-open");
      });

      requestLoaderModal.setAttribute("aria-hidden", "false");
      document.body.classList.add("request-loader-open");
      return;
    }

    requestLoaderBackdrop.classList.remove("is-visible");
    requestLoaderModal.classList.remove("is-open");
    requestLoaderModal.setAttribute("aria-hidden", "true");
    document.body.classList.remove("request-loader-open");

    window.setTimeout(() => {
      if (!requestLoaderModal.classList.contains("is-open")) {
        requestLoaderBackdrop.hidden = true;
        requestLoaderModal.hidden = true;
      }
    }, 220);
  }

  function updateWeightLabels() {
    timeLabel.textContent = Number(timeWeight.value).toFixed(2);
    priceLabel.textContent = Number(priceWeight.value).toFixed(2);
  }

  function hideSuggestionBox(box) {
    box.classList.remove("active");
    box.innerHTML = "";
  }

  function getSuggestBox(kind) {
    return kind === "origin" ? originSuggestions : destinationSuggestions;
  }

  function getSuggestInput(kind) {
    return kind === "origin" ? originInput : destinationInput;
  }

  function renderSuggestionResults(kind, results) {
    const box = getSuggestBox(kind);

    if (!Array.isArray(results) || results.length === 0) {
      box.innerHTML = '<div class="suggestion-btn">No suggestions found</div>';
      box.classList.add("active");
      return;
    }

    box.innerHTML = results
      .slice(0, 8)
      .map((item, index) => {
        return (
          '<button class="suggestion-btn" type="button" data-index="' + index + '">' +
            esc(item.name || "Unknown place") +
          "</button>"
        );
      })
      .join("");

    box.classList.add("active");

    box.querySelectorAll(".suggestion-btn").forEach((button) => {
      button.addEventListener("click", () => {
        const selected = results[Number(button.dataset.index)];
        const input = getSuggestInput(kind);
        input.value = selected && selected.name ? selected.name : "";

        const normalizedSelection = selected
          ? {
              name: selected.name,
              lat: Number(selected.lat),
              lon: Number(selected.lon),
            }
          : null;

        if (kind === "origin") {
          selectedOriginPlace = normalizedSelection;
        } else {
          selectedDestinationPlace = normalizedSelection;
        }

        hideSuggestionBox(box);
      });
    });
  }

  async function fetchSuggestions(kind, query) {
    const box = getSuggestBox(kind);
    const input = getSuggestInput(kind);

    if (query.length < MIN_SUGGEST_QUERY_LEN) {
      hideSuggestionBox(box);
      return;
    }

    if (suggestControllers[kind]) {
      suggestControllers[kind].abort();
    }

    const controller = new AbortController();
    suggestControllers[kind] = controller;
    const timeoutId = window.setTimeout(() => controller.abort(), SUGGEST_TIMEOUT_MS);

    box.innerHTML = '<div class="suggestion-btn">Searching...</div>';
    box.classList.add("active");

    try {
      const url = new URL(suggestUrl, window.location.origin);
      url.searchParams.set("q", query);

      const response = await fetch(url.toString(), {
        method: "GET",
        headers: { Accept: "application/json" },
        signal: controller.signal,
      });

      let payload = {};
      try {
        payload = await response.json();
      } catch {
        payload = {};
      }

      if (!response.ok || controller.signal.aborted) {
        hideSuggestionBox(box);
        return;
      }

      if (input.value.trim() !== query) {
        return;
      }

      renderSuggestionResults(kind, payload.results || []);
    } catch (error) {
      if (error.name !== "AbortError") {
        hideSuggestionBox(box);
      }
    } finally {
      window.clearTimeout(timeoutId);
    }
  }

  function scheduleSuggestions(kind, value) {
    if (suggestTimers[kind]) {
      window.clearTimeout(suggestTimers[kind]);
    }

    const query = value.trim();
    if (query.length < MIN_SUGGEST_QUERY_LEN) {
      hideSuggestionBox(getSuggestBox(kind));
      return;
    }

    suggestTimers[kind] = window.setTimeout(() => {
      fetchSuggestions(kind, query);
    }, SUGGEST_DEBOUNCE_MS);
  }

  function renderRouteDetails(data) {
    const rows = [];

    rows.push(
      '<div class="route-item">' +
        '<div class="node-wrap"><div class="node start"></div><div class="line"></div></div>' +
        '<div><div class="route-label">Start</div><div class="route-name">' + esc(data.origin.name) + "</div></div>" +
      "</div>"
    );

    (data.waypoints || []).forEach((wp) => {
      const addressRow = wp.address
        ? '<div class="route-sub">' + esc(wp.address) + "</div>"
        : "";

      rows.push(
        '<div class="route-item">' +
          '<div class="node-wrap"><div class="node stop"></div><div class="line"></div></div>' +
          '<div><div class="route-label">' + esc(wp.type || "Stop") + '</div><div class="route-name">' + esc(wp.name) + "</div>" + addressRow + "</div>" +
        "</div>"
      );
    });

    rows.push(
      '<div class="route-item">' +
        '<div class="node-wrap"><div class="node end"></div><div class="line"></div></div>' +
        '<div><div class="route-label">End</div><div class="route-name">' + esc(data.destination.name) + "</div></div>" +
      "</div>"
    );

    routeDetails.innerHTML = rows.join("");
  }

  function renderMap(data) {
    layerGroup.clearLayers();

    const bounds = [];

    if (Array.isArray(data.path) && data.path.length > 1) {
      const polyline = L.polyline(data.path, {
        color: "#3b82f6",
        weight: 4,
        opacity: 0.85,
      }).addTo(layerGroup);
      bounds.push(...polyline.getLatLngs());
    }

    if (data.origin) {
      const m = L.marker([data.origin.lat, data.origin.lng], { icon: icons.start }).addTo(layerGroup);
      m.bindPopup("<b>Origin</b><br>" + esc(data.origin.name));
      bounds.push([data.origin.lat, data.origin.lng]);
    }

    if (data.destination) {
      const m = L.marker([data.destination.lat, data.destination.lng], { icon: icons.end }).addTo(layerGroup);
      m.bindPopup("<b>Destination</b><br>" + esc(data.destination.name));
      bounds.push([data.destination.lat, data.destination.lng]);
    }

    (data.waypoints || []).forEach((wp) => {
      const m = L.marker([wp.lat, wp.lng], { icon: icons.stop }).addTo(layerGroup);
      const addressSuffix = wp.address ? "<br>" + esc(wp.address) : "";
      m.bindPopup("<b>" + esc(wp.type || "Stop") + "</b><br>" + esc(wp.name) + addressSuffix);
      bounds.push([wp.lat, wp.lng]);
    });

    if (bounds.length === 1) {
      map.setView(bounds[0], 11);
    } else if (bounds.length > 1) {
      map.fitBounds(bounds, { padding: [40, 40] });
    }
  }

  function renderMetrics(data) {
    const fuelPlan = data.fuel_plan || null;
    const noRefuelRequired = !!(fuelPlan && Number(fuelPlan.min_refuel_stops) <= 0);

    distanceValue.textContent = formatMiles(data.distance_m);
    durationValue.textContent = formatDuration(data.duration_s);

    if (noRefuelRequired) {
      fuelValue.textContent = "--";
      scoreValue.textContent = "--";
    } else {
      fuelValue.textContent = formatMoney(data.fuel_cost);
      scoreValue.textContent = toNumber(data.score).toFixed(3);
    }
  }

  function buildFuelPlan(distanceMeters, assumptions) {
    if (!assumptions) {
      return null;
    }

    const avgMpg = toNumber(assumptions.avg_mpg);
    const tankGallons = toNumber(assumptions.tank_capacity_gal);
    const startFuelPercent = Math.max(0, Math.min(100, toNumber(assumptions.start_fuel_percent, 100)));

    if (avgMpg <= 0 || tankGallons <= 0) {
      return null;
    }

    const miles = toNumber(distanceMeters) / 1609.344;
    const initialGallons = tankGallons * (startFuelPercent / 100);
    const initialRange = initialGallons * avgMpg;
    const maxRange = avgMpg * tankGallons;
    const minStops = miles <= initialRange
      ? 0
      : Math.max(0, Math.ceil((miles - initialRange) / maxRange));

    return {
      distance_mi: miles,
      gallons_needed: miles / avgMpg,
      avg_mpg: avgMpg,
      tank_capacity_gal: tankGallons,
      start_fuel_percent: startFuelPercent,
      initial_fuel_gal: initialGallons,
      initial_range_mi: initialRange,
      max_range_mi: maxRange,
      min_refuel_stops: minStops,
      requires_refuel: minStops > 0,
    };
  }

  function renderFuelModel(data) {
    const assumptions = data.assumptions || null;
    const fuelPlan = data.fuel_plan || buildFuelPlan(data.distance_m, assumptions);

    if (!assumptions || !fuelPlan) {
      fuelModelNote.textContent = "";
      return;
    }

    const mpg = toNumber(assumptions.avg_mpg);
    const tank = toNumber(assumptions.tank_capacity_gal);
    const startFuel = toNumber(assumptions.start_fuel_percent, 100);
    const stopNote = fuelPlan.requires_refuel
      ? "Minimum refuel stops: " + fuelPlan.min_refuel_stops + "."
      : "No refuel stop required for this distance.";

    fuelModelNote.textContent =
      "Assuming " + formatCompactNumber(mpg) + " mpg, " + formatCompactNumber(tank) + " gal tank, and " + formatCompactNumber(startFuel) + "% fuel at start. " + stopNote;
  }

  function renderSelectedRoute(data) {
    emptyState.style.display = "none";
    resultBlock.classList.add("active");
    renderMetrics(data);
    renderFuelModel(data);
    renderRouteDetails(data);
    renderMap(data);
  }

  function buildRouteFromAlternative(alternative) {
    const station = alternative.station || {};
    const stationLat = parseCoordinate(station.lat, -90, 90);
    const stationLon = parseCoordinate(station.lon, -180, 180);
    const stationHasCoords = stationLat !== null && stationLon !== null;

    const alternativePath = Array.isArray(alternative.geometry)
      ? alternative.geometry
          .map((point) => {
            if (!Array.isArray(point) || point.length < 2) {
              return null;
            }

            const lat = parseCoordinate(point[0], -90, 90);
            const lng = parseCoordinate(point[1], -180, 180);
            if (lat === null || lng === null) {
              return null;
            }

            return [lat, lng];
          })
          .filter((point) => point !== null)
      : [];
    const hasAlternativePath = alternativePath.length > 1;

    const sharedWaypoints = Array.isArray(currentPayload.waypoints) ? currentPayload.waypoints : [];
    const sharedPath = Array.isArray(currentPayload.path) ? currentPayload.path : [];
    const sharedFuelPlan = currentPayload.fuel_plan || buildFuelPlan(
      currentPayload.distance_m,
      currentPayload.assumptions,
    );

    const stationPrice = Number(station.retail_price ?? station.price);
    const stopName = (station.name || "Fuel stop") +
      (station.fuel_type ? " (" + station.fuel_type + ")" : "") +
      (Number.isFinite(stationPrice) ? " - " + formatMoney(stationPrice) : "");

    const route = {
      origin: currentPayload.origin,
      destination: currentPayload.destination,
      distance_m: toNumber(alternative.distance_m),
      duration_s: toNumber(alternative.duration_s),
      fuel_cost: toNumber(alternative.estimated_fuel_cost),
      score: toNumber(alternative.score),
      assumptions: currentPayload.assumptions || null,
      waypoints: [],
      path: [],
    };

    route.fuel_plan = sharedFuelPlan || buildFuelPlan(route.distance_m, route.assumptions);
    const sharedStopsRequired = toNumber(sharedFuelPlan && sharedFuelPlan.min_refuel_stops) > 0;
    const shouldUseSharedRefuelPlan = sharedWaypoints.length > 0 && sharedStopsRequired;

    if (shouldUseSharedRefuelPlan) {
      const normalizedSharedWaypoints = sharedWaypoints.map((wp) => {
        const waypointLat = parseCoordinate(wp.lat, -90, 90);
        const waypointLng = parseCoordinate(wp.lng, -180, 180);
        return {
          lat: waypointLat,
          lng: waypointLng,
          name: wp.name || "Fuel Stop",
          address: wp.address || "",
          type: wp.type || "Refuel Stop",
        };
      }).filter((wp) => wp.lat !== null && wp.lng !== null);

      const normalizedAlternativeWaypoints = Array.isArray(alternative.refuel_waypoints)
        ? alternative.refuel_waypoints
            .map((wp) => {
              const waypointLat = parseCoordinate(wp.lat, -90, 90);
              const waypointLng = parseCoordinate(wp.lng, -180, 180);
              return {
                lat: waypointLat,
                lng: waypointLng,
                name: wp.name || "Fuel Stop",
                address: wp.address || "",
                type: wp.type || "Refuel Stop",
              };
            })
            .filter((wp) => wp.lat !== null && wp.lng !== null)
        : [];

      route.waypoints = normalizedAlternativeWaypoints.length > 0
        ? normalizedAlternativeWaypoints
        : normalizedSharedWaypoints;

      if (hasAlternativePath) {
        route.path = alternativePath;
      } else if (sharedPath.length > 1) {
        route.path = sharedPath;
      } else {
        route.path = [
          [currentPayload.origin.lat, currentPayload.origin.lng],
          ...route.waypoints.map((wp) => [wp.lat, wp.lng]),
          [currentPayload.destination.lat, currentPayload.destination.lng],
        ];
      }

      return route;
    }

    if (stationHasCoords) {
      route.waypoints.push({
        lat: stationLat,
        lng: stationLon,
        name: stopName,
        address: station.address || "",
        type: "Fuel Stop",
      });
    }

    // Route options should use their own geometry so changing options updates the map.
    if (hasAlternativePath) {
      route.path = alternativePath;
      return route;
    }

    if (stationHasCoords) {
      route.path = [
        [currentPayload.origin.lat, currentPayload.origin.lng],
        [stationLat, stationLon],
        [currentPayload.destination.lat, currentPayload.destination.lng],
      ];
      return route;
    }

    route.path = sharedPath.length > 1 ? sharedPath : [];
    return route;
  }

  function updateActiveAlternative() {
    alternativesList.querySelectorAll(".alt-btn").forEach((button) => {
      const index = Number(button.dataset.index);
      button.classList.toggle("active", index === selectedAlternativeIndex);
    });
  }

  function selectAlternative(index) {
    if (!currentAlternatives[index]) {
      return;
    }

    selectedAlternativeIndex = index;
    updateActiveAlternative();
    const selectedRoute = buildRouteFromAlternative(currentAlternatives[index]);
    renderSelectedRoute(selectedRoute);
  }

  function renderAlternatives() {
    if (!Array.isArray(currentAlternatives) || currentAlternatives.length === 0) {
      alternativesList.innerHTML = "";
      alternativesBox.classList.remove("active");
      return;
    }

    alternativesList.innerHTML = currentAlternatives.map((alternative, index) => {
      const stationName = esc((alternative.station && alternative.station.name) || "Unknown station");
      const meta = [
        formatMiles(alternative.distance_m),
        formatDuration(alternative.duration_s),
        formatMoney(alternative.estimated_fuel_cost),
      ].join(" | ");

      return (
        '<button type="button" class="alt-btn" data-index="' + index + '">' +
          '<div class="alt-top"><span>#' + (index + 1) + " " + stationName + '</span><span>' + toNumber(alternative.score).toFixed(3) + "</span></div>" +
          '<div class="alt-meta">' + esc(meta) + "</div>" +
        "</button>"
      );
    }).join("");

    alternativesBox.classList.add("active");

    alternativesList.querySelectorAll(".alt-btn").forEach((button) => {
      button.addEventListener("click", () => {
        selectAlternative(Number(button.dataset.index));
      });
    });

    if (selectedAlternativeIndex < 0 || selectedAlternativeIndex >= currentAlternatives.length) {
      selectedAlternativeIndex = 0;
    }

    selectAlternative(selectedAlternativeIndex);
  }

  function applyOptimizePayload(payload) {
    currentPayload = payload;
    renderEngineBadge(payload.engine, payload.notices || []);
    currentAlternatives = (payload.alternatives || []).filter((item) => {
      if (!item || !item.station) {
        return false;
      }

      return item.station.name && Number.isFinite(Number(item.distance_m));
    });
    selectedAlternativeIndex = 0;

    if (currentAlternatives.length > 0) {
      renderAlternatives();
    } else {
      alternativesBox.classList.remove("active");
      renderSelectedRoute(payload);
    }
  }

  timeWeight.addEventListener("input", updateWeightLabels);
  priceWeight.addEventListener("input", updateWeightLabels);
  updateWeightLabels();

  originInput.addEventListener("input", () => {
    selectedOriginPlace = null;
    scheduleSuggestions("origin", originInput.value);
  });

  destinationInput.addEventListener("input", () => {
    selectedDestinationPlace = null;
    scheduleSuggestions("destination", destinationInput.value);
  });

  originInput.addEventListener("blur", () => {
    window.setTimeout(() => hideSuggestionBox(originSuggestions), 300);
  });
  destinationInput.addEventListener("blur", () => {
    window.setTimeout(() => hideSuggestionBox(destinationSuggestions), 300);
  });

  document.addEventListener("click", (event) => {
    if (!originSuggestions.contains(event.target) && event.target !== originInput) {
      hideSuggestionBox(originSuggestions);
    }
    if (!destinationSuggestions.contains(event.target) && event.target !== destinationInput) {
      hideSuggestionBox(destinationSuggestions);
    }
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    clearError();
    renderEngineBadge("", []);
    hideSuggestionBox(originSuggestions);
    hideSuggestionBox(destinationSuggestions);

    const origin = originInput.value.trim();
    const destination = destinationInput.value.trim();
    const avgMpg = Number(avgMpgInput.value);
    const tankCapacityGal = Number(tankCapacityInput.value);
    const startFuelPercent = Number(startFuelInput.value);

    if (!origin || !destination) {
      showError("Origin and destination are required.");
      return;
    }

    if (!Number.isFinite(avgMpg) || avgMpg <= 0 || !Number.isFinite(tankCapacityGal) || tankCapacityGal <= 0) {
      showError("Vehicle MPG and tank capacity must be positive numbers.");
      return;
    }

    if (!Number.isFinite(startFuelPercent) || startFuelPercent < 0 || startFuelPercent > 100) {
      showError("Start fuel must be between 0 and 100.");
      return;
    }

    if (optimizeAbortController) {
      optimizeAbortController.abort();
    }

    const requestToken = ++currentRequestToken;

    optimizeAbortController = new AbortController();
    const timeoutId = window.setTimeout(() => {
      optimizeAbortController.abort();
    }, REQUEST_TIMEOUT_MS);

    setSearching(true);

    try {
      const url = new URL(optimizeUrl, window.location.origin);
      url.searchParams.set("origin", origin);
      url.searchParams.set("destination", destination);
      url.searchParams.set("time_weight", timeWeight.value);
      url.searchParams.set("price_weight", priceWeight.value);
      url.searchParams.set("avg_mpg", String(avgMpg));
      url.searchParams.set("tank_capacity_gal", String(tankCapacityGal));
      url.searchParams.set("start_fuel_percent", String(startFuelPercent));

      if (
        selectedOriginPlace &&
        Number.isFinite(selectedOriginPlace.lat) &&
        Number.isFinite(selectedOriginPlace.lon)
      ) {
        url.searchParams.set("origin_lat", String(selectedOriginPlace.lat));
        url.searchParams.set("origin_lon", String(selectedOriginPlace.lon));
      }

      if (
        selectedDestinationPlace &&
        Number.isFinite(selectedDestinationPlace.lat) &&
        Number.isFinite(selectedDestinationPlace.lon)
      ) {
        url.searchParams.set("destination_lat", String(selectedDestinationPlace.lat));
        url.searchParams.set("destination_lon", String(selectedDestinationPlace.lon));
      }

      const response = await fetch(url.toString(), {
        method: "GET",
        headers: { Accept: "application/json" },
        signal: optimizeAbortController.signal,
      });

      let payload = {};
      try {
        payload = await response.json();
      } catch {
        payload = {};
      }

      if (requestToken !== currentRequestToken) {
        return;
      }

      if (!response.ok) {
        showError(payload.error || "Failed to optimize route.");
        return;
      }

      applyOptimizePayload(payload);
    } catch (error) {
      if (requestToken !== currentRequestToken) {
        return;
      }

      if (error.name === "AbortError") {
        showError("Route request timed out. Try nearby locations or run again.");
      } else {
        showError("Unexpected error while calculating route.");
      }
    } finally {
      window.clearTimeout(timeoutId);
      if (requestToken === currentRequestToken) {
        setSearching(false);
      }
    }
  });
})();
